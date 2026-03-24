#!/usr/bin/env python3
"""
Core Processing Module for Smutscrape
"""

import os
import re
import time
import random
import datetime
import tempfile
import subprocess
import urllib.parse
import feedparser
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from loguru import logger
from termcolor import colored

SELENIUM_AVAILABLE = True
try:
    from selenium.webdriver.common.by import By
except ImportError:
    SELENIUM_AVAILABLE = False

from smutscrape.utilities import (
    get_terminal_width, is_url, handle_vpn, pattern_to_regex,
    should_ignore_video, construct_filename
)
from smutscrape.metadata import finalize_metadata, generate_nfo
from smutscrape.session import is_url_processed
from smutscrape.sites import SiteConfiguration


def get_config_manager():
    from smutscrape.cli import get_config_manager as _get_config_manager
    return _get_config_manager()

def get_session_manager():
    from smutscrape.cli import get_session_manager as _get_session_manager
    return _get_session_manager()

def get_storage_manager():
    from smutscrape.storage import get_storage_manager as _get_storage_manager
    return _get_storage_manager()

def get_selenium_driver(general_config, force_new=False):
    return get_config_manager().get_selenium_driver(force_new=force_new)


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------

def parse_date_loose(date_str):
    if not date_str:
        return None
    date_str = str(date_str).strip()
    for fmt in ["%Y-%m-%dT%H:%M:%S","%Y-%m-%dT%H:%M","%Y-%m-%d","%Y-%m","%Y",
                "%B %d, %Y","%b %d, %Y","%d %B %Y","%d %b %Y","%m/%d/%Y","%d/%m/%Y"]:
        try:
            return datetime.datetime.strptime(date_str[:20], fmt).date()
        except (ValueError, TypeError):
            continue
    m = re.search(r"(\d{4})[-/](\d{1,2})", date_str)
    if m:
        try: return datetime.date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError: pass
    m = re.search(r"(\d{4})", date_str)
    if m:
        try: return datetime.date(int(m.group(1)), 1, 1)
        except ValueError: pass
    return None

def parse_after_threshold(after_str):
    if not after_str:
        return None
    after_str = after_str.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try: return datetime.datetime.strptime(after_str, fmt).date()
        except ValueError: continue
    logger.warning(f"Could not parse --after value '{after_str}'. Date filter disabled.")
    return None

def duration_str_to_minutes(dur_str):
    if not dur_str:
        return None
    dur_str = str(dur_str).strip()
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$", dur_str, re.IGNORECASE)
    if m and any(m.groups()):
        return float(m.group(1) or 0)*60 + float(m.group(2) or 0) + float(m.group(3) or 0)/60
    parts = dur_str.split(":")
    try:
        if len(parts) == 3:   return int(parts[0])*60 + int(parts[1]) + int(parts[2])/60
        elif len(parts) == 2: return int(parts[0]) + int(parts[1])/60
        else:                 return float(dur_str)/60
    except (ValueError, TypeError):
        return None

def video_passes_filters(video_data, after_threshold, min_duration_minutes):
    if after_threshold is not None:
        raw_date = video_data.get("date", "")
        if raw_date:
            video_date = parse_date_loose(raw_date)
            if video_date is not None and video_date < after_threshold:
                logger.info(f"[FILTER] Skipping (date {video_date} < {after_threshold}): {video_data.get('url','?')}")
                return False
        # If date is empty we cannot filter — let it pass and filter on the video page
    if min_duration_minutes is not None and min_duration_minutes > 0:
        raw_dur = video_data.get("duration", "")
        if raw_dur:
            dur_min = duration_str_to_minutes(raw_dur)
            if dur_min is not None and dur_min < min_duration_minutes:
                logger.info(f"[FILTER] Skipping (duration {dur_min:.1f}m < min {min_duration_minutes}m): {video_data.get('url','?')}")
                return False
        # If duration is empty we cannot filter — let it pass
    return True


# ---------------------------------------------------------------------------
# Selenium / fetch helpers
# ---------------------------------------------------------------------------

