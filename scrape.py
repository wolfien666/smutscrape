#!/usr/bin/env python3

import argparse
import yaml
import requests
import cloudscraper
import os
import tempfile
import subprocess
import time
import re
import sys
import random
import io
import string
import textwrap
import json
import pwd
import grp
import shutil
import shlex
import uuid
import feedparser
import urllib.parse
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from smb.SMBConnection import SMBConnection
from datetime import datetime
from loguru import logger
from tqdm import tqdm
from termcolor import colored
from rich.table import Table
from rich.style import Style

# FastAPI imports moved to api.py
FASTAPI_AVAILABLE = True
try:
	from api import run_api_server, FASTAPI_AVAILABLE as API_AVAILABLE
	FASTAPI_AVAILABLE = API_AVAILABLE
except ImportError:
	FASTAPI_AVAILABLE = False

# Download functionality moved to downloaders.py
from downloaders import DownloadManager, download_with_ytdlp_fallback
from sites import SiteManager, SiteConfiguration
from utilities import (
    get_terminal_width, render_ascii, display_options, 
    display_global_examples, display_usage, handle_vpn, console
)

SELENIUM_AVAILABLE = True
try:
	from selenium import webdriver
	from selenium.webdriver.common.by import By
	from webdriver_manager.chrome import ChromeDriverManager
	from selenium.webdriver.chrome.service import Service
	from selenium.webdriver.chrome.options import Options
	from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, ElementClickInterceptedException
except:
	SELENIUM_AVAILABLE = False

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
SITE_DIR = os.path.join(SCRIPT_DIR, 'sites')
STATE_FILE = os.path.join(SCRIPT_DIR, '.state')

last_vpn_action_time = 0
session = requests.Session()

# Initialize download manager (will be properly configured when general_config is loaded)
download_manager = None

# Initialize site manager (will be created when needed)
site_manager = None

def get_site_manager():
	"""Get or create the site manager instance."""
	global site_manager
	if site_manager is None:
		site_manager = SiteManager(SITE_DIR)
	return site_manager
		
class ProgressFile:
	"""A file-like wrapper to track progress during SMB upload."""
	def __init__(self, file_obj, progress_bar):
		self.file_obj = file_obj
		self.pbar = progress_bar
		self.total_size = os.fstat(file_obj.fileno()).st_size
	
	def read(self, size=-1):
		data = self.file_obj.read(size)
		if data:
			self.pbar.update(len(data))
		return data
	
	def __getattr__(self, name):
		return getattr(self.file_obj, name)

def load_state():
	"""Load processed video URLs from .state file into a set."""
	if not os.path.exists(STATE_FILE):
		return set()
	try:
		with open(STATE_FILE, 'r', encoding='utf-8') as f:
			return set(line.strip() for line in f if line.strip())
	except Exception as e:
		logger.error(f"Failed to load state file '{STATE_FILE}': {e}")
		return set()

def save_state(url):
	"""Append a single URL to the end of the .state file."""
	try:
		with open(STATE_FILE, 'a', encoding='utf-8') as f:
			f.write(f"{url}\n")
		logger.info(f"Appended URL to state: {url}")
	except Exception as e:
		logger.error(f"Failed to append to state file '{STATE_FILE}': {e}")
		
def is_url(string):
	"""Check if a string is a URL by parsing it with urlparse."""
	parsed = urlparse(string)
	# A string is considered a URL if it has a netloc (domain) or a scheme
	return bool(parsed.netloc) or bool(parsed.scheme)

def is_url_processed(url, state_set):
	"""Check if a URL is in the state set."""
	return url in state_set

def load_configuration(config_type='general', identifier=None):
	"""Load general or site-specific configuration based on identifier type."""
	if config_type == 'general':
		config_path = os.path.join(SCRIPT_DIR, 'config.yaml')
		try:
			with open(config_path, 'r') as file:
				return yaml.safe_load(file)
		except Exception as e:
			logger.error(f"Failed to load general config from '{config_path}': {e}")
			raise
	
	elif config_type == 'site':
		if not identifier:
			raise ValueError("Site identifier required for site config loading")
		
		# Use the site manager to get site configuration
		site_config = get_site_manager().get_site_by_identifier(identifier)
		if site_config:
			logger.debug(f"Loaded site config for '{identifier}' using SiteManager")
			# Return the raw config dict for backward compatibility
			return site_config.to_dict()
		else:
			logger.debug(f"No site config matched for identifier '{identifier}'")
			return None
	
	raise ValueError(f"Unknown config type: {config_type}")
	
def process_title(title, invalid_chars):
	logger.debug(f"Processing {title} for invalid chars...")
	for char in invalid_chars:
		title = title.replace(char, "")
	logger.debug(f"Processed title: {title}")
	return title

def construct_filename(title, site_config, general_config):
    
    prefix = site_config.get('name_prefix', '')
    suffix = site_config.get('name_suffix', '')
    extension = general_config['file_naming']['extension']
    invalid_chars = general_config['file_naming']['invalid_chars']
    max_chars = general_config['file_naming'].get('max_chars', 255)  # Default to 255 if not specified
    
    # Get unique name settings - use boolean values to handle YAML's various ways of representing true/false
    unique_name = bool(site_config.get("unique_name", False))
    make_unique = bool(general_config['file_naming'].get('make_unique', False))
    
    # Process title by removing invalid characters
    processed_title = process_title(title, invalid_chars)
    
    # Generate a unique ID if needed (6 random characters)
    unique_id = '_' + ''.join(random.choices(string.ascii_lowercase + string.ascii_uppercase + string.digits, k=6)) if unique_name or make_unique else ''
    
    # Calculate available length for the title, accounting for the unique ID if present
    fixed_length = len(prefix) + len(suffix) + len(extension) + len(unique_id)
    max_title_chars = min(max_chars, 255) - fixed_length  # Hard cap at 255 chars total
    
    if max_title_chars <= 0:
        logger.warning(f"Fixed filename parts ({fixed_length} chars) exceed max_chars ({max_chars}); truncating to fit.")
        max_title_chars = max(1, 255 - fixed_length)  # Ensure at least 1 char for title if possible
    
    # Truncate title if necessary
    if len(processed_title) > max_title_chars:
        processed_title = processed_title[:max_title_chars].rstrip()
        logger.debug(f"Truncated title to {max_title_chars} chars: {processed_title}")
    
    # Construct final filename with unique ID before extension
    if unique_id:
        filename = f"{prefix}{processed_title}{suffix}{unique_id}{extension}"
    else:
        filename = f"{prefix}{processed_title}{suffix}{extension}"
    
    # Double-check byte length (Linux limit is 255 bytes, not chars)
    while len(filename.encode('utf-8')) > 255:
        excess = len(filename.encode('utf-8')) - 255
        trim_chars = excess // 4 + 1  # Rough estimate for UTF-8; adjust conservatively
        processed_title = processed_title[:-trim_chars].rstrip()
        
        # Reconstruct the filename with the trimmed title
        if unique_id:
            filename = f"{prefix}{processed_title}{suffix}{unique_id}{extension}"
        else:
            filename = f"{prefix}{processed_title}{suffix}{extension}"
            
        logger.debug(f"Filename exceeded 255 bytes; trimmed to: {filename}")

    logger.debug(f"Generated filename: {filename}")
    return filename

	
def construct_url(base_url, pattern, site_config, mode=None, **kwargs):
	mode_specific_rules = {}
	if mode and mode in site_config.get('modes', {}) and 'url_encoding_rules' in site_config['modes'][mode]:
		mode_specific_rules = site_config['modes'][mode]['url_encoding_rules']
		logger.debug(f"Loaded mode-specific URL encoding rules for mode '{mode}': {mode_specific_rules}")

	site_specific_rules = site_config.get('url_encoding_rules', {})
	if site_specific_rules:
		logger.debug(f"Loaded site-specific URL encoding rules: {site_specific_rules}")

	encoded_kwargs = {}
	logger.debug(f"Constructing URL with pattern '{pattern}' and mode '{mode}'. Applying encoding rules if any.")
	
	# Handle arithmetic expressions like {page - 1}, {page + 2}, etc.
	page_pattern = r'\{page\s*([+-])\s*(\d+)\}'  # Matches {page - 1}, {page + 2}, etc.
	match = re.search(page_pattern, pattern)
	if match and 'page' in kwargs:
		operator, value = match.group(1), int(match.group(2))
		page_value = kwargs.get('page')
		if page_value is not None:
			try:
				page_num = int(page_value)
				if operator == '+':
					adjusted_page = page_num + value
				elif operator == '-':
					adjusted_page = page_num - value
				# Replace the full expression (e.g., "{page - 1}") with the computed value
				pattern = pattern.replace(match.group(0), str(adjusted_page))
				logger.debug(f"Adjusted page {page_value} {operator} {value} = {adjusted_page}")
			except (ValueError, TypeError):
				logger.error(f"Invalid page value '{page_value}' for arithmetic adjustment")
				pattern = pattern.replace(match.group(0), str(page_value))  # Fallback to original
		else:
			pattern = pattern.replace(match.group(0), '')  # Remove if page is None
	elif 'page' in kwargs:
		# Ensure 'page' kwarg is preserved if not used in arithmetic, will be handled by the loop below
		pass # No special action needed here, will be processed by the main loop
	
	# Encode remaining kwargs with rules
	for k, v in kwargs.items():
		if k == 'page' and match:  # Skip page if already handled by arithmetic adjustment of the pattern
			continue
		
		if isinstance(v, str):
			encoded_v = v
			# Apply mode-specific rules first
			if mode_specific_rules:
				for original, replacement in mode_specific_rules.items():
					if original in encoded_v:
						logger.debug(f"Applying mode rule for key '{k}': '{original}' -> '{replacement}' to value '{encoded_v}'")
						encoded_v = encoded_v.replace(original, replacement)
						logger.debug(f"Value after mode rule for key '{k}': '{encoded_v}'")
			
			# Then apply site-specific rules to the (potentially already modified) string
			if site_specific_rules:
				for original, replacement in site_specific_rules.items():
					if original in encoded_v:
						logger.debug(f"Applying site rule for key '{k}': '{original}' -> '{replacement}' to value '{encoded_v}'")
						encoded_v = encoded_v.replace(original, replacement)
						logger.debug(f"Value after site rule for key '{k}': '{encoded_v}'")
			
			encoded_kwargs[k] = encoded_v
		elif k == 'page' and v is None and not match : # handle case where page is None and not part of an arithmetic expression
			encoded_kwargs[k] = None # Preserve None page if not handled by arithmetic
		else:
			encoded_kwargs[k] = v # Preserve non-string or already handled page values
	
	# Format the pattern with encoded kwargs, handling missing keys gracefully
	try:
		# Filter out None page values before formatting if they are not explicitly in the pattern
		# or if the pattern expects a page but it's None (e.g. for first page where page is not in URL)
		final_format_kwargs = {key: val for key, val in encoded_kwargs.items() if val is not None or f"{{{key}}}" in pattern}
		path = pattern.format(**final_format_kwargs)
	except KeyError as e:
		logger.error(f"Missing key in URL pattern '{pattern}': {e}. Available kwargs: {final_format_kwargs.keys()}")
		return None
	
	full_url = urllib.parse.urljoin(base_url, path)
	return full_url


