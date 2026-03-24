#!/usr/bin/env python3
"""
smutscrape/core_patch.py
~~~~~~~~~~~~~~~~~~~~~~~~
Monkey-patches core.process_list_page to support the new
--after (-A) and --min-duration (-D) filter arguments.

This module is automatically imported by smutscrape/__init__.py.
Do not import it directly; it self-applies when imported.
"""

import urllib.parse
from loguru import logger

import smutscrape.core as _core
from smutscrape.filters import video_passes_filters, parse_after_threshold

# Preserve the original function in case it is needed elsewhere
_original_process_list_page = _core.process_list_page


def _patched_process_list_page(
        url, site_config, general_config, page_num=1, video_offset=0,
        mode=None, identifier=None, overwrite=False, headers=None,
        new_nfo=False, do_not_ignore=False, apply_state=False, state_set=None,
        # NEW PARAMETERS
        after_date=None, min_duration=None):
    """
    Drop-in replacement for core.process_list_page with two extra kwargs:

      after_date   (str)   "YYYY-MM" or "YYYY-MM-DD"  passed from --after / -A
      min_duration (float) minutes threshold           passed from --min-duration / -D

    Filtering is applied after extract_data() on each list item,
    before process_video_page() is called, so no wasted HTTP requests occur
    for skipped videos.
    """
    from smutscrape.utilities import get_terminal_width
    from smutscrape.session import is_url_processed
    from smutscrape.core import (
        fetch_page, extract_data, construct_url,
        get_selenium_driver, get_config_manager,
        process_video_page
    )
    from termcolor import colored

    # Parse filter thresholds once per page call
    after_threshold = parse_after_threshold(after_date) if after_date else None
    min_dur_minutes = float(min_duration) if min_duration else None

    use_selenium = site_config.get("use_selenium", False)
    driver = get_selenium_driver(general_config) if use_selenium else None
    soup = fetch_page(url, general_config["user_agents"],
                      headers if headers else {}, use_selenium, driver)
    if soup is None:
        logger.error(f"Failed to fetch page: {url}")
        return None, None, False

    list_scraper = site_config["scrapers"]["list_scraper"]
    base_url = site_config["base_url"]
    container_selector = list_scraper["video_container"]["selector"]

    # Find video container
    container = None
    if isinstance(container_selector, list):
        for selector in container_selector:
            container = soup.select_one(selector)
            if container:
                logger.debug(f"Found container with selector '{selector}'")
                break
        if not container:
            logger.error(f"Could not find video container at {url}")
            return None, None, False
    else:
        container = soup.select_one(container_selector)
        if not container:
            logger.error(f"Could not find video container at {url}")
            return None, None, False

    item_selector = list_scraper["video_item"]["selector"]
    video_elements = container.select(item_selector)
    logger.debug(f"Found {len(video_elements)} video items")
    if not video_elements:
        return None, None, False

    term_width = get_terminal_width()
    print()
    print()
    page_info = f" page {page_num}, {site_config['name'].lower()} {mode}: \"{identifier}\" "
    print(colored(page_info.center(term_width, "="), "yellow"))

    # Log active filters
    if after_threshold:
        logger.info(f"[FILTER] Date filter active: skipping videos uploaded before {after_threshold}")
    if min_dur_minutes:
        logger.info(f"[FILTER] Duration filter active: skipping videos shorter than {min_dur_minutes} min")

    success = False
    skipped_filter = 0

    for i, video_element in enumerate(video_elements, 1):
        if video_offset > 0 and i < video_offset:
            continue

        video_data = extract_data(
            video_element, list_scraper["video_item"]["fields"], driver, site_config
        )

        # ── Apply date + duration filters ──────────────────────────
        if not video_passes_filters(video_data, after_threshold, min_dur_minutes):
            skipped_filter += 1
            continue
        # ───────────────────────────────────────────────────────────

        # Build video URL
        if "url" in video_data and video_data["url"]:
            video_url = video_data["url"]
            if not video_url.startswith(("http://", "https://")):
                video_url = (f"http:{video_url}" if video_url.startswith("//")
                             else urllib.parse.urljoin(base_url, video_url))
        elif "video_key" in video_data and video_data["video_key"]:
            video_url = construct_url(
                base_url, site_config["modes"]["video"]["url_pattern"],
                site_config, mode="video", video=video_data["video_key"]
            )
        else:
            logger.warning(f"Unable to construct video URL for item {i}")
            continue

        print()
        counter = f"{i} of {len(video_elements)}"
        print(colored(f"\u2508\u2508\u2508 {counter} \u2508 {video_url} ".ljust(term_width, "\u2508"), "magenta"))

        if is_url_processed(video_url, state_set) and not (overwrite or new_nfo):
            logger.info(f"Skipping already processed: {video_url}")
            success = True
            continue

        video_success = process_video_page(
            video_url, site_config, general_config, overwrite, headers,
            new_nfo, do_not_ignore, apply_state=apply_state, state_set=state_set
        )
        if video_success:
            success = True

    if skipped_filter:
        logger.info(f"[FILTER] Skipped {skipped_filter} video(s) on page {page_num} due to filters.")

    if driver:
        driver.quit()

    if mode not in site_config["modes"]:
        return None, None, success

    mode_config = site_config["modes"][mode]
    scraper_pagination = list_scraper.get("pagination", {})
    url_pattern_pages = mode_config.get("url_pattern_pages")
    max_pages = mode_config.get("max_pages", scraper_pagination.get("max_pages", float("inf")))

    if page_num >= max_pages:
        logger.warning(f"Stopping pagination: page {page_num} >= max_pages {max_pages}")
        return None, None, success

    next_url = None
    if url_pattern_pages:
        next_url = construct_url(
            base_url, url_pattern_pages, site_config,
            mode=mode, **{mode: identifier, "page": page_num + 1}
        )
        logger.info(f"Next page URL (pattern-based): {next_url}")
    elif scraper_pagination and "next_page" in scraper_pagination:
        next_page_config = scraper_pagination["next_page"]
        next_page_el = soup.select_one(next_page_config.get("selector", ""))
        if next_page_el:
            next_url = next_page_el.get(next_page_config.get("attribute", "href"))
            if next_url and not next_url.startswith(("http://", "https://")):
                next_url = urllib.parse.urljoin(base_url, next_url)
            logger.info(f"Next page URL (selector-based): {next_url}")

    if next_url:
        return next_url, page_num + 1, success
    logger.warning("No next page URL found; stopping pagination.")
    return None, None, success


# Apply the patch
_core.process_list_page = _patched_process_list_page
