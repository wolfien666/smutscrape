#!/usr/bin/env python3
"""
smutscrape/filters.py
~~~~~~~~~~~~~~~~~~~~~
Date and duration filter helpers used by process_list_page.
Added to support --after (-A) and --min-duration (-D) CLI flags.
"""

import re
import datetime
from loguru import logger


def parse_date_loose(date_str):
    """
    Try to parse a date string loosely.
    Accepts ISO 8601, YYYY-MM, YYYY, and many natural-language formats.
    Returns a datetime.date or None.
    """
    if not date_str:
        return None
    date_str = str(date_str).strip()
    formats = [
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
        "%Y-%m-%d", "%Y-%m", "%Y",
        "%B %d, %Y", "%b %d, %Y",
        "%d %B %Y", "%d %b %Y",
        "%m/%d/%Y", "%d/%m/%Y",
    ]
    for fmt in formats:
        stripped = date_str[:20]
        try:
            return datetime.datetime.strptime(stripped, fmt).date()
        except (ValueError, TypeError):
            continue
    # Fallback: extract YYYY-MM via regex
    m = re.search(r"(\d{4})[-/](\d{1,2})", date_str)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            pass
    # Fallback: extract YYYY only
    m = re.search(r"(\d{4})", date_str)
    if m:
        try:
            return datetime.date(int(m.group(1)), 1, 1)
        except ValueError:
            pass
    return None


def parse_after_threshold(after_str):
    """
    Parse the --after argument value (YYYY-MM or YYYY-MM-DD) into a datetime.date.
    Returns None if input is None or unparseable.
    """
    if not after_str:
        return None
    after_str = after_str.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.datetime.strptime(after_str, fmt).date()
        except ValueError:
            continue
    logger.warning(f"Could not parse --after value '{after_str}'. Date filter disabled.")
    return None


def duration_str_to_minutes(dur_str):
    """
    Convert a duration string to float minutes.
    Accepts:
      - ISO 8601:     PT1H23M45S
      - Clock format: HH:MM:SS or MM:SS
      - Raw seconds:  "3600"
    Returns None if unparseable.
    """
    if not dur_str:
        return None
    dur_str = str(dur_str).strip()
    # ISO 8601 PT#H#M#S
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$", dur_str, re.IGNORECASE)
    if m and any(m.groups()):
        h  = float(m.group(1) or 0)
        mi = float(m.group(2) or 0)
        s  = float(m.group(3) or 0)
        return h * 60 + mi + s / 60
    # Clock HH:MM:SS or MM:SS
    parts = dur_str.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60
        elif len(parts) == 2:
            return int(parts[0]) + int(parts[1]) / 60
        else:
            return float(dur_str) / 60  # assume raw seconds
    except (ValueError, TypeError):
        return None


def video_passes_filters(video_data, after_threshold, min_duration_minutes):
    """
    Returns True if the video should be downloaded, False if it should be skipped.

    Parameters
    ----------
    video_data : dict
        The dict returned by extract_data() for a single list-page item.
        Expected optional keys: 'date', 'duration', 'url'.
    after_threshold : datetime.date or None
        Skip videos whose 'date' field parses to a date earlier than this.
    min_duration_minutes : float or None
        Skip videos whose 'duration' field parses to fewer minutes than this.

    Returns
    -------
    bool
    """
    # Date filter
    if after_threshold is not None:
        raw_date = video_data.get("date", "")
        if raw_date:
            video_date = parse_date_loose(raw_date)
            if video_date is not None and video_date < after_threshold:
                logger.info(
                    f"[FILTER] Skipping (date {video_date} < {after_threshold}): "
                    f"{video_data.get('url', '?')}"
                )
                return False
        # No date field -> cannot filter -> let through

    # Duration filter
    if min_duration_minutes is not None and min_duration_minutes > 0:
        raw_dur = video_data.get("duration", "")
        if raw_dur:
            dur_min = duration_str_to_minutes(raw_dur)
            if dur_min is not None and dur_min < min_duration_minutes:
                logger.info(
                    f"[FILTER] Skipping (duration {dur_min:.1f}m < min {min_duration_minutes}m): "
                    f"{video_data.get('url', '?')}"
                )
                return False
        # No duration field -> cannot filter -> let through

    return True