def get_selenium_driver(general_config, force_new=False):
	selenium_config = general_config.get('selenium', {})
	chromedriver_path = selenium_config.get('chromedriver_path')  # None if not specified
	
	create_new = force_new or 'selenium_driver' not in general_config
	if not create_new:
		try:
			driver = general_config['selenium_driver']
			driver.current_url  # Test if the driver is still valid
		except Exception as e:
			logger.warning(f"Existing Selenium driver invalid: {e}")
			create_new = True
	
	if create_new:
		if 'selenium_driver' in general_config:
			try:
				general_config['selenium_driver'].quit()
			except:
				pass
		
		chrome_options = Options()
		chrome_options.add_argument("--headless")
		chrome_options.add_argument("--no-sandbox")
		chrome_options.add_argument("--disable-dev-shm-usage")
		chrome_options.add_argument("--disable-gpu")
		chrome_options.add_argument("--window-size=1920,1080")
		chrome_options.add_argument("--disable-blink-features=AutomationControlled")
		chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
		
		chrome_binary = selenium_config.get('chrome_binary')
		if chrome_binary:
			chrome_options.binary_location = chrome_binary
			logger.debug(f"Set Chrome binary location to: {chrome_binary}")
		
		try:
			if chromedriver_path:
				# Use user-specified ChromeDriver path
				logger.debug(f"Using user-specified ChromeDriver at: {chromedriver_path}")
				service = Service(executable_path=chromedriver_path)
			else:
				# Fallback to webdriver_manager
				logger.debug("No chromedriver_path specified; using webdriver_manager to fetch ChromeDriver")
				service = Service(ChromeDriverManager().install())
				logger.debug(f"Using ChromeDriver at: {service.path}")
			
			driver = webdriver.Chrome(service=service, options=chrome_options)
			logger.debug(f"Initialized Selenium driver with Chrome version: {driver.capabilities['browserVersion']}")
		except Exception as e:
			logger.error(f"Failed to initialize Selenium driver: {e}")
			return None
		
		driver.execute_script("""
			(function() {
				let open = XMLHttpRequest.prototype.open;
				XMLHttpRequest.prototype.open = function(method, url) {
					if (url.includes(".m3u8")) {
						console.log("🔥 Found M3U8 via XHR:", url);
					}
					return open.apply(this, arguments);
				};
			})();
		""")
		general_config['selenium_driver'] = driver
	
	# Store User-Agent for later use
	user_agent = driver.execute_script("return navigator.userAgent;")
	general_config['selenium_user_agent'] = user_agent
	logger.debug(f"Selenium User-Agent: {user_agent}")
	return general_config['selenium_driver']


def process_url(url, site_config, general_config, overwrite, re_nfo, start_page, apply_state=False, state_set=None):
	headers = general_config.get("headers", {}).copy()
	headers["User-Agent"] = random.choice(general_config["user_agents"])
	mode, scraper = match_url_to_mode(url, site_config)
	
	# Split start_page into page_num and video_offset
	page_parts = start_page.split('.')
	page_num = int(page_parts[0])
	video_offset = int(page_parts[1]) if len(page_parts) > 1 else 0
	
	# Check if the input is a full URL using is_url
	is_full_url = is_url(url)
	
	if mode:
		logger.info(f"Matched URL to mode '{mode}' with scraper '{scraper}'")
		if mode == "video":
			success = process_video_page(
				url, site_config, general_config, overwrite, headers, re_nfo,
				apply_state=apply_state, state_set=state_set
			)
		elif mode == "rss":
			success = process_rss_feed(
				url, site_config, general_config, overwrite, headers, re_nfo,
				apply_state=apply_state, state_set=state_set
			)
		else:
			# Extract identifier only if not a full URL
			identifier = url.split("/")[-1].split(".")[0] if not is_full_url else None
			current_page_num = page_num
			current_video_offset = video_offset
			mode_config = site_config["modes"][mode]
			
			# Use the original URL if provided, otherwise construct it
			if is_full_url:
				effective_url = url
				logger.info(f"Using provided URL: {effective_url}")
			else:
				if page_num > 1 and mode_config.get("url_pattern_pages"):
					effective_url = construct_url(
						site_config["base_url"],
						mode_config["url_pattern_pages"],
						site_config,
						mode=mode,
						**{mode: identifier, "page": page_num}
					)
					logger.info(f"Starting at custom page {page_num}.{video_offset}: {effective_url}")
				else:
					effective_url = construct_url(
						site_config["base_url"],
						mode_config["url_pattern"],
						site_config,
						mode=mode,
						**{mode: identifier}
					)
					logger.info(f"Constructed URL: {effective_url}")
			
			success = False
			while effective_url:
				next_page, new_page_number, page_success = process_list_page(
					effective_url, site_config, general_config, current_page_num, current_video_offset,
					mode, identifier, overwrite, headers, re_nfo, apply_state=apply_state, state_set=state_set
				)
				success = success or page_success
				effective_url = next_page
				current_page_num = new_page_number
				current_video_offset = 0  # Reset after first page
				time.sleep(general_config["sleep"]["between_pages"])
	else:
		logger.warning("URL didn't match any specific mode; attempting all configured modes.")
		available_modes = site_config.get("modes", {})
		success = False
		for mode_name in available_modes:
			if mode_name == "video":
				logger.info("Trying 'video' mode...")
				success = process_video_page(
					url, site_config, general_config, overwrite, headers, re_nfo,
					apply_state=apply_state, state_set=state_set
				)
				if success:
					logger.info("Video mode succeeded.")
					break
			elif mode_name == "rss":
				logger.info("Trying 'rss' mode...")
				success = process_rss_feed(
					url, site_config, general_config, overwrite, headers, re_nfo,
					apply_state=apply_state, state_set=state_set
				)
				if success:
					logger.info("RSS mode succeeded.")
					break
			else:
				logger.info(f"Attempting mode '{mode_name}'...")
				identifier = url.split("/")[-1].split(".")[0] if not is_full_url else None
				current_page_num = page_num
				current_video_offset = video_offset
				mode_config = site_config["modes"][mode_name]
				
				# Use the original URL if provided, otherwise construct it
				if is_full_url:
					constructed_url = url
					logger.info(f"Using provided URL for mode '{mode_name}': {constructed_url}")
				else:
					try:
						constructed_url = construct_url(
							site_config["base_url"],
							mode_config["url_pattern"] if current_page_num == 1 else mode_config.get("url_pattern_pages", mode_config["url_pattern"]),
							site_config,
							mode=mode_name,
							**{mode_name: identifier, "page": current_page_num if current_page_num > 1 else None}
						)
						logger.info(f"Starting at custom page {current_page_num}.{current_video_offset}: {constructed_url}")
					except Exception as e:
						logger.warning(f"Mode '{mode_name}' failed to construct URL: {e}")
						continue
				
				success = False
				while constructed_url:
					next_page, new_page_number, page_success = process_list_page(
						constructed_url, site_config, general_config, current_page_num, current_video_offset,
						mode_name, identifier, overwrite, headers, re_nfo, apply_state=apply_state, state_set=state_set
					)
					success = success or page_success
					constructed_url = next_page
					current_page_num = new_page_number
					current_video_offset = 0  # Reset after first page
					time.sleep(general_config["sleep"]["between_pages"])
				if success:
					logger.info(f"Mode '{mode_name}' succeeded.")
					break
		
		if not success:
			logger.error(f"Failed to process URL '{url}' with any mode.")
			process_fallback_download(url, general_config, overwrite)
	
	return success
		

def process_list_page(url, site_config, general_config, page_num=1, video_offset=0, mode=None, identifier=None, overwrite=False, headers=None, new_nfo=False, do_not_ignore=False, apply_state=False, state_set=None):
	use_selenium = site_config.get('use_selenium', False)
	driver = get_selenium_driver(general_config) if use_selenium else None
	soup = fetch_page(url, general_config['user_agents'], headers if headers else {}, use_selenium, driver)
	if soup is None:
		logger.error(f"Failed to fetch page: {url}")
		return None, None, False
	
	list_scraper = site_config['scrapers']['list_scraper']
	base_url = site_config['base_url']
	container_selector = list_scraper['video_container']['selector']
	
	container = None
	if isinstance(container_selector, list):
		for selector in container_selector:
			container = soup.select_one(selector)
			if container:
				logger.debug(f"Found container with selector '{selector}': {container.name}[class={container.get('class', [])}]")
				break
		if not container:
			logger.error(f"Could not find video container at {url} with any selector in {container_selector}")
			return None, None, False
	else:
		logger.debug(f"Searching for container with selector: '{container_selector}'")
		container = soup.select_one(container_selector)
		if not container:
			logger.error(f"Could not find video container at {url} with selector '{container_selector}'")
			return None, None, False
		logger.debug(f"Found container: {container.name}[class={container.get('class', [])}]")
	
	item_selector = list_scraper['video_item']['selector']
	logger.debug(f"Searching for video items with selector: '{item_selector}'")
	video_elements = container.select(item_selector)
	logger.debug(f"Found {len(video_elements)} video items")
	if not video_elements:
		logger.debug(f"No videos found on page {page_num} with selector '{item_selector}'")
		return None, None, False
	
	term_width = get_terminal_width()
	print()
	print()
	page_info = f" page {page_num}, {site_config['name'].lower()} {mode}: \"{identifier}\" "
	page_line = page_info.center(term_width, "═")
	print(colored(page_line, "yellow"))
	
	success = False
	for i, video_element in enumerate(video_elements, 1):
		if video_offset > 0 and i < video_offset:  # Start at video_offset, 1-based
			continue
		
		video_data = extract_data(video_element, list_scraper['video_item']['fields'], driver, site_config)
		if 'url' in video_data:
			video_url = video_data['url']
			if not video_url.startswith(('http://', 'https://')):
				video_url = f"http:{video_url}" if video_url.startswith('//') else urllib.parse.urljoin(base_url, video_url)
		elif 'video_key' in video_data:
			video_url = construct_url(base_url, site_config['modes']['video']['url_pattern'], site_config, mode='video', video=video_data['video_key'])
		else:
			logger.warning("Unable to construct video URL")
			continue
		video_title = video_data.get('title', '').strip() or video_element.text.strip()
		
		print()
		counter = f"{i} of {len(video_elements)}"
		counter_line = f"┈┈┈ {counter} ┈ {video_url} ".ljust(term_width, "┈")
		print(colored(counter_line, "magenta"))
		
		if is_url_processed(video_url, state_set) and not (overwrite or new_nfo):
			logger.info(f"Skipping already processed video: {video_url}")
			success = True
			continue
		
		video_success = process_video_page(video_url, site_config, general_config, overwrite, headers, new_nfo, do_not_ignore, apply_state=apply_state, state_set=state_set)
		if video_success:
			success = True
	
	if driver:
		driver.quit()
	
	if mode not in site_config['modes']:
		logger.warning(f"No pagination for mode '{mode}' as it's not defined in site_config['modes']")
		return None, None, success
	
	mode_config = site_config['modes'][mode]
	scraper_pagination = list_scraper.get('pagination', {})
	url_pattern_pages = mode_config.get('url_pattern_pages')
	max_pages = mode_config.get('max_pages', scraper_pagination.get('max_pages', float('inf')))
	
	if page_num >= max_pages:
		logger.warning(f"Stopping pagination: page_num={page_num} >= max_pages={max_pages}")
		return None, None, success
	
	next_url = None
	if url_pattern_pages:
		next_url = construct_url(
			base_url,
			url_pattern_pages,
			site_config,
			mode=mode,
			**{mode: identifier, 'page': page_num + 1}
		)
		logger.info(f"Generated next page URL (pattern-based): {next_url}")
		
	elif scraper_pagination:
		if 'next_page' in scraper_pagination:
			next_page_config = scraper_pagination['next_page']
			next_page = soup.select_one(next_page_config.get('selector', ''))
			if next_page:
				next_url = next_page.get(next_page_config.get('attribute', 'href'))
				if next_url and not next_url.startswith(('http://', 'https://')):
					next_url = urllib.parse.urljoin(base_url, next_url)
				logger.info(f"Found next page URL (selector-based): {next_url}")
			else:
				logger.warning(f"No 'next' element found with selector '{next_page_config.get('selector')}'")
	
	if next_url:
		return next_url, page_num + 1, success
	logger.warning("No next page URL generated; stopping pagination")
	return None, None, success
	
	
