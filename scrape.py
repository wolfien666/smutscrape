#!/usr/bin/env python3

import argparse
import yaml
import requests
import cloudscraper
from bs4 import BeautifulSoup
import os
import tempfile
import subprocess
import time
import re
import sys
import urllib.parse
from urllib.parse import urlparse
from smb.SMBConnection import SMBConnection
import random
from loguru import logger
from tqdm import tqdm
from termcolor import colored
import io
import shlex
import json
import pwd
import grp
import shutil
import shlex
import json
import uuid
from datetime import datetime
from selenium import webdriver
from rich.console import Console
from rich.table import Table
from rich.style import Style
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG_DIR = os.path.join(SCRIPT_DIR, 'sites')

last_vpn_action_time = 0
session = requests.Session()
console = Console()
		
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
		

def load_config(config_file):
	with open(config_file, 'r') as file:
		return yaml.safe_load(file)

def load_site_config(site):
	config_path = os.path.join(CONFIG_DIR, f'{site}.yaml')
	return load_config(config_path)

def process_title(title, invalid_chars):
	logger.debug(f"Processing {title} for invalid chars...")
	for char in invalid_chars:
		title = title.replace(char, "")
	return title

def construct_filename(title, site_config, general_config):
	prefix = site_config.get('name_prefix', '')
	suffix = site_config.get('name_suffix', '')
	extension = general_config['file_naming']['extension']
	invalid_chars = general_config['file_naming']['invalid_chars']
	max_chars = general_config['file_naming'].get('max_chars', 255)  # Default to 255 if not specified
	
	# Process title by removing invalid characters
	processed_title = process_title(title, invalid_chars)
	
	# Calculate available length for the title
	fixed_length = len(prefix) + len(suffix) + len(extension)
	max_title_chars = min(max_chars, 255) - fixed_length  # Hard cap at 255 chars total
	
	if max_title_chars <= 0:
		logger.warning(f"Fixed filename parts ({fixed_length} chars) exceed max_chars ({max_chars}); truncating to fit.")
		max_title_chars = max(1, 255 - fixed_length)  # Ensure at least 1 char for title if possible
	
	# Truncate title if necessary
	if len(processed_title) > max_title_chars:
		processed_title = processed_title[:max_title_chars].rstrip()
		logger.debug(f"Truncated title to {max_title_chars} chars: {processed_title}")
	
	# Construct final filename
	filename = f"{prefix}{processed_title}{suffix}{extension}"
	
	# Double-check byte length (Linux limit is 255 bytes, not chars)
	while len(filename.encode('utf-8')) > 255:
		excess = len(filename.encode('utf-8')) - 255
		trim_chars = excess // 4 + 1  # Rough estimate for UTF-8; adjust conservatively
		processed_title = processed_title[:-trim_chars].rstrip()
		filename = f"{prefix}{processed_title}{suffix}{extension}"
		logger.debug(f"Filename exceeded 255 bytes; trimmed to: {filename}")
	
	return filename

		
def construct_url(base_url, pattern, site_config, mode=None, **kwargs):
	encoding_rules = (
		site_config['modes'][mode]['url_encoding_rules']
		if mode and mode in site_config['modes'] and 'url_encoding_rules' in site_config['modes'][mode]
		else site_config.get('url_encoding_rules', {})
	)
	encoded_kwargs = {}
	logger.debug(f"Constructing URL with pattern '{pattern}' and mode '{mode}' using encoding rules: {encoding_rules}")
	for k, v in kwargs.items():
		if isinstance(v, str):
			encoded_v = v
			for original, replacement in encoding_rules.items():
				encoded_v = encoded_v.replace(original, replacement)
			encoded_kwargs[k] = encoded_v
		else:
			encoded_kwargs[k] = v
	path = pattern.format(**encoded_kwargs)
	full_url = urllib.parse.urljoin(base_url, path)
	logger.debug(f"Constructed URL: {full_url}")
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


def process_video_page(url, site_config, general_config, overwrite=False, headers=None, new_nfo=False, do_not_ignore=False):
	"""Process a video page: fetch, extract, finalize metadata, and handle NFO/download."""
	global last_vpn_action_time
	vpn_config = general_config.get('vpn', {})
	if vpn_config.get('enabled', False):
		current_time = time.time()
		if current_time - last_vpn_action_time > vpn_config.get('new_node_time', 300):
			handle_vpn(general_config, 'new_node')
	
	logger.info(f"Processing video page: {url}")
	use_selenium = site_config.get('use_selenium', False)
	driver = get_selenium_driver(general_config) if use_selenium else None
	original_url = url
	
	# Fetch and extract raw metadata
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
	logger.debug(f"Video URL: {video_url}")
	video_title = raw_data.get('title', '').strip() or 'Untitled'
	raw_data['Title'] = video_title
	raw_data['URL'] = original_url
	
	if do_not_ignore==False and should_ignore_video(raw_data, general_config['ignored']):
		if driver:
			driver.quit()
		return True
	
	# Finalize metadata and handle NFO/download
	final_metadata = finalize_metadata(raw_data, general_config)  # Pass general_config
	logger.info(f"Final metadata for '{video_title}': {final_metadata}")
	success = handle_nfo_and_download(video_url, final_metadata, site_config, general_config, overwrite, headers, new_nfo)
	
	if driver:
		driver.quit()
	time.sleep(general_config['sleep']['between_videos'])
	return success


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
	driver.get(url)  # Redundant but ensures we’re on the right page
	
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
			# If only one value, use it directly; otherwise, keep as list for post-processing
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
		
		# Apply post-processing if present, or default to first value for lists without postProcess
		if isinstance(config, dict):
			if 'postProcess' in config:
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
			elif isinstance(value, list) and field not in ['tags', 'actors', 'studios']:
				# Default to first value for lists without postProcess, except multi-value fields
				value = value[0] if value else ''
				logger.debug(f"No postProcess for '{field}' with multiple values; defaulted to first: {value}")
		
		data[field] = value if value or isinstance(value, list) else ''
		logger.debug(f"Final value for '{field}': {data[field]}")
	
	return data

		