def pierce_iframe(driver, url, site_config):
    iframe_config = site_config.get('iframe', {})
    if not iframe_config.get('enabled', False):
        driver.get(url)
        return url
    logger.debug(f"Attempting iframe piercing for: {url}")
    driver.get(url)
    time.sleep(random.uniform(1, 2))
    try:
        iframe = driver.find_element(By.CSS_SELECTOR, iframe_config.get('selector', 'iframe'))
        iframe_url = iframe.get_attribute("src")
        if iframe_url:
            logger.info(f"Found iframe with src: {iframe_url}")
            driver.get(iframe_url)
            time.sleep(random.uniform(1, 2))
            return iframe_url
        logger.warning("Iframe found but no src attribute.")
    except Exception as e:
        logger.warning(f"No iframe found or error piercing: {e}")
    return url


def fetch_page(url, user_agents, headers, use_selenium=False, driver=None, retry_count=0):
    """
    Fetch a URL and return BeautifulSoup.
    Falls back to cloudscraper automatically when use_selenium=True but
    driver is None (Chrome not installed).
    """
    if use_selenium and driver is not None:
        logger.debug(f"Fetching URL (selenium): {url}")
        try:
            site_config = globals().get('site_config', {})
            if isinstance(site_config, dict) and site_config.get('iframe', {}).get('enabled'):
                final_url = pierce_iframe(driver, url, site_config)
            else:
                driver.get(url)
                final_url = url
            logger.debug(f"Final URL after iframe handling: {final_url}")
            time.sleep(random.uniform(2, 4))
            return BeautifulSoup(driver.page_source, 'html.parser')
        except Exception as e:
            if retry_count < 2:
                logger.warning(f"Selenium error: {e}. Retrying with new session...")
                new_driver = get_selenium_driver({}, force_new=True)
                if new_driver:
                    return fetch_page(url, user_agents, headers, use_selenium, new_driver, retry_count+1)
            logger.error(f"Failed to fetch {url} with Selenium: {e}")
            return None

    if use_selenium and driver is None:
        logger.warning(
            f"[SELENIUM FALLBACK] Chrome driver unavailable — falling back to cloudscraper for {url}.\n"
            "  Install Chrome/Chromium for full JS-rendered page support."
        )

    import cloudscraper
    scraper = cloudscraper.create_scraper()
    if 'User-Agent' not in headers:
        headers = dict(headers)
        headers['User-Agent'] = random.choice(user_agents)
    logger.debug(f"Fetching URL (requests): {url}")
    time.sleep(random.uniform(1, 3))
    try:
        response = scraper.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return BeautifulSoup(response.content, "html.parser")
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return None


# ---------------------------------------------------------------------------
# Data extraction
# ---------------------------------------------------------------------------

def extract_data(soup, selectors, driver=None, site_config=None):
    data = {}
    if soup is None:
        logger.error("Soup is None; cannot extract data")
        return data
    for field, config in selectors.items():
        if field == 'download_url' and site_config and site_config.get('m3u8_mode', False):
            continue
        if isinstance(config, str):
            elements = soup.select(config)
        elif isinstance(config, dict):
            if 'iframe' in config and driver and site_config:
                try:
                    iframe = driver.find_element(By.CSS_SELECTOR, config['iframe'])
                    driver.switch_to.frame(iframe)
                    iframe_soup = BeautifulSoup(driver.page_source, 'html.parser')
                    elements = iframe_soup.select(config.get('selector', ''))
                    driver.switch_to.default_content()
                except Exception as e:
                    logger.error(f"Failed to pierce iframe for '{field}': {e}")
                    elements = []
            elif 'selector' in config:
                selector = config['selector']
                if isinstance(selector, list):
                    elements = []
                    for sel in selector:
                        elements.extend(soup.select(sel))
                        if elements: break
                elif '|' in selector:
                    namespace, tag = selector.split('|', 1)
                    elements = soup.find_all(f"{namespace}:{tag}")
                else:
                    elements = soup.select(selector)
            elif 'attribute' in config:
                elements = [soup]
            else:
                elements = []
        else:
            elements = []

        if not elements:
            data[field] = ''
            continue

        if isinstance(config, dict) and 'attribute' in config:
            values = [el.get(config['attribute']) for el in elements if el.get(config['attribute'])]
            if field in ('url', 'download_url', 'image', 'date', 'duration'):
                value = values[0] if values else ''
            else:
                value = values[0] if len(values) == 1 else values if values else ''
            if value is None: value = ''
        else:
            value = elements[0].text.strip() if hasattr(elements[0], 'text') and elements[0].text else ''
            if value is None: value = ''

        if field in ['tags', 'actors', 'producers', 'studios'] and not (isinstance(config, dict) and 'attribute' in config):
            values = [el.text.strip() for el in elements if hasattr(el, 'text') and el.text and el.text.strip()]
            seen = set()
            value = [v for v in values if not (v.lower() in seen or seen.add(v.lower()))]

        if isinstance(config, dict) and 'postProcess' in config:
            for step in config['postProcess']:
                if 'replace' in step:
                    for pair in step['replace']:
                        regex, replacement = pair['regex'], pair['with']
                        try:
                            if isinstance(value, list):
                                value = [re.sub(regex, replacement, v, flags=re.DOTALL) if v else '' for v in value]
                            else:
                                value = re.sub(regex, replacement, value, flags=re.DOTALL) if value else ''
                        except re.error:
                            value = ''
        data[field] = value
    return data


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------