def process_rss_feed(url, site_config, general_config, overwrite=False, headers=None, re_nfo=False, apply_state=False, state_set=None):
	"""Process an RSS feed, downloading videos from oldest to newest."""
	logger.info(f"Fetching RSS feed: {url}")
	
	# Fetch the RSS feed
	feed = feedparser.parse(url)
	if feed.bozo:
		logger.error(f"Failed to parse RSS feed at {url}: {feed.bozo_exception}")
		return False
	
	entries = feed.entries
	if not entries:
		logger.warning(f"No entries found in RSS feed at {url}")
		return False
	
	# Reverse entries to process from oldest to newest
	entries = list(reversed(entries))
	logger.info(f"Found {len(entries)} entries in RSS feed; processing from oldest to newest")
	
	term_width = get_terminal_width()
	print()
	print()
	feed_info = f" RSS feed for {site_config['name']} "
	feed_line = feed_info.center(term_width, "═")
	print(colored(feed_line, "yellow"))
	
	success = False
	rss_scraper = site_config['scrapers']['rss_scraper']
	
	for i, entry in enumerate(entries, 1):
		# Extract video URL from the <link> element
		video_url = entry.get('link', '')
		if not video_url or not is_url(video_url):
			logger.warning(f"Entry {i} has no valid URL; skipping")
			continue
		
		# Convert feedparser entry to XML string for BeautifulSoup
		entry_xml = '<item>'
		entry_xml += f'<title><![CDATA[{entry.get("title", "")}]]></title>'
		entry_xml += f'<link><![CDATA[{entry.get("link", "")}]]></link>'
		entry_xml += f'<description><![CDATA[{entry.get("description", "")}]]></description>'
		if 'content' in entry and entry.content:
			entry_xml += f'<content:encoded><![CDATA[{entry.content[0].value}]]></content:encoded>'
		for category in entry.get('categories', []):
			entry_xml += f'<category><![CDATA[{category[0]}]]></category>'
		entry_xml += '</item>'
		
		# Parse the entry with BeautifulSoup using lxml parser
		entry_soup = BeautifulSoup(entry_xml, 'lxml-xml')  # Use lxml-xml for proper XML parsing
		
		# Extract data using the scraper configuration
		video_data = extract_data(entry_soup, rss_scraper['video_item']['fields'], None, site_config)
		
		# Fallback to RSS fields if not found in content
		video_title = video_data.get('title', '').strip() or entry.get('title', 'Untitled').strip()
		video_data['title'] = video_title
		video_data['url'] = video_url
		
		print()
		counter = f"{i} of {len(entries)}"
		counter_line = f"┈┈┈ {counter} ┈ {video_url} ".ljust(term_width, "┈")
		print(colored(counter_line, "magenta"))
		
		if is_url_processed(video_url, state_set) and not (overwrite or re_nfo):
			logger.info(f"Skipping already processed video: {video_url}")
			success = True
			continue
		
		# Process the video page
		video_success = process_video_page(
			video_url, site_config, general_config, overwrite, headers, re_nfo,
			apply_state=apply_state, state_set=state_set
		)
		if video_success:
			success = True
	
	return success

def process_video_page(url, site_config, general_config, overwrite=False, headers=None, new_nfo=False, do_not_ignore=False, apply_state=False, state_set=None):
	global last_vpn_action_time
	vpn_config = general_config.get('vpn', {})
	if vpn_config.get('enabled', False):
		current_time = time.time()
		if current_time - last_vpn_action_time > vpn_config.get('new_node_time', 300):
			last_vpn_action_time = handle_vpn(general_config, 'new_node') or last_vpn_action_time
	
	logger.info(f"Processing video page: {url}")
	use_selenium = site_config.get('use_selenium', False)
	driver = get_selenium_driver(general_config) if use_selenium else None
	original_url = url
	
	iframe_url = None
	video_url = None
	raw_data = {'title': original_url.split('/')[-2]}
	
	if site_config.get('m3u8_mode', False) and driver:
		video_scraper = site_config['scrapers']['video_scraper']
		iframe_config = next(({'enabled': True, 'selector': config['iframe']} for field, config in video_scraper.items() 
							  if isinstance(config, dict) and 'iframe' in config), None)
		if iframe_config:
			logger.debug(f"Piercing iframe '{iframe_config['selector']}' for M3U8")
			driver.get(original_url)
			time.sleep(random.uniform(1, 2))
			try:
				iframe = driver.find_element(By.CSS_SELECTOR, iframe_config['selector'])
				iframe_url = iframe.get_attribute("src")
				if iframe_url:
					logger.info(f"Found iframe: {iframe_url}")
					driver.get(iframe_url)
					time.sleep(random.uniform(1, 2))
					m3u8_url, cookies = extract_m3u8_urls(driver, iframe_url, site_config)
					if m3u8_url:
						video_url = m3u8_url
						headers = headers or general_config.get('headers', {}).copy()
						headers.update({"Cookie": cookies, "Referer": iframe_url, 
										"User-Agent": general_config.get('selenium_user_agent', random.choice(general_config['user_agents']))})
			except Exception as e:
				logger.warning(f"Iframe error: {e}")
		soup = fetch_page(original_url, general_config['user_agents'], headers or {}, use_selenium, driver)
		if soup:
			raw_data = extract_data(soup, site_config['scrapers']['video_scraper'], driver, site_config)
		video_url = video_url or raw_data.get('download_url')
	elif site_config.get('mp4_mode', False) and driver: # New MP4 mode
		logger.info("Attempting MP4 mode detection.")
		video_scraper = site_config['scrapers']['video_scraper']
		iframe_config = next(({'enabled': True, 'selector': config['iframe']} for field, config in video_scraper.items()
							  if isinstance(config, dict) and 'iframe' in config), None)
		page_to_scan = original_url
		if iframe_config:
			logger.debug(f"Piercing iframe '{iframe_config['selector']}' for MP4")
			driver.get(original_url)
			time.sleep(random.uniform(1, 2))
			try:
				iframe = driver.find_element(By.CSS_SELECTOR, iframe_config['selector'])
				iframe_src = iframe.get_attribute("src")
				if iframe_src:
					logger.info(f"Found iframe for MP4 scan: {iframe_src}")
					page_to_scan = iframe_src # Scan inside iframe
					# driver.get(iframe_src) # Already done by extract_mp4_urls
					# time.sleep(random.uniform(1, 2))
			except Exception as e:
				logger.warning(f"Iframe error during MP4 mode: {e}")

		mp4_found_url, cookies = extract_mp4_urls(driver, page_to_scan, site_config)
		if mp4_found_url:
			video_url = mp4_found_url
			site_config['download'] = {'method': 'requests'} # Override to requests for MP4
			logger.info(f"MP4 detected: {video_url}, download method set to 'requests'")
			headers = headers or general_config.get('headers', {}).copy()
			headers.update({"Cookie": cookies, "Referer": page_to_scan,
							"User-Agent": general_config.get('selenium_user_agent', random.choice(general_config['user_agents']))})
		soup = fetch_page(original_url, general_config['user_agents'], headers or {}, use_selenium, driver)
		if soup:
			raw_data = extract_data(soup, site_config['scrapers']['video_scraper'], driver, site_config)
		video_url = video_url or raw_data.get('download_url') # Fallback to scraped URL if direct detection fails
	elif site_config.get('detect_mode', False) and driver: # New Detect mode
		logger.info("Attempting Detect mode (MP4 then M3U8).")
		video_scraper = site_config['scrapers']['video_scraper']
		iframe_config = next(({'enabled': True, 'selector': config['iframe']} for field, config in video_scraper.items()
							  if isinstance(config, dict) and 'iframe' in config), None)
		page_to_scan = original_url
		scan_headers = headers or general_config.get('headers', {}).copy()

		if iframe_config:
			logger.debug(f"Piercing iframe '{iframe_config['selector']}' for Detect mode")
			driver.get(original_url)
			time.sleep(random.uniform(1, 2))
			try:
				iframe = driver.find_element(By.CSS_SELECTOR, iframe_config['selector'])
				iframe_src = iframe.get_attribute("src")
				if iframe_src:
					logger.info(f"Found iframe for Detect scan: {iframe_src}")
					page_to_scan = iframe_src
					# driver.get(iframe_src) # Done by extract functions
					# time.sleep(random.uniform(1, 2))
			except Exception as e:
				logger.warning(f"Iframe error during Detect mode: {e}")
		
		# Try MP4 first
		mp4_found_url, mp4_cookies = extract_mp4_urls(driver, page_to_scan, site_config)
		if mp4_found_url:
			video_url = mp4_found_url
			site_config['download'] = {'method': 'requests'}
			logger.info(f"Detect mode: MP4 found: {video_url}, download method 'requests'")
			scan_headers.update({"Cookie": mp4_cookies, "Referer": page_to_scan,
								 "User-Agent": general_config.get('selenium_user_agent', random.choice(general_config['user_agents']))})
		else:
			logger.info("Detect mode: MP4 not found, trying M3U8.")
			# Try M3U8 second
			m3u8_found_url, m3u8_cookies = extract_m3u8_urls(driver, page_to_scan, site_config)
			if m3u8_found_url:
				video_url = m3u8_found_url
				site_config['download'] = {'method': 'ffmpeg'} # Ensure ffmpeg for m3u8
				logger.info(f"Detect mode: M3U8 found: {video_url}, download method 'ffmpeg'")
				scan_headers.update({"Cookie": m3u8_cookies, "Referer": page_to_scan,
									 "User-Agent": general_config.get('selenium_user_agent', random.choice(general_config['user_agents']))})
			else:
				logger.warning("Detect mode: Neither MP4 nor M3U8 found via network sniffing.")
		
		headers = scan_headers # Update main headers with cookies if found
		soup = fetch_page(original_url, general_config['user_agents'], headers, use_selenium, driver)
		if soup:
			raw_data = extract_data(soup, site_config['scrapers']['video_scraper'], driver, site_config)
		video_url = video_url or raw_data.get('download_url') # Fallback
	else:
		soup = fetch_page(original_url, general_config['user_agents'], headers or {}, use_selenium, driver)
		if soup is None and use_selenium:
			logger.warning("Selenium failed; retrying with requests")
			soup = fetch_page(original_url, general_config['user_agents'], headers or {}, False, None)
		if soup is None:
			logger.error(f"Failed to fetch: {original_url}")
			if driver:
				driver.quit()
			return False
		raw_data = extract_data(soup, site_config['scrapers']['video_scraper'], driver, site_config)
		video_url = raw_data.get('download_url')
	
	video_url = video_url or original_url
	video_title = raw_data.get('title', '').strip() or 'Untitled'

	remove_title_string = site_config.get('remove_title_string', '')

	if remove_title_string:
		if video_title.endswith(remove_title_string):
			video_title = video_title[:-len(remove_title_string)].rstrip()
			logger.debug(f"Removed string '{remove_title_string}' from title: {video_title}")
		else:
			logger.debug(f"\"{remove_title_string}\" not found in title: {video_title}")
	else:
		logger.debug("Site config has no remove_title_string set")
	
	raw_data['title'] = video_title
	logger.debug(f"Final title: {raw_data['title']}")
	raw_data['url'] = original_url
	
	if not do_not_ignore and should_ignore_video(raw_data, general_config['ignored']):
		if driver:
			driver.quit()
		return True
	
	final_metadata = finalize_metadata(raw_data, general_config)
	file_name = construct_filename(final_metadata['title'], site_config, general_config)
	destination_config = general_config['download_destinations'][0]
	state_updated = False
	if destination_config['type'] == 'smb':
		smb_path = os.path.join(destination_config['path'], file_name)
		if not overwrite and file_exists_on_smb(destination_config, smb_path):
			logger.info(f"File '{smb_path}' exists on SMB share. Skipping download.")
			if apply_state and not is_url_processed(original_url, state_set):
				state_set.add(original_url)
				save_state(original_url)
				logger.info(f"Retroactively added {original_url} to state due to existing file and --applystate")
				state_updated = True
			if general_config.get('make_nfo', False) and has_metadata_selectors(site_config):
				smb_nfo_path = os.path.join(destination_config['path'], f"{file_name.rsplit('.', 1)[0]}.nfo")
				if not (new_nfo or file_exists_on_smb(destination_config, smb_nfo_path)):
					temp_nfo_path = os.path.join(tempfile.gettempdir(), 'smutscrape', f"{file_name.rsplit('.', 1)[0]}.nfo")
					os.makedirs(os.path.dirname(temp_nfo_path), exist_ok=True)
					generate_nfo(temp_nfo_path, final_metadata, True)
					upload_to_smb(temp_nfo_path, smb_nfo_path, destination_config, overwrite)
					os.remove(temp_nfo_path)
			if driver:
				driver.quit()
			return True
	if destination_config['type'] == 'smb':
		temp_dir = destination_config.get('temporary_storage', os.path.join(tempfile.gettempdir(), 'smutscrape'))
		os.makedirs(temp_dir, exist_ok=True)
		final_destination_path = os.path.join(temp_dir, file_name)
		# logger.debug(f"Final SMB destination path: {final_destination_path}")
		temp_destination_path = os.path.join(temp_dir, f".{file_name}")  # Changed from .part suffix to . prefix
		logger.debug(f"Temporary intermediate path: {temp_destination_path}")
	else:
		final_destination_path = os.path.join(destination_config['path'], file_name)
		temp_destination_path = final_destination_path  # No prefix for local
	
	# Check for existing complete file in temp dir
	if destination_config['type'] == 'smb' and not overwrite and os.path.exists(final_destination_path):
		video_info = download_manager.get_video_metadata(final_destination_path)
		if video_info:
			logger.info(f"Valid complete file '{final_destination_path}' exists in temp dir. Skipping download.")
			success = True
		else:
			logger.warning(f"Invalid file '{final_destination_path}' in temp dir. Redownloading.")
			os.remove(final_destination_path)
			success = download_video(video_url, final_destination_path, site_config, general_config, headers, final_metadata, overwrite)
	else:
		success = download_video(video_url, final_destination_path, site_config, general_config, headers, final_metadata, overwrite)
	if success and general_config.get('make_nfo', False) and has_metadata_selectors(site_config):
		logger.debug(f"Successful video download, now generating nfo.")
		generate_nfo(final_destination_path, final_metadata, overwrite or new_nfo)
	if success and destination_config['type'] == 'smb':
		logger.debug(f"Successful video download, now managing file.")
		manage_file(final_destination_path, destination_config, overwrite, video_url=original_url, state_set=state_set)
	
	if success and not is_url_processed(original_url, state_set):
		logger.debug(f"Adding {original_url} to state")
		state_set.add(original_url)
		save_state(original_url)
	
	if driver:
		driver.quit()
	time.sleep(general_config['sleep']['between_videos'])
	return success or state_updated