def process_list_page(url, site_config, general_config, current_page=1, mode=None, identifier=None, overwrite=False, headers=None, new_nfo=False, do_not_ignore=False):
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
		logger.debug(f"No videos found on page {current_page} with selector '{item_selector}'")
		return None, None, False
	
	# Get terminal width for full-width separators
	term_width = get_terminal_width()
	
	# Two empty lines before page
	print()
	print()
	
	# Page header: single line with gold text
	page_info = f" page {current_page}, {site_config['name'].lower()} {mode}: \"{identifier}\" "
	page_line = page_info.center(term_width, "═")
	print(colored(page_line, "yellow"))
	
	# Process each video
	success = False
	for i, video_element in enumerate(video_elements, 1):
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
		
		# Combine counter and URL into a single left-aligned line with 3 "┈" prefix
		print()  # Empty line before each video entry
		counter = f"{i} of {len(video_elements)}"
		counter_line = f"┈┈┈ {counter} ┈ {video_url} ".ljust(term_width, "┈")
		print(colored(counter_line, "magenta"))
		
		# Process the video
		video_success = process_video_page(video_url, site_config, general_config, overwrite, headers, new_nfo, do_not_ignore)
		if video_success:
			success = True
	
	# Pagination logic
	if mode not in site_config['modes']:
		logger.warning(f"No pagination for mode '{mode}' as it’s not defined in site_config['modes']")
		if driver:
			driver.quit()
		return None, None, success
	
	mode_config = site_config['modes'][mode]
	scraper_pagination = list_scraper.get('pagination', {})
	url_pattern_pages = mode_config.get('url_pattern_pages')
	max_pages = mode_config.get('max_pages', scraper_pagination.get('max_pages', float('inf')))
	
	if current_page >= max_pages:
		logger.warning(f"Stopping pagination: current_page={current_page} >= max_pages={max_pages}")
		if driver:
			driver.quit()
		return None, None, success
	
	next_url = None
	if url_pattern_pages:
		next_url = construct_url(
			base_url,
			url_pattern_pages,
			site_config,
			mode=mode,
			**{mode: identifier, 'page': current_page + 1}
		)
		logger.debug(f"Generated next page URL (pattern-based): {next_url}")
	elif scraper_pagination:
		if 'next_page' in scraper_pagination:
			next_page_config = scraper_pagination['next_page']
			next_page = soup.select_one(next_page_config.get('selector', ''))
			if next_page:
				next_url = next_page.get(next_page_config.get('attribute', 'href'))
				if next_url and not next_url.startswith(('http://', 'https://')):
					next_url = urllib.parse.urljoin(base_url, next_url)
				logger.debug(f"Found next page URL (selector-based): {next_url}")
			else:
				logger.warning(f"No 'next' element found with selector '{next_page_config.get('selector')}'")
	
	if next_url:
		if driver:
			driver.quit()
		return next_url, current_page + 1, success
	logger.warning("No next page URL generated; stopping pagination")
	if driver:
		driver.quit()
	return None, None, success

	
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
	conn = SMBConnection(destination_config['username'], destination_config['password'], "videoscraper", destination_config['server'])
	try:
		if conn.connect(destination_config['server'], 445):
			if not overwrite and file_exists_on_smb(destination_config, smb_path):
				logger.info(f"File '{smb_path}' exists on SMB share. Skipping.")
				return
			
			file_size = os.path.getsize(local_path)
			with open(local_path, 'rb') as file:
				with tqdm(total=file_size, unit='B', unit_scale=True, desc="Uploading to SMB") as pbar:
					progress_file = ProgressFile(file, pbar)
					conn.storeFile(destination_config['share'], smb_path, progress_file)
		else:
			logger.error("Failed to connect to SMB share.")
	except Exception as e:
		logger.error(f"Error uploading to SMB: {e}")
	finally:
		conn.close()


def get_video_metadata(file_path):
	"""Extract video duration, resolution, and bitrate using ffprobe."""
	command = [
		"ffprobe",
		"-v", "error",
		"-show_entries", "format=duration,bit_rate,size:stream=width,height",
		"-of", "json",
		file_path
	]
	try:
		result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, check=True)
		metadata = json.loads(result.stdout)
		
		# File size in bytes (from ffprobe or os)
		file_size = int(metadata.get('format', {}).get('size', os.path.getsize(file_path)))
		
		# Duration in seconds
		duration = float(metadata.get('format', {}).get('duration', 0))
		duration_str = f"{int(duration // 3600):02d}:{int((duration % 3600) // 60):02d}:{int(duration % 60):02d}"
		
		# Resolution
		streams = metadata.get('streams', [])
		video_stream = next((s for s in streams if s.get('width') and s.get('height')), None)
		resolution = f"{video_stream['width']}x{video_stream['height']}" if video_stream else "Unknown"
		
		# Bitrate in kbps
		bitrate = int(metadata.get('format', {}).get('bit_rate', 0)) // 1000 if metadata.get('format', {}).get('bit_rate') else 0
		
		return {
			'size': file_size,
			'size_str': f"{file_size / 1024 / 1024:.2f} MB",
			'duration': duration_str,
			'resolution': resolution,
			'bitrate': f"{bitrate} kbps" if bitrate else "Unknown"
		}
	except subprocess.CalledProcessError as e:
		logger.error(f"ffprobe failed for {file_path}: {e.stderr}")
		return None
	except Exception as e:
		logger.error(f"Error extracting metadata for {file_path}: {e}")
		return None


def download_file(url, destination_path, method, general_config, site_config, headers=None, metadata=None, origin=None, overwrite=False):
	if not url:
		logger.error("Invalid or empty URL")
		return False
	os.makedirs(os.path.dirname(destination_path), exist_ok=True)
	if url.startswith('//'):
		url = 'http:' + url
	
	use_headers = headers and any(k in headers for k in ["Cookie"])
	success = False
	
	desc = f"Downloading {os.path.basename(destination_path)}"
	
	try:
		if method == "requests":
			success = download_with_requests(url, destination_path, headers, general_config, site_config, desc)
		elif method == 'curl':
			success = download_with_curl(url, destination_path, headers, general_config, site_config, desc)
		elif method == 'wget':
			success = download_with_wget(url, destination_path, headers, general_config, site_config, desc)
		elif method == 'yt-dlp':
			success = download_with_ytdlp(url, destination_path, headers, general_config, metadata, desc, overwrite=overwrite)
		elif method == 'ffmpeg':
			success = download_with_ffmpeg(url, destination_path, general_config, headers, desc, origin=origin)
	except Exception as e:
		logger.error(f"Download method '{method}' failed: {e}")
		return False
	
	if success and os.path.exists(destination_path):
		video_info = get_video_metadata(destination_path)
		if video_info:
			logger.success(f"Download completed: {os.path.basename(destination_path)}")
			logger.info(f"Size: {video_info['size_str']} · Duration: {video_info['duration']} · Resolution: {video_info['resolution']}")
		else:
			logger.warning(f"Download completed: {os.path.basename(destination_path)} (Metadata extraction failed)")
	elif not success:
		logger.error(f"Download failed for {destination_path}")
	
	return success

	