def construct_url(base_url, pattern, site_config, mode=None, **kwargs):
    """Construct a full URL from a pattern and parameters."""
    url = pattern
    for key, value in kwargs.items():
        if value is not None:
            arith = re.search(r'\{' + re.escape(key) + r'\s*([\+\-\*\/])\s*(\d+)\}', url)
            if arith:
                op, val = arith.group(1), int(arith.group(2))
                new_val = value+val if op=='+' else value-val if op=='-' else value*val if op=='*' else value//val
                url = url.replace(arith.group(0), str(new_val))
            url = url.replace(f"{{{key}}}", str(value))
    if not url.startswith(('http://', 'https://')):
        url = urllib.parse.urljoin(base_url, url)
    return url


# ---------------------------------------------------------------------------
# resolve_download_dir  (reads download_destinations from config.yaml)
# ---------------------------------------------------------------------------

def resolve_download_dir(general_config):
    """
    Return the first usable local download path from config.yaml.

    Priority order:
      1. download_destinations list — first entry with type==local whose path exists (or can be created)
      2. Legacy flat key  download_dir
      3. Hard fallback    <cwd>/downloads
    """
    destinations = general_config.get('download_destinations', [])
    for dest in destinations:
        if not isinstance(dest, dict):
            continue
        dtype = dest.get('type', 'local')
        if dtype == 'local':
            path = dest.get('path', '')
            if path:
                try:
                    os.makedirs(path, exist_ok=True)
                    logger.debug(f"[DOWNLOAD] Using destination path: {path}")
                    return path
                except OSError as e:
                    logger.warning(f"[DOWNLOAD] Cannot use destination path '{path}': {e}")

    legacy = general_config.get('download_dir')
    if legacy:
        os.makedirs(legacy, exist_ok=True)
        logger.debug(f"[DOWNLOAD] Using legacy download_dir: {legacy}")
        return legacy

    fallback = os.path.join(os.getcwd(), 'downloads')
    os.makedirs(fallback, exist_ok=True)
    logger.warning(f"[DOWNLOAD] No download_destinations configured — falling back to: {fallback}")
    return fallback


# ---------------------------------------------------------------------------
# download_video  (yt-dlp wrapper, streams stdout for live progress)
# ---------------------------------------------------------------------------

# Pattern: [download]  42.3% of  1.23GiB at  3.50MiB/s ETA 00:20
_DL_PROGRESS_RE = re.compile(
    r'\[download\]\s+(\d+\.?\d*)%'
    r'(?:.*?at\s+([\d.]+\s*\S+/s))?'
    r'(?:.*?ETA\s+(\S+))?',
    re.IGNORECASE
)