def pierce_iframe(driver, url, site_config):
	"""
	Attempts to pierce into an iframe if specified in site_config.
	Returns the final URL loaded (iframe src or original URL).
	"""
	iframe_config = site_config.get('iframe', {})
	if not iframe_config.get('enabled', False):
		driver.get(url)
		return url
	
	logger.debug(f"Attempting iframe piercing for: {url}")
	driver.get(url)
	time.sleep(random.uniform(1, 2))  # Initial page load
	
	try:
		iframe_selector = iframe_config.get('selector', 'iframe')
		iframe = driver.find_element(By.CSS_SELECTOR, iframe_selector)
		iframe_url = iframe.get_attribute("src")
		if iframe_url:
			logger.info(f"Found iframe with src: {iframe_url}")
			driver.get(iframe_url)
			time.sleep(random.uniform(1, 2)) 
			return iframe_url
		else:
			logger.warning("Iframe found but no src attribute.")
			return url
	except Exception as e:
		logger.warning(f"No iframe found or error piercing: {e}")
		return url

def extract_m3u8_urls(driver, url, site_config):
	logger.debug(f"Extracting M3U8 URLs from: {url}")
	# URL is already loaded (iframe or original) by process_video_page
	driver.get(url)  # Redundant but ensures we're on the right page
	
	driver.execute_script("""
		(function() {
			let open = XMLHttpRequest.prototype.open;
			XMLHttpRequest.prototype.open = function(method, url) {
				if (url.includes(".m3u8")) {
					console.log("🔥 Found M3U8 via XHR:", url);
				}
				return open.apply(this, arguments);
			};
		})();
	""")

	time.sleep(5)
	
	logs = driver.get_log("performance")
	m3u8_urls = []
	logger.debug(f"Analyzing {len(logs)} performance logs")
	for log in logs:
		try:
			message = json.loads(log["message"])["message"]
			if "Network.responseReceived" in message["method"]:
				request_url = message["params"]["response"]["url"]
				if ".m3u8" in request_url:
					m3u8_urls.append(request_url)
					logger.debug(f"Found M3U8 URL: {request_url}")
		except KeyError:
			continue
	
	if not m3u8_urls:
		logger.warning("No M3U8 URLs detected in network traffic")
		return None, None
	
	best_m3u8 = sorted(m3u8_urls, key=lambda u: "1920x1080" in u, reverse=True)[0]
	cookies_list = driver.get_cookies()
	cookies_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies_list])
	logger.debug(f"Cookies after load: {cookies_str if cookies_str else 'None'}")
	logger.info(f"Selected best M3U8: {best_m3u8}")
	return best_m3u8, cookies_str

def extract_mp4_urls(driver, url, site_config):
	logger.debug(f"Extracting MP4 URLs from: {url}")
	driver.get(url)

	driver.execute_script("""
		(function() {
			let open = XMLHttpRequest.prototype.open;
			XMLHttpRequest.prototype.open = function(method, url) {
				if (url.includes(".mp4")) {
					console.log("🔥 Found MP4 via XHR:", url);
				}
				return open.apply(this, arguments);
			};
		})();
	""")

	time.sleep(5) # Wait for network requests

	logs = driver.get_log("performance")
	mp4_urls = []
	logger.debug(f"Analyzing {len(logs)} performance logs for MP4s")
	for log in logs:
		try:
			message = json.loads(log["message"])["message"]
			if "Network.responseReceived" in message["method"]:
				request_url = message["params"]["response"]["url"]
				if ".mp4" in request_url:
					# Basic quality check - prefer URLs with typical video resolution patterns
					if re.search(r'(240|360|480|720|1080|1440|2160)p', request_url.lower()) or \
					   re.search(r'(\d{3,4}x\d{3,4})', request_url.lower()):
						mp4_urls.append(request_url)
						logger.debug(f"Found MP4 URL (likely video): {request_url}")
					else:
						logger.debug(f"Found MP4 URL (potential non-video, logging only): {request_url}")

		except KeyError:
			continue
	
	if not mp4_urls:
		logger.warning("No MP4 URLs detected in network traffic")
		return None, None

	# Prioritize higher resolution if discernible from URL, very basic sort
	# This is a simple heuristic and might need refinement based on common URL patterns
	def quality_key(url_str):
		resolutions = {"2160p": 6, "1440p": 5, "1080p": 4, "720p": 3, "480p": 2, "360p": 1, "240p": 0}
		for res, score in resolutions.items():
			if res in url_str:
				return score
		# Try to extract resolution like 1920x1080
		match = re.search(r'(\d+)x(\d+)', url_str)
		if match:
			try:
				return int(match.group(2)) # Sort by height
			except ValueError:
				pass
		return -1 # Lowest priority if no clear resolution

	best_mp4 = sorted(mp4_urls, key=quality_key, reverse=True)[0]
	cookies_list = driver.get_cookies()
	cookies_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies_list])
	logger.debug(f"Cookies after MP4 detection: {cookies_str if cookies_str else 'None'}")
	logger.info(f"Selected best MP4: {best_mp4}")
	return best_mp4, cookies_str

def fetch_page(url, user_agents, headers, use_selenium=False, driver=None, retry_count=0):
	if not use_selenium:
		scraper = cloudscraper.create_scraper()
		if 'User-Agent' not in headers:
			headers['User-Agent'] = random.choice(user_agents)
		logger.debug(f"Fetching URL (requests): {url}")
		time.sleep(random.uniform(1, 3))
		try:
			response = scraper.get(url, headers=headers, timeout=30)
			response.raise_for_status()
			return BeautifulSoup(response.content, "html.parser")
		except requests.exceptions.RequestException as e:
			logger.error(f"Error fetching {url}: {e}")
			return None
	else:
		if driver is None:
			logger.warning("Selenium requested, but no driver provided.")
			return None
		logger.debug(f"Fetching URL (selenium): {url}")
		try:
			site_config = globals().get('site_config', {})
			if site_config.get('iframe', {}).get('enabled'):
				final_url = pierce_iframe(driver, url, site_config)
			else:
				driver.get(url)
				final_url = url
			logger.debug(f"Final URL after iframe handling: {final_url}")
			time.sleep(random.uniform(2, 4))
			return BeautifulSoup(driver.page_source, 'html.parser')
		except Exception as e:
			if retry_count < 2 and 'general_config' in globals():
				logger.warning(f"Selenium error: {e}. Retrying with new session...")
				new_driver = get_selenium_driver(globals()['general_config'], force_new=True)
				if new_driver:
					return fetch_page(url, user_agents, headers, use_selenium, new_driver, retry_count + 1)
			logger.error(f"Failed to fetch {url} with Selenium: {e}")
			return None



def extract_data(soup, selectors, driver=None, site_config=None):
	data = {}
	if soup is None:
		logger.error("Soup is None; cannot extract data")
		return data
	
	for field, config in selectors.items():
		if field == 'download_url' and site_config.get('m3u8_mode', False):
			continue
		if isinstance(config, str):
			elements = soup.select(config)
		elif isinstance(config, dict):
			if 'iframe' in config and driver and site_config:
				iframe_selector = config['iframe']
				logger.debug(f"Piercing iframe '{iframe_selector}' for field '{field}'")
				try:
					iframe = driver.find_element(By.CSS_SELECTOR, iframe_selector)
					driver.switch_to.frame(iframe)
					iframe_soup = BeautifulSoup(driver.page_source, 'html.parser')
					elements = iframe_soup.select(config.get('selector', ''))
					driver.switch_to.default_content()
				except Exception as e:
					logger.error(f"Failed to pierce iframe '{iframe_selector}' for '{field}': {e}")
					elements = []
			elif 'selector' in config:
				selector = config['selector']
				if isinstance(selector, list):
					elements = []
					for sel in selector:
						elements.extend(soup.select(sel))
						if elements:
							break
				else:
					# Handle namespace in selector (e.g., "content|encoded")
					if '|' in selector:
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
			logger.debug(f"No elements found for '{field}'")
			continue
		
		if isinstance(config, dict) and 'attribute' in config:
			# Handle attribute-based extraction (e.g., href, src)
			values = [element.get(config['attribute']) for element in elements if element.get(config['attribute'])]
			value = values[0] if len(values) == 1 else values if values else ''
			if value is None:
				logger.debug(f"Attribute '{config['attribute']}' for '{field}' is None; defaulting to empty string")
				value = ''
		else:
			# Handle text-based extraction
			value = elements[0].text.strip() if hasattr(elements[0], 'text') and elements[0].text else ''
			if value is None:
				value = ''
		
		# Handle multi-value fields with deduplication only for text-based fields
		if field in ['tags', 'actors', 'producers', 'studios'] and not (isinstance(config, dict) and 'attribute' in config):
			values = [element.text.strip() for element in elements if hasattr(element, 'text') and element.text and element.text.strip()]
			normalized_values = {v.lower() for v in values if v}
			value = [v for v in values if v.lower() in normalized_values]
			seen = set()
			value = [v for v in value if not (v.lower() in seen or seen.add(v.lower()))]
		
		# Apply post-processing if present
		if isinstance(config, dict) and 'postProcess' in config:
			for step in config['postProcess']:
				if 'replace' in step:
					for pair in step['replace']:
						regex, replacement = pair['regex'], pair['with']
						try:
							if isinstance(value, list):
								value = [re.sub(regex, replacement, v, flags=re.DOTALL) if v else '' for v in value]
							else:
								old_value = value
								value = re.sub(regex, replacement, value, flags=re.DOTALL) if value else ''
								if value != old_value:
									logger.debug(f"Applied regex '{regex}' -> '{replacement}' for '{field}': {value}")
						except re.error as e:
							logger.error(f"Regex error for '{field}': regex={regex}, error={e}")
							value = ''
				elif 'max_attribute' in step:
					if not isinstance(value, list):
						logger.debug(f"Skipping max_attribute for '{field}' as value is not a list: {value}")
						continue
					attr_name = step.get('attribute')
					attr_type = step.get('type', 'str')
					if not attr_name:
						logger.error(f"max_attribute for '{field}' missing 'attribute' key")
						continue
					try:
						attr_values = [(val, elements[i].get(attr_name)) for i, val in enumerate(value) if elements[i].get(attr_name) is not None]
						if not attr_values:
							logger.debug(f"No valid '{attr_name}' attributes found for '{field}'; using first value")
							value = value[0] if value else ''
						else:
							if attr_type == 'int':
								converted_attrs = [(val, int(attr)) for val, attr in attr_values]
							elif attr_type == 'float':
								converted_attrs = [(val, float(attr)) for val, attr in attr_values]
							else:
								converted_attrs = [(val, str(attr)) for val, attr in attr_values]
							value = max(converted_attrs, key=lambda x: x[1])[0]
							logger.debug(f"Applied max_attribute '{attr_name}' (type: {attr_type}) for '{field}': selected {value}")
					except (ValueError, TypeError) as e:
						logger.error(f"Failed to convert '{attr_name}' to {attr_type} for '{field}': {e}")
						value = value[0] if value else ''
				elif 'first' in step and step['first'] and isinstance(value, list):
					value = value[0] if value else ''
		
		# Default to first value for lists without postProcess, except multi-value fields
		if isinstance(config, dict) and 'postProcess' not in config and isinstance(value, list) and field not in ['tags', 'actors', 'studios']:
			value = value[0] if value else ''
			logger.debug(f"No postProcess for '{field}' with multiple values; defaulted to first: {value}")
		
		data[field] = value if value or isinstance(value, list) else ''
		# logger.debug(f"Final value for '{field}': {data[field]}")
	
	return data


	