def download_with_requests(url, destination_path, headers, general_config, site_config, desc):
	ua = headers.get('User-Agent', random.choice(general_config['user_agents']))
	headers["User-Agent"] = ua
	
	logger.debug(f"Executing requests GET: {url} with headers: {headers}")
	
	with requests.get(url, headers=headers, stream=True) as r:
		r.raise_for_status()
		total_size = int(r.headers.get("Content-Length", 0)) or None
		if not total_size:
			logger.debug("Content-Length unavailable; total size will be determined at completion.")
		
		os.makedirs(os.path.dirname(destination_path), exist_ok=True)
		with open(destination_path, "wb") as f:
			with tqdm(total=total_size, unit="B", unit_scale=True, desc=desc, disable=False) as pbar:
				for chunk in r.iter_content(chunk_size=1024):
					size = f.write(chunk)
					pbar.update(size)
					if not total_size:
						pbar.total = pbar.n
	
	if os.path.exists(destination_path):
		final_size = os.path.getsize(destination_path)
	else:
		logger.error("Download failed: File not found")
		return False
		
	logger.info(f"Successfully completed download to {destination_path}")
	return True
	
def download_with_curl(url, destination_path, headers, general_config, site_config, desc):
	ua = headers.get('User-Agent', random.choice(general_config['user_agents']))
	# -# for progress bar, -w for sizes at each step
	command = ["curl", "-L", "-o", destination_path, "--retry", "3", "--max-time", "600", "-#", 
			   "-w", "Downloaded: %{size_download} bytes / Total: %{size_total} bytes (%{speed_download} bytes/s)\n"]
	if headers:
		command.extend(["-A", ua])
		if "Referer" in headers:
			command.extend(["-H", f"Referer: {headers['Referer']}"])
		if "Cookie" in headers:
			command.extend(["-H", f"Cookie: {headers['Cookie']}"])
	command.append(url)
	
	logger.debug(f"Executing curl command: {' '.join(shlex.quote(arg) for arg in command)}")
	
	# Pipe curl output directly to terminal
	process = subprocess.Popen(
		command,
		stdout=sys.stdout,  # Real-time output to terminal
		stderr=subprocess.STDOUT,
		universal_newlines=True,
		bufsize=1  # Line buffering for live updates
	)
	
	return_code = process.wait()
	if return_code != 0:
		logger.error(f"curl failed with return code {return_code}")
		return False
	
	logger.info(f"Successfully completed curl download to {destination_path}")
	return True

