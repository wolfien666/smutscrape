#!/usr/bin/env python3
"""
Smutscrape - Adult Content Scraper and Downloader

A modular, extensible framework for scraping and downloading adult content
with rich metadata support and multiple download methods.
"""

__version__ = "1.0.0"
__author__ = "Smutscrape Contributors"
__description__ = "Adult content scraper with metadata support"

# Import main functionality for easy access
from smutscrape.core import (
    construct_url, match_url_to_mode, process_url, process_list_page,
    process_video_page, process_rss_feed
)
from smutscrape.sites import SiteManager, SiteConfiguration
from smutscrape.downloaders import DownloadManager
from smutscrape.session import SessionManager
from smutscrape.storage import StorageManager

# Make CLI entry point available
from smutscrape.cli import main as cli_main

__all__ = [
    '__version__',
    '__author__', 
    '__description__',
    'construct_url',
    'match_url_to_mode',
    'process_url',
    'process_list_page',
    'process_video_page',
    'process_rss_feed',
    'SiteManager',
    'SiteConfiguration',
    'DownloadManager',
    'SessionManager',
    'StorageManager',
    'cli_main'
] 