def should_ignore_video(data, ignored_terms):
	if not ignored_terms:
		return False
	ignored_terms_lower = [term.lower() for term in ignored_terms]
	ignored_terms_encoded = [term.lower().replace(' ', '-') for term in ignored_terms]
	
	# Compile regex patterns with word boundaries for efficiency
	term_patterns = [re.compile(r'\b' + re.escape(term) + r'\b') for term in ignored_terms_lower]
	encoded_patterns = [re.compile(r'\b' + re.escape(encoded) + r'\b') for encoded in ignored_terms_encoded]
	
	for field, value in data.items():
		if isinstance(value, str):
			value_lower = value.lower()
			for term, term_pattern, encoded_pattern in zip(ignored_terms_lower, term_patterns, encoded_patterns):
				if term_pattern.search(value_lower) or encoded_pattern.search(value_lower):
					logger.warning(f"Ignoring video due to term '{term}' in {field}: '{value}'")
					return True
		elif isinstance(value, list):
			for item in value:
				item_lower = item.lower()
				for term, term_pattern, encoded_pattern in zip(ignored_terms_lower, term_patterns, encoded_patterns):
					if term_pattern.search(item_lower) or encoded_pattern.search(item_lower):
						logger.warning(f"Ignoring video due to term '{term}' in {field}: '{item}'")
						return True
	return False

def apply_permissions(file_path, destination_config):
	if 'permissions' not in destination_config:
		return
	permissions = destination_config['permissions']
	try:
		uid = pwd.getpwnam(permissions['owner']).pw_uid if 'owner' in permissions and permissions['owner'].isalpha() else int(permissions.get('uid', -1))
		gid = grp.getgrnam(permissions['group']).gr_gid if 'group' in permissions and permissions['group'].isalpha() else int(permissions.get('gid', -1))
		if uid != -1 or gid != -1:
			current_uid = os.stat(file_path).st_uid if uid == -1 else uid
			current_gid = os.stat(file_path).st_gid if gid == -1 else gid
			os.chown(file_path, current_uid, current_gid)
		if 'mode' in permissions:
			os.chmod(file_path, int(permissions['mode'], 8))
	except Exception as e:
		logger.error(f"Failed to apply permissions to {file_path}: {e}")



def upload_to_smb(local_path, smb_path, destination_config, overwrite=False):
	logger.debug(f"Connecting to SMB for {os.path.basename(local_path)} -> {smb_path}")
	conn = SMBConnection(destination_config['username'], destination_config['password'], "videoscraper", destination_config['server'])
	connected = False
	try:
		connected = conn.connect(destination_config['server'], 445)
		if not connected:
			logger.error(f"Failed to connect to SMB share for {smb_path}.")
			return False

		if not overwrite and file_exists_on_smb(destination_config, smb_path):
			logger.info(f"File '{os.path.basename(smb_path)}' exists on SMB share '{destination_config['share']}' at '{smb_path}'. Skipping upload.")
			return True
		
		file_size = os.path.getsize(local_path)
		with open(local_path, 'rb') as file:
			with tqdm(total=file_size, unit='B', unit_scale=True, desc=f"Uploading {os.path.basename(local_path)} to SMB") as pbar:
				progress_file = ProgressFile(file, pbar)
				conn.storeFile(destination_config['share'], smb_path, progress_file)
		logger.debug(f"Successfully stored file on SMB: {smb_path}")
		return True

	except Exception as e:
		logger.error(f"Error during SMB operation for {os.path.basename(local_path)} to {smb_path}: {e}")
		return False
	finally:
		if connected and conn.sock: # Only close if connection was successful and socket exists
			conn.close()
			logger.debug(f"SMB connection closed for {smb_path}")

def file_exists_on_smb(destination_config, path):
    # logger.debug("Connecting to SMB...")
    conn = SMBConnection(destination_config['username'], destination_config['password'], "videoscraper", destination_config['server'])
    try:
        if not conn.connect(destination_config['server'], 445):
            raise ConnectionError(f"Failed to connect to SMB server {destination_config['server']}")
            
        logger.debug(f"Successfully connected to SMB")
        try:
            conn.getAttributes(destination_config['share'], path)
            return True
        except:
            return False
    finally:
        conn.close()