def download_with_wget(url, destination_path, headers, general_config, site_config, desc):
	ua = headers.get('User-Agent', random.choice(general_config['user_agents']))
	command = ["wget", "--tries=3", "--timeout=600", "-O", destination_path]
	if headers:
		command.extend(["--user-agent", ua])
		if "Referer" in headers:
			command.extend(["--referer", headers['Referer']])
		if "Cookie" in headers:
			command.extend(["--header", f"Cookie: {headers['Cookie']}"])
	command.append(url)
	
	logger.debug(f"Executing wget command: {' '.join(shlex.quote(arg) for arg in command)}")
	process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
	
	total_size = get_content_length(url, headers, general_config)
	progress_regex = re.compile(r'(\d+)%\s+(\d+[KMG]?)')
	with tqdm(total=total_size, unit='B', unit_scale=True, desc=desc, disable=not total_size) as pbar:
		for line in process.stdout:
			match = progress_regex.search(line)
			if match:
				percent, _ = match.groups()
				if total_size:
					pbar.update((int(percent) * total_size // 100) - pbar.n)
			elif "Length:" in line and total_size is None:
				size = int(re.search(r'Length: (\d+)', line).group(1))
				pbar.total = size
			elif line.strip():
				logger.debug(f"wget output: {line.strip()}")
			if os.path.exists(destination_path):
				pbar.update(os.path.getsize(destination_path) - pbar.n)
	
	return_code = process.wait()
	if return_code != 0:
		logger.error(f"wget failed with return code {return_code}")
		return False
	logger.info(f"Successfully completed wget download to {destination_path}")
	return True


def download_with_ytdlp(url, destination_path, headers, general_config, metadata, desc, overwrite=False):
	ua = headers.get('User-Agent', random.choice(general_config['user_agents']))
	command = ["yt-dlp", "-o", destination_path, "--user-agent", ua, "--progress"]
	if overwrite:
		command.append("--force-overwrite")
	if metadata and 'Image' in metadata:
		command.extend(["--embed-thumbnail", "--convert-thumbnails", "jpg"])
	command.append(url)
	
	logger.debug(f"Executing yt-dlp command: {' '.join(shlex.quote(arg) for arg in command)}")
	process = subprocess.Popen(
		command,
		stdout=sys.stdout,  # Direct yt-dlp progress to terminal
		stderr=subprocess.STDOUT,  # Errors with stdout
		universal_newlines=True,
		bufsize=1  # Line buffering for real-time output
	)
	
	return_code = process.wait()
	if return_code != 0:
		logger.error(f"yt-dlp failed with return code {return_code}")
		return False
	logger.info(f"Successfully completed yt-dlp download to {destination_path}")
	return True
	
	
def download_with_ffmpeg(url, destination_path, general_config, headers=None, desc="Downloading", origin=None):
	headers = headers or {}
	ua = headers.get('User-Agent', random.choice(general_config['user_agents']))
	if "Headless" in ua:
		ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
	
	fetch_headers = {
		"User-Agent": ua,
		"Referer": headers.get("Referer", ""),
		"Accept": "application/vnd.apple.mpegurl",
	}
	if "Cookie" in headers and headers["Cookie"]:
		logger.debug(f"Including provided cookie: {headers['Cookie']}")
		fetch_headers["Cookie"] = headers["Cookie"]
	# else:
	# 	logger.debug("No cookie provided for fetch")
	if origin:
		logger.debug(f"Including header for origin: {origin}")
		fetch_headers["Origin"] = origin
	else:
		logger.debug("No origin url provided; omitting origin header")
	
	logger.debug(f"Fetching M3U8 with headers: {fetch_headers}")
	try:
		scraper = cloudscraper.create_scraper()
		response = scraper.get(url, headers=fetch_headers, timeout=30)
		response.raise_for_status()
		m3u8_content = response.text
		logger.debug(f"Fetched M3U8 content: {m3u8_content[:100]}...")
	except requests.exceptions.RequestException as e:
		logger.error(f"Failed to fetch M3U8: {e}")
		return False
	
	temp_m3u8_path = destination_path + ".m3u8"
	with open(temp_m3u8_path, "w", encoding="utf-8") as f:
		base_url = url.rsplit('/', 1)[0] + "/"
		segments = []
		for line in m3u8_content.splitlines():
			if line and not line.startswith("#"):
				if not line.startswith("http"):
					line = urllib.parse.urljoin(base_url, line)
				segments.append(line)
				f.write(line + "\n")
			else:
				f.write(line + "\n")
	
	total_segments = len(segments)
	logger.debug(f"Found {total_segments} segments in M3U8")
	
	command = [
		"ffmpeg",
		"-protocol_whitelist", "file,http,https,tcp,tls,crypto",
		"-i", temp_m3u8_path,
		"-c", "copy",
		"-bsf:a", "aac_adtstoasc",
		"-y",
		destination_path
	]
	
	logger.debug(f"Executing FFmpeg command: {' '.join(shlex.quote(arg) for arg in command)}")
	process = subprocess.Popen(
		command,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		universal_newlines=True
	)
	
	desc = f"Downloading {os.path.basename(destination_path)}"
	with tqdm(total=total_segments, unit='seg', desc=desc) as pbar:
		for line in process.stderr:
			line = line.strip()
			if "Opening 'http" in line and '.ts' in line:
				pbar.update(1)
			elif "error" in line.lower() or "failed" in line.lower():
				logger.error(f"FFmpeg error: {line}")
			elif "Duration:" in line:
				logger.debug(f"FFmpeg output: {line}")
	
	return_code = process.wait()
	if os.path.exists(temp_m3u8_path):
		os.remove(temp_m3u8_path)
	
	if return_code != 0:
		logger.error(f"FFmpeg failed with return code {return_code}")
		return False
	logger.info(f"Successfully completed ffmpeg download to {destination_path}")
	return True
	

def get_content_length(url, headers, general_config):
	"""Attempt to fetch Content-Length header for progress bar accuracy."""
	try:
		ua = headers.get('User-Agent', random.choice(general_config['user_agents']))
		fetch_headers = {"User-Agent": ua}
		if "Referer" in headers:
			fetch_headers["Referer"] = headers["Referer"]
		if "Cookie" in headers:
			fetch_headers["Cookie"] = headers["Cookie"]
		response = requests.head(url, headers=fetch_headers, timeout=10, allow_redirects=True)
		response.raise_for_status()
		return int(response.headers.get("Content-Length", 0)) or None
	except Exception as e:
		logger.debug(f"Failed to get Content-Length: {e}")
		return None

def file_exists_on_smb(destination_config, path):
	conn = SMBConnection(destination_config['username'], destination_config['password'], "videoscraper", destination_config['server'])
	try:
		if conn.connect(destination_config['server'], 445):
			try:
				conn.getAttributes(destination_config['share'], path)
				return True
			except:
				return False
		return False
	finally:
		conn.close()

def handle_vpn(general_config, action='start'):
	global last_vpn_action_time
	vpn_config = general_config.get('vpn', {})
	if not vpn_config.get('enabled', False):
		return
	vpn_bin = vpn_config.get('vpn_bin', '')
	cmd = vpn_config.get(f"{action}_cmd", '').format(vpn_bin=vpn_bin)
	try:
		subprocess.run(cmd, shell=True, check=True)
		last_vpn_action_time = time.time()
		logger.info(f"VPN {action} executed")
	except subprocess.CalledProcessError as e:
		logger.error(f"Failed VPN {action}: {e}")

def process_fallback_download(url, general_config, overwrite=False):
	destination_config = general_config['download_destinations'][0]
	temp_dir = os.path.join(tempfile.gettempdir(), f"download_{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
	os.makedirs(temp_dir, exist_ok=True)
	logger.info(f"Fallback download for: {url}")
	success, downloaded_files = download_with_ytdlp_fallback(url, temp_dir, general_config)
	if not success or not downloaded_files:
		shutil.rmtree(temp_dir, ignore_errors=True)
		return False
	
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

def download_with_ytdlp_fallback(url, temp_dir, general_config):
	command = f"yt-dlp --paths {temp_dir} --format best --add-metadata"
	if general_config.get('user_agents'):
		command += f" --user-agent \"{random.choice(general_config['user_agents'])}\""
	command += f" \"{url}\""
	process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, cwd=temp_dir)
	progress_regex = re.compile(r'\[download\]\s+(\d+\.\d+)% of ~?\s*(\d+\.\d+)(K|M|G)iB')
	filename_regex = re.compile(r'\[download\] Destination: (.+)')
	downloaded_files = []
	total_size = None
	pbar = None
	try:
		for line in process.stdout:
			filename_match = filename_regex.search(line)
			if filename_match:
				filename = os.path.basename(filename_match.group(1))
				if filename not in downloaded_files:
					downloaded_files.append(filename)
			progress_match = progress_regex.search(line)
			if progress_match:
				percent, size, size_unit = progress_match.groups()
				if total_size is None:
					total_size = float(size) * {'K': 1024, 'M': 1024**2, 'G': 1024**3}[size_unit]
					pbar = tqdm(total=total_size, unit='B', unit_scale=True, desc="Downloading")
				progress = float(percent) * total_size / 100
				if pbar:
					pbar.update(progress - pbar.n)
			logger.debug(line.strip())
	except KeyboardInterrupt:
		process.terminate()
		if pbar:
			pbar.close()
		return False, []
	if pbar:
		pbar.close()
	success = process.wait() == 0
	if success and not downloaded_files:
		downloaded_files = os.listdir(temp_dir)
	return success and downloaded_files, downloaded_files

def match_url_to_mode(url, site_config):
	# Normalize the input URL
	parsed_url = urlparse(url)
	scheme = parsed_url.scheme.lower()  # e.g., 'http' or 'https'
	netloc = parsed_url.netloc.lower()  # e.g., 'www.incestflix.com' or 'incestflix.com'
	path = parsed_url.path.rstrip('/').lower()  # e.g., '/watch/video123' or '/tag/sometag'
	
	# Remove 'www.' prefix if present
	if netloc.startswith('www.'):
		netloc = netloc[4:]
	
	# Normalize the base_url from site_config
	base_url = site_config['base_url'].rstrip('/')
	parsed_base = urlparse(base_url)
	base_netloc = parsed_base.netloc.lower()  # e.g., 'incestflix.com'
	base_path = parsed_base.path.rstrip('/').lower()  # Usually empty for base_url
	
	# Remove 'www.' prefix from base_netloc if present
	if base_netloc.startswith('www.'):
		base_netloc = base_netloc[4:]
	
	# Check if the normalized netloc matches the base_netloc
	if netloc != base_netloc:
		logger.debug(f"No match: netloc '{netloc}' does not match base_netloc '{base_netloc}'")
		return None, None
	
	# Combine base_path and path for matching (if base_url has a path component)
	effective_path = path
	
	# Iterate over modes to find a match
	for mode, config in site_config['modes'].items():
		pattern = config['url_pattern'].rstrip('/')
		pattern_segments = pattern.lstrip('/').split('/')
		path_segments = effective_path.lstrip('/').split('/')
		
		# Skip if path is too short to match pattern (accounting for placeholders)
		if len(path_segments) < len(pattern_segments) - pattern.count('{'):
			continue
		
		regex_parts = []
		placeholder_found = False
		for i, segment in enumerate(pattern_segments):
			if '{' in segment and '}' in segment:
				placeholder_found = True
				regex_parts.append(r'([^/]+)')
			else:
				regex_parts.append(re.escape(segment.lower()))  # Normalize case
		
		if not placeholder_found:
			if effective_path == pattern.lstrip('/').lower():
				logger.info(f"Matched URL '{url}' to mode '{mode}' with exact pattern '{pattern}'")
				return mode, config['scraper']
			continue
		
		regex_pattern = '^/' + '/'.join(regex_parts)
		if placeholder_found and len(path_segments) > len(pattern_segments):
			regex_pattern += r'(?:/.*)?'
		regex_pattern += '$'
		
		if re.match(regex_pattern, effective_path):
			logger.info(f"Matched URL '{url}' to mode '{mode}' with pattern '{pattern}'")
			return mode, config['scraper']
	
	logger.debug(f"No mode matched for URL: {url}")
	return None, None

def has_metadata_selectors(site_config, return_fields=False):
	"""
	Check if the site config has selectors for metadata fields beyond title and download_url.
	If return_fields=True, return the list of fields instead of a boolean.
	"""
	video_scraper = site_config.get('scrapers', {}).get('video_scraper', {})
	excluded = {'title', 'download_url'}
	metadata_fields = [field for field in video_scraper.keys() if field not in excluded]
	
	if return_fields:
		return ", ".join(sorted(metadata_fields)) if metadata_fields else "None"
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
	actors = [actor.lstrip('#') for actor in final_metadata.get('actors', []) if actor]
	studios = [studio.lstrip('#') for studio in final_metadata.get('studios', []) if studio]
	tags = [tag.lstrip('#') for tag in final_metadata.get('tags', []) if tag]
	
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
	
	return final_metadata


def handle_nfo_and_download(video_url, final_metadata, site_config, general_config, overwrite=False, headers=None, new_nfo=False):
	"""Handle NFO generation and video download."""
	file_name = construct_filename(final_metadata['title'], site_config, general_config)
	destination_config = general_config['download_destinations'][0]
	overwrite = overwrite or site_config.get('overwrite', general_config.get('overwrite', False))
	nfo_overwrite = overwrite or new_nfo
	
	# Setup paths
	if destination_config['type'] == 'smb':
		smb_destination_path = os.path.join(destination_config['path'], file_name)
		smb_nfo_path = os.path.join(destination_config['path'], f"{file_name.rsplit('.', 1)[0]}.nfo")
		temp_base = os.path.join(tempfile.gettempdir(), 'smutscrape')
		temp_dir = destination_config.get('temporary_storage', temp_base)
		os.makedirs(temp_dir, exist_ok=True)
		destination_path = os.path.join(temp_dir, file_name)
		temp_nfo_path = os.path.join(temp_dir, f"{file_name.rsplit('.', 1)[0]}.nfo")
		video_exists = file_exists_on_smb(destination_config, smb_destination_path)
		nfo_exists = file_exists_on_smb(destination_config, smb_nfo_path)
	else:
		destination_path = os.path.join(destination_config['path'], file_name)
		nfo_path = f"{destination_path.rsplit('.', 1)[0]}.nfo"
		video_exists = os.path.exists(destination_path)
		nfo_exists = os.path.exists(nfo_path)
	
	temp_exists = os.path.exists(destination_path)
	download_method = site_config['download'].get('method', 'curl')
	origin_to_use = urllib.parse.urlparse(video_url).scheme + "://" + urllib.parse.urlparse(video_url).netloc
	
	make_nfo = general_config.get('make_nfo', False)
	has_selectors = has_metadata_selectors(site_config)
	
	# Generate NFO
	if make_nfo and has_selectors:
		if destination_config['type'] == 'smb':
			if nfo_overwrite or not nfo_exists:
				generate_nfo_file(destination_path, final_metadata)
				if os.path.exists(temp_nfo_path):
					upload_to_smb(temp_nfo_path, smb_nfo_path, destination_config, nfo_overwrite)
					os.remove(temp_nfo_path)
					logger.success(f"{'Replaced' if nfo_exists else 'Uploaded'} NFO to {smb_nfo_path}")
			else:
				logger.debug(f"NFO exists at {smb_nfo_path}, skipping")
		else:
			if nfo_overwrite or not nfo_exists:
				generate_nfo_file(destination_path, final_metadata)
				if nfo_exists:
					logger.success(f"Replaced NFO at {nfo_path}")
			else:
				logger.debug(f"NFO exists at {nfo_path}, skipping")
	
	# Handle download
	if video_exists and not overwrite:
		logger.info(f"File '{file_name}' exists at destination. Skipping download.")
		return True
	elif not overwrite and temp_exists:
		video_info = get_video_metadata(destination_path)
		if video_info:
			logger.info(f"Valid video in temp: {file_name}. Uploading.")
			if destination_config['type'] == 'smb':
				upload_to_smb(destination_path, smb_destination_path, destination_config, overwrite)
				os.remove(destination_path)
			elif destination_config['type'] == 'local':
				apply_permissions(destination_path, destination_config)
			return True
		else:
			logger.warning(f"Invalid temp file: {destination_path}. Redownloading.")
			os.remove(destination_path)
	
	logger.info(f"Downloading: {file_name}")
	if download_file(video_url, destination_path, download_method, general_config, site_config, headers=headers, metadata=final_metadata, origin=origin_to_use, overwrite=overwrite):
		if destination_config['type'] == 'smb':
			upload_to_smb(destination_path, smb_destination_path, destination_config, overwrite)
			os.remove(destination_path)
		elif destination_config['type'] == 'local':
			apply_permissions(destination_path, destination_config)
		logger.success(f"Processed video: {file_name}")
		return True
	else:
		logger.error(f"Download failed: {file_name}")
		return False

def generate_nfo_file(video_path, metadata):
	"""Generate NFO file from finalized metadata."""
	nfo_path = f"{video_path.rsplit('.', 1)[0]}.nfo"
	
	try:
		with open(nfo_path, 'w', encoding='utf-8') as f:
			f.write('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n')
			f.write('<movie>\n')
			if 'title' in metadata and metadata['title']:
				f.write(f"  <title>{metadata['title']}</title>\n")
			if 'URL' in metadata and metadata['URL']:
				f.write(f"  <url>{metadata['URL']}</url>\n")
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
		logger.info(f"Generated NFO file: {nfo_path}")
		return True
	except Exception as e:
		logger.error(f"Failed to generate NFO file {nfo_path}: {e}", exc_info=True)
		raise


def get_terminal_width():
	try:
		return os.get_terminal_size().columns
	except OSError:
		return 80

def interpolate_color(start_rgb, end_rgb, steps, step):
	r = int(start_rgb[0] + (end_rgb[0] - start_rgb[0]) * step / (steps - 1))
	g = int(start_rgb[1] + (end_rgb[1] - start_rgb[1]) * step / (steps - 1))
	b = int(start_rgb[2] + (end_rgb[2] - start_rgb[2]) * step / (steps - 1))
	return (r, g, b)

def load_ascii_art(script_dir, term_width):
	logo_dir = os.path.join(script_dir, "logo")
	
	if not os.path.exists(logo_dir):
		logger.warning(f"Logo directory '{logo_dir}' not found.")
		return None
	
	logo_files = [f for f in os.listdir(logo_dir) if f.endswith(".txt") and f[:-4].isdigit()]
	if not logo_files:
		logger.warning(f"No valid ASCII art files in '{logo_dir}'.")
		return None
	
	widths = [int(f[:-4]) for f in logo_files]
	widths.sort()
	suitable_width = max((w for w in widths if w <= term_width), default=None)
	if suitable_width is None:
		logger.debug(f"No ASCII art fits width {term_width}.")
		return None
	
	art_file = os.path.join(logo_dir, f"{suitable_width}.txt")
	try:
		with open(art_file, "r", encoding="utf-8") as f:
			# Preserve all spaces, only filter truly empty lines
			lines = [line for line in f.read().splitlines() if line.strip()]
		
		if not lines:
			return None
		
		# Find the longest line to determine art width
		art_width = max(len(line) for line in lines)
		# Calculate left padding to center the entire block
		left_padding = (term_width - art_width) // 2
		if left_padding < 0:
			left_padding = 0  # Art too wide, align left
		
		# Pad each line to match the longest, then add left padding
		padded_lines = [line + " " * (art_width - len(line)) for line in lines]
		centered_lines = [" " * left_padding + line for line in padded_lines]
		
		# Apply gradient
		start_rgb = (255, 105, 180)  # Pink
		end_rgb = (255, 165, 0)      # Orange
		steps = len(lines)
		
		for i, line in enumerate(centered_lines):
			rgb = interpolate_color(start_rgb, end_rgb, steps, i)
			style = Style(color=f"rgb({rgb[0]},{rgb[1]},{rgb[2]})", bold=True)
			console.print(line, style=style, justify="left", overflow="crop", no_wrap=True)
		return True
	except Exception as e:
		logger.error(f"Failed to load ASCII art from '{art_file}': {e}")
		return None

def find_site_config(site_input):
	"""
	Find a site config by matching site_input against shortcode, name, or domain (case-insensitive).
	Returns the config dict or None if no match.
	"""
	site_input_lower = site_input.lower()
	for config_file in os.listdir(CONFIG_DIR):
		if config_file.endswith(".yaml"):
			try:
				with open(os.path.join(CONFIG_DIR, config_file), 'r') as f:
					site_config = yaml.safe_load(f)
				# Check shortcode, name, domain
				if site_config.get('shortcode', '').lower() == site_input_lower:
					logger.debug(f"Matched '{site_input}' to shortcode '{site_config['shortcode']}' in '{config_file}'")
					return site_config
				if site_config.get('name', '').lower() == site_input_lower:
					logger.debug(f"Matched '{site_input}' to name '{site_config['name']}' in '{config_file}'")
					return site_config
				if site_config.get('domain', '').lower() == site_input_lower:
					logger.debug(f"Matched '{site_input}' to domain '{site_config['domain']}' in '{config_file}'")
					return site_config
			except Exception as e:
				logger.warning(f"Failed to load config '{config_file}': {e}")
	logger.error(f"No site config found matching '{site_input}' (shortcode, name, or domain)")
	return None

def display_options():
	console.print("[bold][yellow]Options:[/yellow][/bold]")
	console.print("  [magenta]--overwrite[/magenta]      # Replace existing files with same name at download destination")
	console.print("  [magenta]--new_nfo[/magenta]        # Update the metadata in existing .nfo files")
	console.print("  [magenta]--page {number}[/magenta]  # Scrape results starting on provided page number")
	console.print("  [magenta]--debug[/magenta]          # Enable detailed debug logging")

def display_global_examples():
	console.print("[bold]Randomly Generated Examples:[/bold]")
	
	# Collect all site/mode/example combos
	all_examples = []
	for site_config_file in os.listdir(CONFIG_DIR):
		if site_config_file.endswith(".yaml"):
			try:
				with open(os.path.join(CONFIG_DIR, site_config_file), 'r') as f:
					site_config = yaml.safe_load(f)
				site_name = site_config.get("name", "Unknown")
				shortcode = site_config.get("shortcode", "??")
				modes = site_config.get("modes", {})
				for mode, config in modes.items():
					tip = config.get("tip", "No description available")
					examples = config.get("examples", ["N/A"])
					for example in examples:
						all_examples.append((site_name, shortcode, mode, tip, example))
			except Exception as e:
				logger.warning(f"Failed to load config '{site_config_file}': {e}")
	
	# Randomly select up to 10 examples
	selected_examples = random.sample(all_examples, min(10, len(all_examples))) if all_examples else []
	
	# Display in a borderless table
	table = Table(show_edge=False, expand=True, show_lines=False, show_header=True)
	table.add_column("[magenta][bold]Command[/bold][/magenta]", justify="right")
	table.add_column("[yellow]Effect[/yellow]", justify="left")
	
	for site_name, shortcode, mode, tip, example in selected_examples:
		cmd = f"[magenta]scrape[/magenta] [yellow]{shortcode}[/yellow] [green]{mode}[/green] [blue]\"{example}\"[/blue]"
		effect = f"{tip} [bold][blue]\"{example}\"[/blue][/bold] on [bold][yellow]{site_name}[/yellow][/bold]"
		table.add_row(cmd, effect)
	
	console.print(table)
	console.print()

def display_site_details(site_config, term_width):
	"""Display a detailed readout for a specific site config."""
	site_name = site_config.get("name", "Unknown")
	shortcode = site_config.get("shortcode", "??")
	domain = site_config.get("domain", "unknown domain")
	base_url = site_config.get("base_url", "https://example.com")
	video_uri = site_config.get("modes", {}).get("video", {}).get("url_pattern", "/watch/0123456.html")
	download_method = site_config.get("download", {}).get("method", "N/A")
	use_selenium = site_config.get("use_selenium", False)
	name_suffix = site_config.get("name_suffix", None)
	metadata = has_metadata_selectors(site_config, return_fields=True)
	
	# Combine counter and URL into a single left-aligned line with "┈" padding
	site_header = f"{site_name} ".ljust(term_width, "┈")
	console.print(f"[yellow][bold]{site_header}[/bold][/yellow]")
	console.print()
	console.print(f"   Domain: [bold]{domain}[/bold]")
	console.print(f"Shortcode: [bold]{shortcode}[/bold]")
	console.print(f"   Method: [bold]{download_method}[/bold]")
	console.print(f" Metadata: {metadata}")
	if name_suffix:
		console.print(f"     Note: Filenames are appended with \"{name_suffix}\".")
	if use_selenium:
		console.print(f"     Note: [yellow][bold]selenium[/bold][/yellow] and [yellow][bold]chromedriver[/bold][/yellow] are required to scrape this site.")
		console.print(f"           See: https://github.com/io-flux/smutscrape#selenium--chromedriver-%EF%B8%8F%EF%B8%8F")
	console.print()
	console.print(f"    Usage: [magenta]scrape {shortcode} {{mode}} {{query}}[/magenta]")
	console.print(f"           [magenta]scrape {base_url}{video_uri}[/magenta]")
	console.print()
	
	# Modes Table
	modes = site_config.get("modes", {})
	if modes:
		console.print("[yellow][bold]Available Modes:[/bold][/yellow]")
		mode_table = Table(show_edge=True, expand=True, width=term_width)
		mode_table.add_column("[bold]Mode[/bold]", width=7)
		mode_table.add_column("[bold]Purpose[/bold]", width=(term_width//10)*4)
		mode_table.add_column("[bold]Example[/bold]", width=term_width//2)
		
		for mode, config in modes.items():
			tip = config.get("tip", "No description available")
			examples = config.get("examples", ["N/A"])
			example = random.choice(examples)  # Pick a random example
			example_cmd = f"[magenta]scrape {shortcode} {mode} \"{example}\"[/magenta]"
			mode_table.add_row(mode, tip, example_cmd)
		console.print(mode_table)
		console.print()
	
	display_options()

def main():
	parser = argparse.ArgumentParser(
		description="Smutscrape: Scrape and download adult content from various sites with metadata saved in .nfo files."
	)
	parser.add_argument("args", nargs="*", help="Site shortcode, name, or domain followed by mode and query (e.g., 'ph search \"big boobs\"'), or a direct URL.")
	parser.add_argument("--debug", action="store_true", help="Enable detailed debug logging.")
	parser.add_argument("--overwrite", action="store_true", help="Overwrite existing video files.")
	parser.add_argument("--new_nfo", action="store_true", help="Regenerate .nfo files even if they exist.")
	parser.add_argument("--do_not_ignore", action="store_true", help="Override the ignore list in general config.yaml")
	parser.add_argument("--page", type=int, default=1, help="Start scraping from this page number.")
	args = parser.parse_args()
	
	term_width = get_terminal_width()
	
	# Display graphic header
	top_bar_text = " welcome to "
	top_bar = top_bar_text.center(term_width, "═")
	console.print(top_bar, style=Style(color="yellow"))
	console.print()
	ascii_art = load_ascii_art(SCRIPT_DIR, term_width)
	if not ascii_art:
		fallback_text = "S M U T S C R A P E"
		console.print(fallback_text.center(term_width), style=Style(color="magenta", bold=True))
	console.print()
	
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
	general_config = load_config(os.path.join(SCRIPT_DIR, "config.yaml"))
	
	if not args.args:  # No arguments, show full usage
		console.print("Smutscrape helps you get the smut you desire without opening a browser.")
		console.print()
		console.print("[bold]Usage:[/bold] [magenta]scrape[/magenta] [yellow]{site}[/yellow] [green]{mode}[/green] [blue]{query}[/blue]  or  [magenta]scrape[/magenta] {url}")
		console.print()
		console.print(f"[bold]Supported Sites[/bold] (loaded from {CONFIG_DIR}:")
		if not os.path.exists(CONFIG_DIR):
			logger.error(f"Configs directory '{CONFIG_DIR}' not found.")
			sys.exit(1)
		
		table = Table(show_edge=True, expand=True, width=term_width)
		table.add_column("[bold][yellow]Site (shortcode)[/yellow][/bold]", width=term_width//5)
		table.add_column("[bold][green]Scrape Modes[/green][/bold]", width=(term_width//5)*2)
		table.add_column("[bold]Available Metadata[/bold]", width=(term_width//5)*2)
		
		supported_sites = []
		for site_config_file in os.listdir(CONFIG_DIR):
			if site_config_file.endswith(".yaml"):
				try:
					with open(os.path.join(CONFIG_DIR, site_config_file), 'r') as f:
						site_config = yaml.safe_load(f)
					site_name = site_config.get("name", "Unknown")
					site_code = site_config.get("shortcode", "??")
					site_display = f"{site_name} ({site_code})"
					modes = [m for m in site_config.get("modes", {}).keys() if m != "video"]
					modes_display = ", ".join(modes) if modes else "None"
					metadata = has_metadata_selectors(site_config, return_fields=True)
					supported_sites.append((site_display, modes_display, metadata))
				except Exception as e:
					logger.warning(f"Failed to load config '{site_config_file}': {e}")
		
		if supported_sites:
			for site_display, modes_display, metadata in sorted(supported_sites):
				table.add_row(site_display, modes_display, metadata)
		else:
			logger.warning(f"No valid site configs found in {CONFIG_DIR}")
			table.add_row("No sites loaded", "", "")
		
		console.print(table)
		console.print()
		console.print()
		display_global_examples()
		display_options()
		sys.exit(0)
	
	try:
		if len(args.args) == 1:  # Single arg: site or URL
			if args.args[0].startswith(("http://", "https://")):  # URL case
				url = args.args[0]
				logger.debug(f"Looking for config matches for {url}...")
				matched_site_config = None
				for site_config_file in os.listdir(CONFIG_DIR):
					if site_config_file.endswith(".yaml"):
						with open(os.path.join(CONFIG_DIR, site_config_file), 'r') as f:
							site_config = yaml.safe_load(f)
						parsed_url = urlparse(url)
						url_domain = parsed_url.netloc.lower().replace("www.", "")
						config_domain = site_config.get("domain", "").lower()
						if url_domain == config_domain:
							matched_site_config = site_config
							break
				
				if matched_site_config:
					headers = general_config.get("headers", {}).copy()
					headers["User-Agent"] = random.choice(general_config["user_agents"])
					mode, scraper = match_url_to_mode(url, matched_site_config)
					
					if mode:
						logger.info(f"Matched URL to mode '{mode}' with scraper '{scraper}'")
						if mode == "video":
							success = process_video_page(url, matched_site_config, general_config, args.overwrite, headers, args.new_nfo, True)
						else:
							identifier = url.split("/")[-1].split(".")[0]
							current_page = args.page
							mode_config = matched_site_config["modes"][mode]
							if current_page > 1 and mode_config.get("url_pattern_pages"):
								url = construct_url(
									matched_site_config["base_url"],
									mode_config["url_pattern_pages"],
									matched_site_config,
									mode=mode,
									**{mode: identifier, "page": current_page}
								)
								logger.info(f"Starting at custom page {current_page}: {url}")
							success = False
							while url:
								next_page, new_page_number, page_success = process_list_page(
									url, matched_site_config, general_config, current_page,
									mode, identifier, args.overwrite, headers, args.new_nfo
								)
								success = success or page_success
								if next_page is None:
									break
								url = next_page
								current_page = new_page_number
								time.sleep(general_config["sleep"]["between_pages"])
					else:
						logger.warning("URL didn't match any specific mode; attempting all configured modes.")
						available_modes = matched_site_config.get("modes", {})
						attempted_modes = []
						
						for mode_name in available_modes:
							if mode_name == "video":
								logger.info("Trying 'video' mode...")
								success = process_video_page(url, matched_site_config, general_config, args.overwrite, headers, True)
								attempted_modes.append("video")
								if success:
									logger.info("Video mode succeeded; stopping mode attempts.")
									break
							else:
								logger.info(f"Attempting mode '{mode_name}'...")
								attempted_modes.append(mode_name)
								identifier = url.split("/")[-1].split(".")[0]
								current_page = args.page
								mode_config = matched_site_config["modes"][mode_name]
								
								if mode_config.get("url_pattern"):
									try:
										constructed_url = construct_url(
											matched_site_config["base_url"],
											mode_config["url_pattern"],
											matched_site_config,
											mode=mode_name,
											**{mode_name: identifier}
										)
										if current_page > 1 and mode_config.get("url_pattern_pages"):
											constructed_url = construct_url(
												matched_site_config["base_url"],
												mode_config["url_pattern_pages"],
												matched_site_config,
												mode=mode_name,
												**{mode_name: identifier, "page": current_page}
											)
											logger.info(f"Starting at custom page {current_page}: {constructed_url}")
										else:
											logger.info(f"Attempting: {constructed_url}")
										
										success = False
										while constructed_url:
											next_page, new_page_number, page_success = process_list_page(
												constructed_url, matched_site_config, general_config, current_page,
												mode_name, identifier, args.overwrite, headers, args.new_nfo
											)
											success = success or page_success
											if next_page is None:
												break
											constructed_url = next_page
											current_page = new_page_number
											time.sleep(general_config["sleep"]["between_pages"])
										if success:
											logger.info(f"Mode '{mode_name}' succeeded; stopping mode attempts.")
											break
									except Exception as e:
										logger.debug(f"Mode '{mode_name}' failed: {e}")
										continue
						
						if not success and len(attempted_modes) == len(available_modes):
							logger.error(f"Failed to process URL '{url}' with any mode: {', '.join(attempted_modes)}")
							process_fallback_download(url, general_config, args.overwrite)
				else:
					process_fallback_download(url, general_config, args.overwrite)
			else:  # Site-only case
				site_input = args.args[0]
				site_config = find_site_config(site_input)
				if not site_config:
					logger.error(f"Site '{site_input}' not found as shortcode, name, or domain in {CONFIG_DIR}")
					sys.exit(1)
				display_site_details(site_config, term_width)
				sys.exit(0)
		
		elif len(args.args) >= 3:  # Site + mode + query
			site_input = args.args[0]
			mode = args.args[1]
			identifier = " ".join(args.args[2:])
			
			site_config = find_site_config(site_input)
			if not site_config:
				logger.error(f"Site '{site_input}' not found as shortcode, name, or domain in {CONFIG_DIR}")
				sys.exit(1)
			
			headers = general_config.get("headers", {})
			handle_vpn(general_config, "start")
			if mode not in site_config["modes"]:
				logger.error(f"Unsupported mode '{mode}' for site '{site_input}'")
				sys.exit(1)
			mode_config = site_config["modes"][mode]
			current_page = args.page
			if current_page > 1 and mode_config.get("url_pattern_pages"):
				url = construct_url(
					site_config["base_url"],
					mode_config["url_pattern_pages"],
					site_config,
					mode=mode,
					**{mode: identifier, "page": current_page}
				)
				logger.debug(f"Starting at custom page {current_page}: {url}")
			else:
				url = construct_url(
					site_config["base_url"],
					mode_config["url_pattern"],
					site_config,
					mode=mode,
					**{mode: identifier}
				)
				if current_page > 1:
					logger.warning(f"Starting page {current_page} requested, but no 'url_pattern_pages' defined; starting at page 1")
			if mode == "video":
				process_video_page(url, site_config, general_config, args.overwrite, headers, True)
			else:
				while url:
					next_page, new_page_number, page_success = process_list_page(
						url, site_config, general_config, current_page, mode,
						identifier, args.overwrite, headers, args.new_nfo
					)
					if next_page is None:
						break
					url = next_page
					current_page = new_page_number
					time.sleep(general_config["sleep"]["between_pages"])
		else:
			logger.error("Invalid arguments. Provide site (shortcode, name, or domain), mode, and identifier, or a URL.")
			sys.exit(1)
	except KeyboardInterrupt:
		logger.warning("Interrupted by user.")
	except Exception as e:
		logger.error(f"Error: {e}")
	finally:
		if "selenium_driver" in general_config and general_config["selenium_driver"] is not None:
			try:
				general_config["selenium_driver"].quit()
				logger.info("Selenium driver closed cleanly.")
			except Exception as e:
				logger.warning(f"Failed to close Selenium driver: {e}")
		print()

if __name__ == "__main__":
	main()