def download_video(page_url, site_config, general_config, output_dir=None,
                   progress_callback=None):
    """
    Download *page_url* using yt-dlp.
    *progress_callback(pct, speed, eta)* is called whenever yt-dlp prints a
    progress line, allowing the GUI to update a progress bar in real time.
    Returns True on success, False on failure.
    """
    if output_dir is None:
        output_dir = resolve_download_dir(general_config)

    shortcode    = site_config.get('shortcode', 'dl')
    site_dir     = os.path.join(output_dir, shortcode)
    os.makedirs(site_dir, exist_ok=True)
    out_template = os.path.join(site_dir, '%(title)s [%(id)s].%(ext)s')

    cmd = [
        'yt-dlp',
        '--format', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
        '--merge-output-format', 'mp4',
        '--no-playlist',
        '--newline',          # one progress line per line — needed for streaming parse
        '--output', out_template,
        page_url,
    ]

    cookies = general_config.get('cookies_file') or site_config.get('cookies_file')
    if cookies and os.path.isfile(cookies):
        cmd += ['--cookies', cookies]

    rate_limit = general_config.get('rate_limit')
    if rate_limit:
        cmd += ['--limit-rate', str(rate_limit)]

    logger.info(f"[DOWNLOAD] yt-dlp: {page_url}")
    logger.debug(f"[DOWNLOAD] cmd: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            m = _DL_PROGRESS_RE.search(line)
            if m and progress_callback:
                pct   = float(m.group(1))
                speed = m.group(2) or ""
                eta   = m.group(3) or ""
                progress_callback(pct, speed, eta)
            else:
                # Forward non-progress lines to the logger
                if line and not line.startswith('[download]'):
                    logger.debug(f"[yt-dlp] {line}")
        proc.wait(timeout=600)
        if proc.returncode == 0:
            if progress_callback:
                progress_callback(100.0, "", "")
            logger.success(f"[DOWNLOAD] OK: {page_url}")
            return True
        else:
            logger.error(f"[DOWNLOAD] yt-dlp failed (rc={proc.returncode})")
            return False
    except FileNotFoundError:
        logger.error("[DOWNLOAD] yt-dlp not found. Install it: pip install yt-dlp  or  sudo apt install yt-dlp")
        return False
    except subprocess.TimeoutExpired:
        logger.error(f"[DOWNLOAD] Timeout exceeded for {page_url}")
        return False
    except Exception as e:
        logger.error(f"[DOWNLOAD] Unexpected error: {e}")
        return False


# ---------------------------------------------------------------------------
# process_url (direct URL dispatch)
# ---------------------------------------------------------------------------

def process_url(url, site_config, general_config, overwrite=False, re_nfo=False, page="1",
                apply_state=False, state_set=None, after_date=None, min_duration=None):
    page_parts = str(page).split('.')
    current_page_num    = int(page_parts[0])
    current_video_offset = int(page_parts[1]) if len(page_parts) > 1 else 0
    if is_url(url):
        for mode_name, mode_config in site_config.get("modes", {}).items():
            pattern = mode_config.get("url_pattern")
            if pattern and re.search(pattern_to_regex(pattern), url):
                if mode_name == 'video':
                    return process_video_page(url, site_config, general_config, overwrite,
                                              general_config.get('headers', {}), re_nfo,
                                              apply_state=apply_state, state_set=state_set)
                else:
                    constructed_url = url
                    success = False
                    while constructed_url:
                        next_page, new_page_num, page_success = process_list_page(
                            constructed_url, site_config, general_config,
                            current_page_num, current_video_offset,
                            mode_name, "direct_url", overwrite,
                            general_config.get('headers', {}), re_nfo,
                            apply_state=apply_state, state_set=state_set,
                            after_date=after_date, min_duration=min_duration
                        )
                        success = success or page_success
                        constructed_url = next_page
                        current_page_num = new_page_num
                        current_video_offset = 0
                        if constructed_url:
                            time.sleep(general_config["sleep"]["between_pages"])
                    return success
    return False


# ---------------------------------------------------------------------------
# process_list_page
# ---------------------------------------------------------------------------

def process_list_page(url, site_config, general_config, page_num=1, video_offset=0,
                      mode=None, identifier=None, overwrite=False, headers=None,
                      new_nfo=False, do_not_ignore=False, apply_state=False,
                      state_set=None, after_date=None, min_duration=None,
                      dl_progress_cb=None, video_info_cb=None, global_progress_cb=None):
    after_threshold  = parse_after_threshold(after_date) if after_date else None
    min_dur_minutes  = float(min_duration) if min_duration else None

    use_selenium = site_config.get('use_selenium', False)
    driver = get_selenium_driver(general_config) if use_selenium else None
    soup   = fetch_page(url, general_config['user_agents'], headers or {}, use_selenium, driver)
    if soup is None:
        logger.error(f"Failed to fetch page: {url}")
        return None, None, False

    list_scraper       = site_config['scrapers']['list_scraper']
    base_url           = site_config['base_url']
    container_selector = list_scraper['video_container']['selector']

    # ── Container ────────────────────────────────────────────────────────────
    container = None
    tried = []
    if isinstance(container_selector, list):
        for sel in container_selector:
            tried.append(sel)
            container = soup.select_one(sel)
            if container:
                logger.debug(f"[CONTAINER] Matched selector: '{sel}'")
                break
        if not container:
            logger.error(
                f"[CONTAINER] None of {len(tried)} selectors matched on {url}.\n"
                f"  Tried: {tried}\n"
                f"  Page title: {soup.title.string if soup.title else 'N/A'}\n"
                f"  Body classes: {soup.body.get('class', []) if soup.body else 'N/A'}"
            )
            return None, None, False
    else:
        container = soup.select_one(container_selector)
        if not container:
            logger.error(
                f"[CONTAINER] Selector '{container_selector}' matched nothing on {url}.\n"
                f"  Page title: {soup.title.string if soup.title else 'N/A'}"
            )
            return None, None, False

    # ── Video items ──────────────────────────────────────────────────────────
    item_selector  = list_scraper['video_item']['selector']
    video_elements = container.select(item_selector)
    if not video_elements:
        fallback = soup.select("a[href*='/watch/']")
        logger.error(
            f"[ITEMS] Item selector matched 0 elements.\n"
            f"  Container: <{container.name} class='{container.get('class', '')}'>\n"
            f"  Fallback 'a[href*=/watch/]' found: {len(fallback)}"
        )
        if fallback:
            logger.warning(f"[ITEMS] Using {len(fallback)} fallback <a> elements (URL-only mode).")
            video_elements = fallback
        else:
            return None, None, False

    term_width = get_terminal_width()
    print()
    print(colored(f" page {page_num}, {site_config['name'].lower()} {mode}: \"{identifier}\" ".center(term_width, "═"), "yellow"))
    total_items = len(video_elements)
    logger.info(f"Found {total_items} video elements on page {page_num}")
    if after_threshold:  logger.info(f"[FILTER] Date filter: > {after_threshold}")
    if min_dur_minutes:  logger.info(f"[FILTER] Duration filter: > {min_dur_minutes} min")

    success        = False
    skipped_filter = 0
    processed      = 0

    for i, video_element in enumerate(video_elements, 1):
        if video_offset > 0 and i < video_offset:
            continue

        video_data = extract_data(video_element, list_scraper['video_item']['fields'], driver, site_config)

        if not video_passes_filters(video_data, after_threshold, min_dur_minutes):
            skipped_filter += 1
            processed += 1
            if global_progress_cb:
                global_progress_cb(processed, total_items)
            continue

        # ── Resolve URL ──────────────────────────────────────────────────────
        raw_url = video_data.get('url', '')
        if isinstance(raw_url, list):
            raw_url = raw_url[0] if raw_url else ''

        if raw_url:
            video_url = raw_url
            if not video_url.startswith(('http://', 'https://')):
                video_url = f"http:{video_url}" if video_url.startswith('//') else urllib.parse.urljoin(base_url, video_url)
        elif video_data.get('video_key'):
            video_url = construct_url(
                base_url,
                site_config['modes']['video']['url_pattern'],
                site_config, mode='video',
                video=video_data['video_key']
            )
        else:
            logger.debug(f"[ITEMS] No URL for element {i}: {video_data}")
            processed += 1
            if global_progress_cb:
                global_progress_cb(processed, total_items)
            continue

        print()
        print(colored(f"┈┈┈ {i} of {total_items} ┈ {video_url} ".ljust(term_width, "┈"), "magenta"))

        # Emit video info (title from list, date, duration) to GUI before download
        if video_info_cb:
            v_title    = video_data.get('title', '') or video_url.split('/')[-2] or video_url
            v_date     = video_data.get('date', '')
            v_duration = video_data.get('duration', '')
            video_info_cb(v_title, v_date, v_duration)

        if is_url_processed(video_url, state_set) and not (overwrite or new_nfo):
            logger.info(f"Skipping already processed: {video_url}")
            success = True
            processed += 1
            if global_progress_cb:
                global_progress_cb(processed, total_items)
            continue

        if process_video_page(video_url, site_config, general_config, overwrite, headers,
                               new_nfo, do_not_ignore, apply_state=apply_state,
                               state_set=state_set, dl_progress_cb=dl_progress_cb,
                               video_info_cb=video_info_cb):
            success = True

        processed += 1
        if global_progress_cb:
            global_progress_cb(processed, total_items)

    if skipped_filter:
        logger.info(f"[FILTER] Skipped {skipped_filter} videos due to filters.")
    if driver:
        driver.quit()

    # ── Pagination ───────────────────────────────────────────────────────────
    if mode not in site_config.get('modes', {}):
        return None, None, success

    mode_config        = site_config['modes'][mode]
    scraper_pagination = list_scraper.get('pagination', {})
    url_pattern_pages  = mode_config.get('url_pattern_pages')
    max_pages          = mode_config.get('max_pages', scraper_pagination.get('max_pages', float('inf')))

    if page_num >= max_pages:
        return None, None, success

    next_url = None
    if url_pattern_pages:
        m = re.search(r'\{(\w+)\}', url_pattern_pages)
        id_key = m.group(1) if m and m.group(1) != 'page' else mode
        next_url = construct_url(
            base_url, url_pattern_pages, site_config, mode=mode,
            **{id_key: identifier, 'page': page_num + 1}
        )
    elif scraper_pagination and 'next_page' in scraper_pagination:
        cfg = scraper_pagination['next_page']
        el  = soup.select_one(cfg.get('selector', ''))
        if el:
            next_url = el.get(cfg.get('attribute', 'href'))
            if next_url and not next_url.startswith(('http://', 'https://')):
                next_url = urllib.parse.urljoin(base_url, next_url)

    return (next_url, page_num+1, success) if next_url else (None, None, success)


# ---------------------------------------------------------------------------
# process_video_page
# ---------------------------------------------------------------------------

def process_video_page(url, site_config, general_config, overwrite=False, headers=None,
                       new_nfo=False, do_not_ignore=False, apply_state=False,
                       state_set=None, dl_progress_cb=None, video_info_cb=None):
    logger.info(f"Processing video page: {url}")
    use_selenium = site_config.get('use_selenium', False)
    driver = get_selenium_driver(general_config) if use_selenium else None
    soup   = fetch_page(url, general_config['user_agents'], headers or {}, use_selenium, driver)
    if not soup:
        return False

    raw_data = extract_data(soup, site_config['scrapers']['video_scraper'], driver, site_config)
    title    = raw_data.get('title', 'Unknown')

    # Update GUI info panel with data from the actual video page (more accurate)
    if video_info_cb:
        v_date     = raw_data.get('date', '')
        v_duration = raw_data.get('duration', '')
        video_info_cb(title, v_date, v_duration)

    download_cfg = site_config.get('download', {})
    method = download_cfg.get('method', 'yt-dlp')

    if method == 'yt-dlp':
        logger.success(f"Successfully processed video: {title}")
        ok = download_video(url, site_config, general_config,
                            progress_callback=dl_progress_cb)
    else:
        video_url = raw_data.get('download_url')
        if not video_url:
            logger.error("No download URL found")
            return False
        logger.success(f"Successfully processed video: {title}")
        ok = download_video(video_url, site_config, general_config,
                            progress_callback=dl_progress_cb)

    if ok and apply_state and state_set is not None:
        state_set.add(url)
    return ok