def process_fallback_download(url, general_config, overwrite=False):
	# Ensure download_manager is initialized
	global download_manager
	if download_manager is None:
		download_manager = DownloadManager(general_config)
		
	destination_config = general_config['download_destinations'][0]
	temp_dir = os.path.join(tempfile.gettempdir(), f"download_{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
	os.makedirs(temp_dir, exist_ok=True)
	logger.info(f"Fallback download for: {url}")
	success, downloaded_files = download_with_ytdlp_fallback(url, temp_dir, general_config)
	
	if not success or not downloaded_files:
		logger.warning(f"yt-dlp fallback failed for {url}. Attempting direct detection fallback.")
		if _fallback_detect_and_download(url, general_config, overwrite):
			logger.info(f"Direct detection fallback succeeded for {url}")
			# If _fallback_detect_and_download created the temp_dir or used it, 
			# it should clean up its own specific temp files.
			# We only try to remove temp_dir if ytdlp might have created it and left it empty.
			if os.path.exists(temp_dir) and not os.listdir(temp_dir):
				shutil.rmtree(temp_dir, ignore_errors=True)
			return True
		else:
			logger.error(f"Both yt-dlp and direct detection fallbacks failed for {url}.")
			shutil.rmtree(temp_dir, ignore_errors=True) # Clean up ytdlp's temp_dir if both failed
			return False
	
	# This part below only runs if yt-dlp succeeded initially
	logger.info(f"yt-dlp fallback succeeded for {url}, processing {len(downloaded_files)} files.")
	for downloaded_file in downloaded_files:
		source_path = os.path.join(temp_dir, downloaded_file)
		if destination_config['type'] == 'smb':
			smb_destination_path = os.path.join(destination_config['path'], downloaded_file)
			if not overwrite and file_exists_on_smb(destination_config, smb_destination_path):
				logger.info(f"File '{downloaded_file}' exists on SMB. Skipping.")
				continue
			upload_to_smb(source_path, smb_destination_path, destination_config)
		elif destination_config['type'] == 'local':
			final_path = os.path.join(destination_config['path'], downloaded_file)
			if not overwrite and os.path.exists(final_path):
				logger.info(f"File '{downloaded_file}' exists locally. Skipping.")
				continue
			os.makedirs(os.path.dirname(final_path), exist_ok=True)
			shutil.move(source_path, final_path)
			apply_permissions(final_path, destination_config)
	shutil.rmtree(temp_dir, ignore_errors=True)
	return True

# Moved to downloaders.py - imported at top of file


def parse_url_pattern(pattern):
	components = []
	current_segment = ""
	
	i = 0
	while i < len(pattern):
		if pattern[i] == "{":
			if current_segment:
				components.append({"type": "static", "value": current_segment})
				current_segment = ""
			j = i + 1
			while j < len(pattern) and pattern[j] != "}":
				j += 1
			if j < len(pattern):
				placeholder = pattern[i+1:j]
				components.append({"type": "wildcard", "name": placeholder, "numeric": placeholder == "page"})
				i = j + 1
			else:
				raise ValueError(f"Unclosed placeholder in pattern: {pattern}")
		else:
			current_segment += pattern[i]
			i += 1
	
	if current_segment:
		components.append({"type": "static", "value": current_segment})
	
	logger.debug(f"Parsed pattern '{pattern}' into components: {components}")
	return components


def pattern_to_regex(pattern):
	regex = ""
	static_count = 0
	static_length = 0
	in_wildcard = False
	current_static = ""
	numeric_wildcards = {"page"}
	
	for char in pattern.rstrip("/"):
		if char == "{":
			if current_static:
				regex += re.escape(current_static)
				static_count += 1
				static_length += len(current_static)
				current_static = ""
			in_wildcard = True
			wildcard_name = ""
		elif char == "}":
			if in_wildcard:
				if wildcard_name in numeric_wildcards:
					regex += f"(?P<{wildcard_name}>\\d+)"
				else:
					regex += f"(?P<{wildcard_name}>[^/?&#]+)"
				in_wildcard = False
			else:
				current_static += char
		elif in_wildcard:
			wildcard_name += char
		else:
			current_static += char
	
	if current_static:
		regex += re.escape(current_static)
		static_count += 1
		static_length += len(current_static)
	
	if "?" not in pattern and "&" not in pattern:
		regex = f"^{regex}$"
	else:
		regex = f"^{regex}(?:$|&.*)"
	
	# logger.debug(f"Converted pattern '{pattern}' to regex: '{regex}', static_count={static_count}, static_length={static_length}")
	return re.compile(regex, re.IGNORECASE), static_count, static_length  # Add IGNORECASE

def match_url_to_mode(url, site_config):
	parsed_url = urlparse(url)
	netloc = parsed_url.netloc.lower().replace("www.", "", 1)
	full_path = parsed_url.path.rstrip("/").lower() + ("?" + parsed_url.query.lower() if parsed_url.query else "")
	
	base_netloc = urlparse(site_config["base_url"]).netloc.lower().replace("www.", "", 1)
	if netloc != base_netloc:
		# logger.debug(f"No match: netloc '{netloc}' != base_netloc '{base_netloc}'")
		return None, None
	
	modes = site_config.get("modes", {})
	non_video_modes = {k: v for k, v in modes.items() if k != "video"}
	video_mode = modes.get("video")
	
	best_match = None
	best_static_count = -1
	best_static_length = -1
	
	for mode, config in non_video_modes.items():
		# logger.debug(f"Checking mode: '{mode}'")
		for pattern_key in ["url_pattern", "url_pattern_pages"]:
			if pattern_key not in config:
				continue
			pattern = config[pattern_key]
			regex, static_count, static_length = pattern_to_regex(pattern)
			# logger.debug(f"Testing pattern '{pattern}' -> regex '{regex.pattern}'")
			match = regex.match(full_path)
			if match:
				extracted = match.groupdict()
				# logger.debug(f"Match found: extracted={extracted}")
				if (static_count > best_static_count) or (static_count == best_static_count and static_length > best_static_length):
					best_match = (mode, config["scraper"])
					best_static_count = static_count
					best_static_length = static_length
				# logger.debug(f"Matched URL '{url}' to mode '{mode}' with {pattern_key} (static_count={static_count}, static_length={static_length})")
			#else:
				# logger.debug(f"No match for '{pattern}'")
	
	if best_match:
		logger.debug(f"Best match selected: {best_match} (static_count={best_static_count}, static_length={best_static_length})")
		return best_match
	
	if video_mode and "url_pattern" in video_mode:
		pattern = video_mode["url_pattern"]
		regex, static_count, static_length = pattern_to_regex(pattern)
		logger.debug(f"Testing video pattern '{pattern}' -> regex '{regex.pattern}'")
		match = regex.match(full_path)
		if match:
			extracted = match.groupdict()
			logger.debug(f"Matched URL '{url}' to mode 'video' with pattern '{pattern}' (static_count={static_count}, static_length={static_length})")
			return "video", video_mode["scraper"]
		else:
			logger.debug(f"No match for video mode with pattern '{pattern}'")
	
	logger.debug(f"No mode matched for URL: '{url}'")
	return None, None	

def get_available_modes(site_config):
	"""Return a list of available scrape modes for a site config, excluding 'video'."""
	# If it's a SiteConfiguration object, use its method
	if isinstance(site_config, SiteConfiguration):
		return site_config.get_available_modes(exclude_video=True)
	
	# Backward compatibility for dict configs
	return [m for m in site_config.get("modes", {}).keys() if m != "video"]

def has_metadata_selectors(site_config, return_fields=False):
	"""
	Check if the site config has selectors for metadata fields beyond title, download_url, and image.
	If return_fields=True, return the list of fields instead of a boolean.
	"""
	# If it's a SiteConfiguration object, use its methods
	if isinstance(site_config, SiteConfiguration):
		if return_fields:
			return site_config.get_metadata_fields()
		return site_config.has_metadata_selectors()
	
	# Backward compatibility for dict configs
	video_scraper = site_config.get('scrapers', {}).get('video_scraper', {})
	excluded = {'title', 'download_url', 'image'}
	metadata_fields = [field for field in video_scraper.keys() if field not in excluded]
	
	if return_fields:
		return sorted(metadata_fields) if metadata_fields else []
	return bool(metadata_fields)


def custom_title_case(text, uppercase_list=None, preserve_mixed_case=False):
	"""Apply custom title casing with exact match overrides from uppercase_list."""
	if not text:
		return text
	uppercase_list = uppercase_list or []
	# If preserving mixed case (e.g., "McFly") and not in uppercase_list, return as-is
	if preserve_mixed_case and re.search(r'[a-z][A-Z]|[A-Z][a-z]', text) and text.lower() not in {u.lower() for u in uppercase_list}:
		return text
	
	# Build a case-insensitive mapping of overrides to their exact form
	override_map = {term.lower(): term for term in uppercase_list}
	
	# Split into words
	words = text.split()
	if not words:
		# Single word: check for override match
		text_lower = text.lower()
		return override_map.get(text_lower, text.title())
	
	# Process each word
	result = []
	for word in words:
		word_lower = word.lower()
		if word_lower in override_map:
			result.append(override_map[word_lower])  # Use exact form (e.g., "BrutalX")
		else:
			result.append(word.title() if not preserve_mixed_case or len(words) > 1 else word)
	
	final_text = ' '.join(result)
	return final_text
	
def finalize_metadata(metadata, general_config):
    """Finalize metadata: deduplicate across fields, apply capitalization rules."""
    case_overrides = general_config.get('case_overrides', [])
    tag_case_overrides = general_config.get('tag_case_overrides', [])
    tag_overrides = case_overrides + tag_case_overrides  # Combine for tags
    
    final_metadata = metadata.copy()
    
    # Normalize fields to lists and strip '#'
    actors = [actor.lstrip('#') for actor in final_metadata.get('actors', []) if actor and actor.strip() != "and"]
    studios = [studio.lstrip('#') for studio in final_metadata.get('studios', []) if studio and studio.strip() != "and"]
    tags = [tag.lstrip('#') for tag in final_metadata.get('tags', []) if tag and tag.strip() != "and"]
    
    # Deduplicate: Actors > Studios > Tags
    actors_lower = set(a.lower() for a in actors)
    studios = [s for s in studios if s.lower() not in actors_lower]
    studios_lower = set(s.lower() for s in studios)
    tags = [t for t in tags if t.lower() not in actors_lower and t.lower() not in studios_lower]
    
    # Apply capitalization
    final_metadata['actors'] = [custom_title_case(a, case_overrides, preserve_mixed_case=True) for a in actors]
    final_metadata['studios'] = [custom_title_case(s, case_overrides, preserve_mixed_case=True) for s in studios]
    final_metadata['tags'] = [custom_title_case(t, tag_overrides) for t in tags]
    if 'title' in final_metadata and final_metadata['title']:
        final_metadata['title'] = custom_title_case(final_metadata['title'].strip(), case_overrides)
    if 'studio' in final_metadata and final_metadata['studio']:
        final_metadata['studio'] = custom_title_case(final_metadata['studio'].lstrip('#'), case_overrides, preserve_mixed_case=True)
    
    # Log the final values for each field in the metadata
    for field in final_metadata:
        logger.debug(f"Final value for '{field}': {final_metadata[field]}")
    
    return final_metadata




def generate_nfo(destination_path, metadata, overwrite=False):
	"""Generate an NFO file alongside the video.

	Args:
		destination_path (str): Path to the video file.
		metadata (dict): Metadata to include in the NFO file.
		overwrite (bool): If True, overwrite existing NFO file. Defaults to False.

	Returns:
		bool: True if NFO generation succeeded, False otherwise.
	"""
	# Compute NFO file path
	nfo_path = f"{destination_path.rsplit('.', 1)[0]}.nfo"

	# Check if NFO exists and respect overwrite flag
	if os.path.exists(nfo_path) and not overwrite:
		logger.debug(f"NFO exists at {nfo_path}. Skipping generation.")
		return True

	try:
		# Write the NFO file
		with open(nfo_path, 'w', encoding='utf-8') as f:
			f.write('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n')
			f.write('<movie>\n')
			if 'title' in metadata and metadata['title']:
				f.write(f"  <title>{metadata['title']}</title>\n")
			if 'url' in metadata and metadata['url']:
				f.write(f"  <url>{metadata['url']}</url>\n")
			if 'date' in metadata and metadata['date']:
				f.write(f"  <premiered>{metadata['date']}</premiered>\n")
			if 'Code' in metadata and metadata['Code']:
				f.write(f"  <uniqueid>{metadata['Code']}</uniqueid>\n")
			if 'tags' in metadata and metadata['tags']:
				for tag in metadata['tags']:
					f.write(f"  <tag>{tag}</tag>\n")
			if 'actors' in metadata and metadata['actors']:
				for i, performer in enumerate(metadata['actors'], 1):
					f.write(f"  <actor>\n    <name>{performer}</name>\n    <order>{i}</order>\n  </actor>\n")
			if 'Image' in metadata and metadata['Image']:
				f.write(f"  <thumb aspect=\"poster\">{metadata['Image']}</thumb>\n")
			if 'studios' in metadata and metadata['studios']:
				for studio in metadata['studios']:
					f.write(f"  <studio>{studio}</studio>\n")
			elif 'studio' in metadata and metadata['studio']:
				f.write(f"  <studio>{metadata['studio']}</studio>\n")
			if 'description' in metadata and metadata['description']:
				f.write(f"  <plot>{metadata['description']}</plot>\n")
			f.write('</movie>\n')

		# Log success
		logger.success(f"{'Replaced' if os.path.exists(nfo_path) else 'Generated'} NFO at {nfo_path}")
		return True

	except Exception as e:
		logger.error(f"Failed to generate NFO at {nfo_path}: {e}", exc_info=True)
		return False


def download_video(video_url, destination_path, site_config, general_config, headers=None, metadata=None, overwrite=False):
	"""Download a video file to a temporary or final path."""
	download_method = site_config.get('download', {}).get('method', 'curl')
	origin = urllib.parse.urlparse(video_url).scheme + "://" + urllib.parse.urlparse(video_url).netloc
	
	if os.path.exists(destination_path) and not overwrite:
		video_info = download_manager.get_video_metadata(destination_path)
		if video_info:
			logger.info(f"Valid video exists at {destination_path}. Skipping download.")
			return True
		else:
			logger.warning(f"Invalid video file at {destination_path}. Redownloading.")
			os.remove(destination_path)
	
	logger.info(f"Downloading to {destination_path}")
	success = download_manager.download_file(
		video_url, destination_path, download_method, site_config,
		headers=headers, metadata=metadata, origin=origin, overwrite=overwrite
	)
	if success:
		logger.success(f"Downloaded video to {destination_path}")
	else:
		logger.error(f"Failed to download video to {destination_path}")
	return success


def manage_file(destination_path, destination_config, overwrite=False, video_url=None, state_set=None):
	"""Move or upload the video (and NFO) to the final destination."""
	smb_upload_successful = False
	
	if destination_config['type'] == 'smb':
		smb_path = os.path.join(destination_config['path'], os.path.basename(destination_path))
		smb_nfo_path = os.path.join(destination_config['path'], f"{os.path.basename(destination_path).rsplit('.', 1)[0]}.nfo")
		
		# Attempt to upload the main video file
		smb_upload_successful = upload_to_smb(destination_path, smb_path, destination_config, overwrite)
		
		if smb_upload_successful:
			logger.success(f"Successfully processed video for SMB: {smb_path}")
			os.remove(destination_path) # Remove video file only if upload was successful
			logger.debug(f"Removed temporary video file: {destination_path}")
			
			# Handle NFO file upload if video upload was successful
			temp_nfo_path = f"{destination_path.rsplit('.', 1)[0]}.nfo"
			if os.path.exists(temp_nfo_path):
				nfo_upload_successful = upload_to_smb(temp_nfo_path, smb_nfo_path, destination_config, overwrite)
				if nfo_upload_successful:
					os.remove(temp_nfo_path) # Remove NFO file only if its upload was successful
					logger.debug(f"Removed temporary NFO file: {temp_nfo_path}")
				else:
					logger.error(f"Failed to upload NFO file {os.path.basename(temp_nfo_path)} to SMB. It remains at {temp_nfo_path}")
			else:
				logger.debug(f"No NFO file found at {temp_nfo_path} to upload.")
		else:
			logger.error(f"Failed to upload video {os.path.basename(destination_path)} to SMB. It remains at {destination_path}")
			# Also check if an NFO exists and warn that it wasn't uploaded due to video failure
			temp_nfo_path_on_failure = f"{destination_path.rsplit('.', 1)[0]}.nfo"
			if os.path.exists(temp_nfo_path_on_failure):
				logger.warning(f"NFO file {os.path.basename(temp_nfo_path_on_failure)} was not uploaded due to video upload failure. It remains at {temp_nfo_path_on_failure}")
		return smb_upload_successful # Return the success status of the main video file processing
	else: # Local destination type
		final_path = os.path.join(destination_config['path'], os.path.basename(destination_path))
		os.makedirs(os.path.dirname(final_path), exist_ok=True)
		if not overwrite and os.path.exists(final_path):
			logger.info(f"File exists locally at {final_path}. Skipping move.")
			# If original destination_path was temporary and different, it might need removal
			if destination_path != final_path and os.path.exists(destination_path):
				os.remove(destination_path)
				logger.debug(f"Removed original file at {destination_path} as final already exists.")
			return True
		else:
			try:
				shutil.move(destination_path, final_path)
				apply_permissions(final_path, destination_config)
				logger.success(f"Moved to local destination: {final_path}")
				# Handle NFO for local move
				temp_nfo_path = f"{destination_path.rsplit('.', 1)[0]}.nfo"
				final_nfo_path = f"{final_path.rsplit('.', 1)[0]}.nfo"
				if os.path.exists(temp_nfo_path):
					if not overwrite and os.path.exists(final_nfo_path):
						logger.info(f"NFO file exists locally at {final_nfo_path}. Skipping move.")
						if temp_nfo_path != final_nfo_path and os.path.exists(temp_nfo_path):
							os.remove(temp_nfo_path)
					else:
						shutil.move(temp_nfo_path, final_nfo_path)
						apply_permissions(final_nfo_path, destination_config)
						logger.debug(f"Moved NFO to {final_nfo_path}")
				return True
			except Exception as e:
				logger.error(f"Failed to move {destination_path} to {final_path}: {e}")
				return False
	return False # Should not be reached in local path scenario if logic is correct


def cleanup(general_config):
	"""Clean up resources like Selenium driver."""
	if 'selenium_driver' in general_config and general_config['selenium_driver']:
		try:
			general_config['selenium_driver'].quit()
			logger.info("Selenium driver closed.")
		except Exception as e:
			logger.warning(f"Failed to close Selenium driver: {e}")
	print()


def _fallback_detect_and_download(url, general_config, overwrite=False):
	"""Helper function for fallback: tries to detect MP4 then M3U8 and download."""
	# Ensure download_manager is initialized
	global download_manager
	if download_manager is None:
		download_manager = DownloadManager(general_config)
	
	logger.info(f"Fallback: Attempting direct detection for {url}")
	driver = None
	video_url_detected = None
	download_method = None
	detection_headers = general_config.get("headers", {}).copy()
	detection_headers["User-Agent"] = random.choice(general_config["user_agents"])

	if SELENIUM_AVAILABLE:
		driver = get_selenium_driver(general_config) # Ensure driver is fetched/reused via general_config
		if not driver:
			logger.error("Fallback: Failed to initialize Selenium driver for detection.")
			return False
		
		current_url_for_scan = url
		# Simplified iframe check for fallback
		try:
			driver.get(url) # Load the initial URL first
			time.sleep(random.uniform(2,4)) # Allow page to load and scripts to potentially run
			iframes = driver.find_elements(By.TAG_NAME, "iframe")
			if iframes:
				# Try to find a visible, reasonably sized iframe, or just the first one with a src
				best_iframe_src = None
				for iframe_element in iframes:
					iframe_src_attr = iframe_element.get_attribute("src")
					if iframe_src_attr and is_url(iframe_src_attr):
						# Basic check, could be improved with size/visibility checks
						best_iframe_src = iframe_src_attr
						logger.debug(f"Fallback: Potential iframe found with src: {best_iframe_src}")
						break # Take the first valid one for simplicity in fallback
				if best_iframe_src:
					logger.info(f"Fallback: Scanning inside iframe: {best_iframe_src}")
					current_url_for_scan = best_iframe_src
					# driver.get(current_url_for_scan) # extract_mp4/m3u8_urls will navigate
			else:
				logger.debug(f"Fallback: No iframes found on {url} or no suitable src attributes.")
		except Exception as e:
			logger.warning(f"Fallback: Error during simplified iframe check for {url}: {e}")

		# Try MP4 detection
		logger.debug(f"Fallback: Attempting MP4 detection on {current_url_for_scan}")
		mp4_found_url, mp4_cookies = extract_mp4_urls(driver, current_url_for_scan, {}) # Pass empty site_config
		if mp4_found_url:
			video_url_detected = mp4_found_url
			download_method = 'requests'
			detection_headers.update({"Cookie": mp4_cookies, "Referer": current_url_for_scan,
								 "User-Agent": general_config.get('selenium_user_agent', detection_headers["User-Agent"])})
			logger.info(f"Fallback: Detected MP4: {video_url_detected}")
		else:
			logger.info(f"Fallback: MP4 not found via direct detection for {current_url_for_scan}, trying M3U8.")
			# Try M3U8 detection
			m3u8_found_url, m3u8_cookies = extract_m3u8_urls(driver, current_url_for_scan, {}) # Pass empty site_config
			if m3u8_found_url:
				video_url_detected = m3u8_found_url
				download_method = 'ffmpeg'
				detection_headers.update({"Cookie": m3u8_cookies, "Referer": current_url_for_scan,
									 "User-Agent": general_config.get('selenium_user_agent', detection_headers["User-Agent"])})
				logger.info(f"Fallback: Detected M3U8: {video_url_detected}")
			else:
				logger.warning(f"Fallback: Direct detection failed for MP4 and M3U8 on {current_url_for_scan}.")
				# Selenium driver is managed globally, no quit here for fallback.
				return False
	else:
		logger.warning("Fallback: Selenium not available, cannot perform direct MP4/M3U8 detection.")
		return False

	if not video_url_detected or not download_method:
		logger.debug("Fallback: video_url_detected or download_method is missing after detection attempts.")
		return False

	title_from_url_path = url.split('/')[-1].split('?')[0] if '/' in url else url
	title = re.sub(r'[^a-zA-Z0-9_.-]', '_', title_from_url_path) or "fallback_video"
	invalid_chars = general_config['file_naming']['invalid_chars']
	processed_title = process_title(title, invalid_chars)
	extension = ".mp4" # Default to .mp4; ffmpeg handles m3u8 to mp4
	
	filename = construct_filename(processed_title, {}, general_config) # Use empty site_config for basic construction

	destination_config = general_config['download_destinations'][0]
	temp_storage_path = destination_config.get('temporary_storage', os.path.join(tempfile.gettempdir(), 'smutscrape'))
	os.makedirs(temp_storage_path, exist_ok=True)
	# Use a unique name for the temporary download to avoid collision
	temp_filename_for_download = str(uuid.uuid4().hex[:8]) + "_" + filename
	local_temp_path = os.path.join(temp_storage_path, temp_filename_for_download)

	logger.info(f"Fallback: Downloading detected video {video_url_detected} as {temp_filename_for_download} using {download_method}")
	# Pass an empty site_config as it's not strictly needed for download_video when method/URL are explicit
	success = download_video(video_url_detected, local_temp_path, {"download": {"method": download_method}}, general_config, headers=detection_headers, overwrite=overwrite)

	if success:
		final_filename_at_destination = filename # This is the desired final name, not the temp one.
		if destination_config['type'] == 'smb':
			smb_final_path = os.path.join(destination_config['path'], final_filename_at_destination)
			if not overwrite and file_exists_on_smb(destination_config, smb_final_path):
				logger.info(f"Fallback: File '{final_filename_at_destination}' exists on SMB. Skipping upload.")
				os.remove(local_temp_path) # Clean up temp file
				return True
			upload_to_smb(local_temp_path, smb_final_path, destination_config, overwrite)
			os.remove(local_temp_path)
			logger.success(f"Fallback: Uploaded detected video to SMB: {smb_final_path}")
			return True
		elif destination_config['type'] == 'local':
			local_final_storage_path = os.path.join(destination_config['path'], final_filename_at_destination)
			if not overwrite and os.path.exists(local_final_storage_path):
				logger.info(f"Fallback: File '{final_filename_at_destination}' exists locally. Skipping move.")
				os.remove(local_temp_path) # Clean up temp file
				return True
			os.makedirs(os.path.dirname(local_final_storage_path), exist_ok=True)
			shutil.move(local_temp_path, local_final_storage_path)
			apply_permissions(local_final_storage_path, destination_config)
			logger.success(f"Fallback: Moved detected video to local destination: {local_final_storage_path}")
			return True
	else:
		logger.error(f"Fallback: Download of detected video failed for {video_url_detected}")
		if os.path.exists(local_temp_path):
			os.remove(local_temp_path)
	return False



def generate_global_table(term_width, output_path=None):
	"""Generate the global sites table, optionally saving as Markdown to output_path."""
	table = Table(show_edge=True, expand=True, width=term_width)
	table.add_column("[bold][magenta]code[/magenta][/bold]", width=6, justify="left")
	table.add_column("[bold][magenta]site[/magenta][/bold]", width=12, justify="left")
	table.add_column("[bold][yellow]modes[/yellow][/bold]", width=(term_width-8)//3)
	table.add_column("[bold][green]metadata[/green][/bold]", width=(term_width-8)//3)
	
	supported_sites = []
	selenium_sites = set()
	encoding_rule_sites = set()
	pagination_modes = set()
	
	for site_config_file in os.listdir(SITE_DIR):
		if site_config_file.endswith(".yaml"):
			try:
				with open(os.path.join(SITE_DIR, site_config_file), 'r') as f:
					site_config = yaml.safe_load(f)
				site_name = site_config.get("name", "Unknown")
				site_code = site_config.get("shortcode", "??")
				use_selenium = site_config.get("use_selenium", False)
				
				if use_selenium:
					selenium_sites.add(site_code)
				
				modes = site_config.get("modes", {})
				modes_display_list = []
				for mode, config in modes.items():
					supports_pagination = "url_pattern_pages" in config
					mode_url_rules = config.get("url_encoding_rules", {})
					has_special_encoding = " & " in mode_url_rules or "&" in mode_url_rules
					footnotes = []
					if supports_pagination:
						footnotes.append("*")
						pagination_modes.add(mode)
					if has_special_encoding:
						footnotes.append("‡")
						if site_code not in encoding_rule_sites:
							encoding_rule_sites.add(site_code)
					mode_display = f"[yellow][bold]{mode}[/bold][/yellow]" + (f" {''.join(footnotes)}" if footnotes else "")
					modes_display_list.append(mode_display)
				
				metadata = has_metadata_selectors(site_config, return_fields=True)
				supported_sites.append((site_code, site_name, modes_display_list, metadata, use_selenium))
			except Exception as e:
				logger.warning(f"Failed to load config '{site_config_file}': {e}")
	
	if supported_sites:
		for site_code, site_name, modes_display_list, metadata, use_selenium in sorted(supported_sites, key=lambda x: x[0]):
			code_display = f"[magenta][bold]{site_code}[/bold][/magenta]"
			site_display = f"[magenta]{site_name}[/magenta]" + (f" †" if use_selenium else "")
			modes_display = " · ".join(modes_display_list) if modes_display_list else "[gray]None[/gray]"
			metadata_display = " · ".join(f"[green][bold]{field}[/bold][/green]" for field in metadata) if metadata else "None"
			table.add_row(code_display, site_display, modes_display, metadata_display)
	else:
		logger.warning("No valid site configs found in 'configs' folder.")
		table.add_row("[magenta][bold]??[/bold][/magenta]", "[magenta]No sites loaded[/magenta]", "[gray]None[/gray]", "None")
	
	# Prepare footnotes
	footnotes = []
	if pagination_modes:
		footnotes.append("[italic]* supports [bold][green]pagination[/green][/bold]; see [bold][yellow]optional arguments[/yellow][/bold] below.[/italic]")
	if selenium_sites:
		footnotes.append("[italic]† [yellow][bold]selenium[/bold][/yellow] and [yellow][bold]chromedriver[/bold][/yellow] required.[/italic]")
	if encoding_rule_sites:
		footnotes.append("[italic]‡ combine terms with \'&\' to search them together.[/italic]")

	if output_path:
		md_lines = [
			"| code   | site                          | modes                          | metadata                       |\n",
			"| ------ | ----------------------------- | ------------------------------ | ------------------------------ |\n"
		]
		
		for site_code, site_name, modes_display_list, metadata, use_selenium in sorted(supported_sites, key=lambda x: x[0]):
			code_str = f"`{site_code}`"
			site_str = f"**_{site_name}_**" + (f" †" if use_selenium else "")
			# Strip Rich formatting and keep only mode name + footnotes
			modes_str = " · ".join(
				mode.replace("[yellow][bold]", "").replace("[/bold][/yellow]", "") 
				for mode in modes_display_list
			) if modes_display_list else "None"
			metadata_str = " · ".join(metadata) if metadata else "None"
			md_lines.append(f"| {code_str:<6} | {site_str:<29} | {modes_str:<30} | {metadata_str:<30} |\n")
		
		if pagination_modes:
			md_lines.append("\n* _Supports pagination; see optional arguments below._\n")
		if selenium_sites:
			md_lines.append("\n† _Selenium required._\n")
		if encoding_rule_sites:
			md_lines.append("\n‡ _Combine terms with \"&\"._\n")
		
		
		try:
			with open(output_path, 'w', encoding='utf-8') as f:
				f.writelines(md_lines)
			logger.info(f"Saved site table to '{output_path}' in Markdown format.")
		except Exception as e:
			logger.error(f"Failed to write Markdown table to '{output_path}': {e}")
		return None
	
	from rich.console import Group
	return Group(table, *footnotes) if footnotes else table



	

def handle_single_arg(arg, general_config, args, term_width, state_set):
	# Ensure download_manager is initialized
	global download_manager
	if download_manager is None:
		download_manager = DownloadManager(general_config)
	
	is_url_flag = is_url(arg)
	config = load_configuration('site', arg)
	if config:
		# Configuration loaded successfully
		if is_url_flag:
			if config.get('use_selenium', False) and not SELENIUM_AVAILABLE:
				console.print(f"[yellow]Sorry, but this site requires Selenium, which is not available on your system.[/yellow]")
				console.print(f"Please install the necessary Selenium libraries to use this site.")
				sys.exit(1)
			else:
				console.print("═" * term_width, style=Style(color="yellow"))
				console.print()
				render_ascii(config.get("domain", "unknown"), general_config, term_width)
				console.print()
				process_url(arg, config, general_config, args.overwrite, args.re_nfo, args.page, apply_state=args.applystate, state_set=state_set)
		else:
			# Get the SiteConfiguration object instead of dict
			site_obj = get_site_manager().get_site_by_identifier(arg)
			if site_obj:
				site_obj.display_details(term_width, general_config)
				display_options()
			sys.exit(0)
	else:
		if is_url_flag:
			logger.warning(f"No site config matched for URL '{arg}'. Falling back to yt-dlp.")
			process_fallback_download(arg, general_config, args.overwrite)
		else:
			logger.error(f"Could not match the provided argument '{arg}' to a site configuration.")
			sys.exit(1)
			
def handle_multi_arg(args, general_config, args_obj, state_set):
	# Ensure download_manager is initialized
	global download_manager
	if download_manager is None:
		download_manager = DownloadManager(general_config)
	
	site_config = load_configuration('site', args[0])
	if not site_config:
		logger.error(f"Site '{args[0]}' not found in configs")
		sys.exit(1)

	# Check if the third argument is a URL that matches the site's domain
	if len(args) >= 3 and is_url(args[2]):
		potential_url_arg = args[2]
		site_base_url_str = site_config.get("base_url", "")
		
		if not site_base_url_str:
			logger.warning(f"Site '{args[0]}' has no base_url defined. Cannot validate if URL argument '{potential_url_arg}' belongs to this site. Proceeding to treat '{args[1]}' as mode and remaining args as query.")
		else:
			site_base_url_parsed = urlparse(site_base_url_str)
			potential_url_arg_parsed = urlparse(potential_url_arg)

			site_domain = site_base_url_parsed.netloc.lower().replace('www.', '')
			arg_domain = potential_url_arg_parsed.netloc.lower().replace('www.', '')

			if site_domain and arg_domain and site_domain == arg_domain:
				logger.info(f"Third argument '{potential_url_arg}' is a URL matching site '{args[0]}' domain ('{site_domain}'). Processing as a direct URL via handle_single_arg.")
				term_width = get_terminal_width() # For display in handle_single_arg
				handle_single_arg(potential_url_arg, general_config, args_obj, term_width, state_set)
				return # Crucial: exit handle_multi_arg as task is delegated
			else:
				domains_match_info = f"URL domain: '{arg_domain or 'unknown'}', Site domain: '{site_domain or 'unknown'}'"
				logger.warning(f"Third argument '{potential_url_arg}' is a URL, but its domain does not match site '{args[0]}'. ({domains_match_info}). It will be treated as a query string for mode '{args[1]}'.")

	# If the redirect to handle_single_arg didn't happen, proceed with normal multi-argument logic.
	mode = args[1]
	identifier = " ".join(args[2:]) if len(args) > 2 else ""

	if mode not in site_config.get('modes', {}):
		logger.error(f"Unsupported mode '{mode}' for site '{args[0]}'")
		available_modes = get_available_modes(site_config)
		if available_modes:
			logger.info(f"Available modes for site '{args[0]}': {', '.join(available_modes)}")
		else:
			logger.info(f"No specific modes (like 'channel', 'search', etc.) defined for site '{args[0]}'. Try providing a direct video URL.")
		sys.exit(1)
	
	if site_config.get('use_selenium', False) and not SELENIUM_AVAILABLE:
		term_width = get_terminal_width()
		console.print("═" * term_width, style=Style(color="yellow"))
		console.print()
		banner_text_selenium_fail = site_config.get("domain") or site_config.get("name", args[0])
		render_ascii(banner_text_selenium_fail, general_config, term_width)
		console.print()
		console.print(f"[yellow]Sorry, but site '{site_config.get('name', args[0])}' requires Selenium, which is not available on your system.[/yellow]")
		console.print(f"Please install the necessary Selenium libraries to use this site.")
		sys.exit(1)
	
	term_width = get_terminal_width()
	console.print("═" * term_width, style=Style(color="yellow"))
	console.print()
	banner_text = site_config.get("domain") or site_config.get("name", args[0])
	render_ascii(banner_text, general_config, term_width)
	console.print()
	
	mode_config = site_config['modes'][mode]
	page_num = args_obj.page_num
	video_offset = args_obj.video_offset
	
	constructed_url = None
	if mode == 'rss':
		if 'url_pattern' in mode_config:
			constructed_url = construct_url(
				site_config["base_url"],
				mode_config["url_pattern"],
				site_config,
				mode=mode
			)
		else:
			logger.error(f"RSS mode for site '{args[0]}' is missing 'url_pattern' in its configuration.")
			sys.exit(1)
	elif mode == 'video':
		if 'url_pattern' in mode_config:
			# For 'video' mode, the identifier is usually a video ID or key
			video_key_name = mode # Often the mode name itself is the placeholder, e.g., {video}
			# Check if a specific placeholder is defined, e.g. "video_id_placeholder": "id"
			video_id_placeholder = mode_config.get("video_id_placeholder", video_key_name)

			constructed_url = construct_url(
				site_config["base_url"],
				mode_config["url_pattern"],
				site_config,
				mode=mode,
				**{video_id_placeholder: identifier}
			)
		else:
			logger.error(f"Video mode for site '{args[0]}' is missing 'url_pattern'. Cannot construct video URL from identifier '{identifier}'.")
			sys.exit(1)
	else: # For other list modes (channel, search, etc.)
		current_url_pattern_key = "url_pattern"
		if page_num > 1 and mode_config.get("url_pattern_pages"):
			current_url_pattern_key = "url_pattern_pages"
		elif not mode_config.get("url_pattern"):
			logger.error(f"Mode '{mode}' for site '{args[0]}' is missing 'url_pattern' in its configuration.")
			sys.exit(1)

		url_pattern_to_use = mode_config[current_url_pattern_key]
		
		kwargs_for_url = {mode: identifier}
		# Only include 'page' if it's part of the pattern or if page_num > 1 and using paged pattern
		if "{page}" in url_pattern_to_use or (page_num > 1 and current_url_pattern_key == "url_pattern_pages"):
			kwargs_for_url["page"] = page_num
		elif page_num == 1 and "{page}" not in url_pattern_to_use and current_url_pattern_key == "url_pattern":
			# If page is 1, and not in the main pattern, don't pass 'page' kwarg unless explicitly needed.
			# construct_url handles None gracefully if {page} isn't in pattern.
			kwargs_for_url["page"] = None


		constructed_url = construct_url(
			site_config["base_url"],
			url_pattern_to_use,
			site_config,
			mode=mode,
			**kwargs_for_url
		)
	
	if not constructed_url:
		logger.error(f"Failed to construct URL for site '{args[0]}', mode '{mode}', identifier/query '{identifier}'.")
		sys.exit(1)
	
	logger.info(f"Constructed starting URL: {constructed_url}")
	handle_vpn(general_config, 'start')

	if mode == 'video':
		process_video_page(
			constructed_url, site_config, general_config, args_obj.overwrite, 
			general_config.get('headers', {}), args_obj.re_nfo, 
			apply_state=args_obj.applystate, state_set=state_set
		)
	elif mode == 'rss':
		process_rss_feed(
			constructed_url, site_config, general_config, args_obj.overwrite, 
			general_config.get('headers', {}), args_obj.re_nfo, 
			apply_state=args_obj.applystate, state_set=state_set
		)
	else: # List page modes
		current_url_to_process = constructed_url
		current_page_num_for_list = page_num
		current_video_offset_for_list = video_offset if current_page_num_for_list == page_num else 0
		
		while current_url_to_process:
			next_page_url, next_page_number, page_processed_successfully = process_list_page(
				current_url_to_process, site_config, general_config, 
				current_page_num_for_list, 
				current_video_offset_for_list,
				mode, identifier,
				args_obj.overwrite, 
				general_config.get('headers', {}), 
				args_obj.re_nfo, 
				apply_state=args_obj.applystate, 
				state_set=state_set
			)
			current_video_offset_for_list = 0 
			current_url_to_process = next_page_url
			if next_page_number is not None:
				current_page_num_for_list = next_page_number
			else:
				current_url_to_process = None

			if current_url_to_process:
				time.sleep(general_config['sleep']['between_pages'])





def main():
	parser = argparse.ArgumentParser(
		description="Smutscrape: Scrape and download adult content with metadata in .nfo files."
	)
	parser.add_argument("args", nargs="*", help="Site shortcode/mode/query or URL.")
	parser.add_argument("-d", "--debug", action="store_true", help="Enable detailed debug logging.")
	parser.add_argument("-o", "--overwrite", action="store_true", help="Overwrite existing video files.")
	parser.add_argument("-n", "--re_nfo", action="store_true", help="Regenerate .nfo files even if they exist.")
	parser.add_argument("-p", "--page", type=str, default="1", help="Start scraping from this page.number (e.g., 12.9 for page 12, video 9).")
	parser.add_argument("-a", "--applystate", action="store_true", help="Add URLs to .state if file exists at destination without overwriting.")
	parser.add_argument("-t", "--table", type=str, help="Output site table in Markdown and exit.")
	parser.add_argument("-s", "--server", action="store_true", help="Run as FastAPI server instead of CLI mode.")
	parser.add_argument("--host", type=str, default=None, help="Host to bind the API server to (overrides config)")
	parser.add_argument("--port", type=int, default=None, help="Port to bind the API server to (overrides config)")
	args = parser.parse_args()
	
	# Check if running in server mode
	if args.server:
		if not FASTAPI_AVAILABLE:
			logger.error("FastAPI is not installed. Please install it with: pip install fastapi uvicorn")
			sys.exit(1)
		
		# Setup basic logging for server mode
		log_level = "DEBUG" if args.debug else "INFO"
		logger.remove()
		logger.add(
			sys.stderr,
			level=log_level,
			format="<d>{time:YYYY-MM-DD HH:mm:ss}</d> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
			colorize=True
		)
		
		# Load general config to get server settings
		general_config = load_configuration('general')
		if not general_config:
			logger.error("Failed to load general configuration. Please check 'config.yaml'.")
			sys.exit(1)
		
		# Determine host and port with priority: CLI args > config.yaml > defaults
		default_host = "127.0.0.1"
		default_port = 6999
		
		# Get values from config if present
		api_server_config = general_config.get('api_server', {})
		config_host = api_server_config.get('host', default_host)
		config_port = api_server_config.get('port', default_port)
		
		# Apply priority: CLI args override config, config overrides defaults
		final_host = args.host if args.host is not None else config_host
		final_port = args.port if args.port is not None else config_port
		
		logger.info(f"Starting Smutscrape in API server mode on {final_host}:{final_port}")
		run_api_server(host=final_host, port=final_port)
		return
	
	# Normal CLI mode continues below
	term_width = get_terminal_width()
	
	# Logging setup
	log_level = "DEBUG" if args.debug else "INFO"
	logger.remove()
	if args.debug:
		logger.add(
			sys.stderr,
			level="DEBUG",
			format="<d>{time:YYYYMMDDHHmmss.SSS}</d> | <d>{level:1.1}</d> | <d>{function}:{line}</d> · <d>{message}</d>",
			colorize=True,
			filter=lambda record: record["level"].name == "DEBUG"
		)
	logger.add(
		sys.stderr,
		level="INFO",
		format="<d>{time:YYYYMMDDHHmmss.SSS}</d> | <level>{level:1.1}</level> | <d>{function}:{line}</d> · <level>{message}</level>",
		colorize=True,
		filter=lambda record: record["level"].name != "DEBUG"
	)
	
	general_config = load_configuration('general')
	if not general_config:
		logger.error("Failed to load general configuration. Please check 'config/general.yml'.")
		sys.exit(1)
	
	# Initialize download manager with general config
	global download_manager
	download_manager = DownloadManager(general_config)
	
	# Load state once at startup
	state_set = load_state()
	logger.debug(f"Loaded {len(state_set)} URLs from state file")
	
	print()
	render_ascii("Smutscrape", general_config, term_width)
	
	if args.table:
		generate_global_table(term_width, output_path=args.table)
		logger.info(f"Generated site table at '{args.table}'")
		sys.exit(0)
	
	if not args.args:
		print()
		global_table = generate_global_table(term_width)
		display_usage(term_width, global_table)
		display_global_examples(SITE_DIR)
		display_options()
		sys.exit(0)
	
	# Split --page into page_num and video_offset
	page_parts = args.page.split('.')
	args.page_num = int(page_parts[0])
	args.video_offset = int(page_parts[1]) if len(page_parts) > 1 else 0
	
	try:
		if len(args.args) == 1:
			handle_single_arg(args.args[0], general_config, args, term_width, state_set)
		elif len(args.args) >= 2:
			handle_multi_arg(args.args, general_config, args, state_set)
		else:
			logger.error("Invalid arguments. Use: scrape {site} {mode} {query} or scrape {url}")
			global_table = generate_global_table(term_width)
			display_usage(term_width, global_table)
			display_global_examples(SITE_DIR)
			display_options()
			sys.exit(1)
	except KeyboardInterrupt:
		logger.warning("Interrupted by user. Cleaning up...")
		cleanup(general_config)
		sys.exit(130)
	except Exception as e:
		logger.error(f"Unexpected error occurred: {e}", exc_info=args.debug)
		cleanup(general_config)
		sys.exit(1)
	finally:
		handle_vpn(general_config, 'stop')
		cleanup(general_config)
		logger.info("Scraping session completed.")

if __name__ == "__main__":
	main()
