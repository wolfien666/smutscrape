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
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIG_DIR = os.path.join(SCRIPT_DIR, 'configs')

last_vpn_action_time = 0
session = requests.Session()


		
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
				logger.info(f"Using user-specified ChromeDriver at: {chromedriver_path}")
				service = Service(executable_path=chromedriver_path)
			else:
				# Fallback to webdriver_manager
				logger.info("No chromedriver_path specified; using webdriver_manager to fetch ChromeDriver")
				service = Service(ChromeDriverManager().install())
				logger.info(f"Using ChromeDriver at: {service.path}")
			
			driver = webdriver.Chrome(service=service, options=chrome_options)
			logger.info(f"Initialized Selenium driver with Chrome version: {driver.capabilities['browserVersion']}")
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

def generate_nfo_file(video_path, metadata):
	nfo_path = f"{video_path.rsplit('.', 1)[0]}.nfo"
	
	tag_uppercase = [
		"ABDL", "ASMR", "BBW", "BDSM", "DILF", "DP", "HD", "JAV", "JOI", "POV", "BBS", "BS", "BSS",
		"FD", "FDD", "FDDD", "FDDDD", "FMD", "FMDD", "FMDDD", "FMS", "FMSS", "FS",
		"FSD", "MD", "MDD", "MDDD", "MDDDD", "MILF", "MMD", "MMS", "MS", "MSD", "MSS",
		"MSSD", "MSSS", "MSSSS", "MSDD", "SS", "3D", "4K"
	]
	studio_uppercase = ["DP", "HD", "JAV", "JOI", "MILF", "POV", "3D", "4K"]
	
	try:
		logger.debug(f"Using generate_nfo_file version 1.3")
		logger.debug(f"Generating NFO with metadata: {metadata}")
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
			if 'tags' in metadata:
				logger.debug(f"Tags value: {metadata['tags']}")
				if metadata['tags'] is None:
					logger.warning(f"Tags is None for {nfo_path}")
				elif len(metadata['tags']) > 0:
					for tag in set(metadata['tags']):
						cleaned_tag = tag.lstrip('#')
						formatted_tag = custom_title_case(cleaned_tag, tag_uppercase)
						f.write(f"  <tag>{formatted_tag}</tag>\n")
			if 'actors' in metadata:
				logger.debug(f"Actors value: {metadata['actors']}")
				if metadata['actors'] is None:
					logger.warning(f"Actors is None for {nfo_path}")
				elif len(metadata['actors']) > 0:
					for i, performer in enumerate(metadata['actors'], 1):
						cleaned_performer = performer.lstrip('#')
						formatted_performer = custom_title_case(cleaned_performer, tag_uppercase, preserve_mixed_case=True)
						f.write(f"  <actor>\n    <name>{formatted_performer}</name>\n    <order>{i}</order>\n  </actor>\n")
			if 'Image' in metadata and metadata['Image']:
				f.write(f"  <thumb aspect=\"poster\">{metadata['Image']}</thumb>\n")
			if 'studio' in metadata and metadata['studio']:
				cleaned_studio = metadata['studio'].lstrip('#')
				formatted_studio = custom_title_case(cleaned_studio, studio_uppercase, preserve_mixed_case=True)
				f.write(f"  <studio>{formatted_studio}</studio>\n")
			elif 'studios' in metadata:
				logger.debug(f"Studios value: {metadata['studios']}")
				if metadata['studios'] is None:
					logger.warning(f"Studios is None for {nfo_path}")
				elif len(metadata['studios']) > 0:
					cleaned_studio = metadata['studios'][0].lstrip('#')  # Only take first studio
					formatted_studio = custom_title_case(cleaned_studio, studio_uppercase, preserve_mixed_case=True)
					f.write(f"  <studio>{formatted_studio}</studio>\n")
			if 'description' in metadata and metadata['description']:
				f.write(f"  <plot>{metadata['description']}</plot>\n")
			
			f.write('</movie>\n')
		logger.info(f"Generated NFO file: {nfo_path}")
		return True
	except Exception as e:
		logger.error(f"Failed to generate NFO file {nfo_path}: {e}", exc_info=True)  # Include stack trace
		raise

def process_video_page(url, site_config, general_config, overwrite_files=False, headers=None, force_new_nfo=False):
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
	base_origin = urllib.parse.urlparse(original_url).scheme + "://" + urllib.parse.urlparse(original_url).netloc
	
	iframe_url = None
	if site_config.get('m3u8_mode', False) and driver:
		video_scraper = site_config['scrapers']['video_scraper']
		iframe_config = None
		for field, config in video_scraper.items():
			if isinstance(config, dict) and 'iframe' in config:
				iframe_config = {'enabled': True, 'selector': config['iframe']}
				break
		if iframe_config:
			logger.debug(f"Piercing iframe '{iframe_config['selector']}' for M3U8 extraction")
			driver.get(original_url)
			time.sleep(random.uniform(1, 2))
			try:
				iframe = driver.find_element(By.CSS_SELECTOR, iframe_config['selector'])
				iframe_url = iframe.get_attribute("src")
				if iframe_url:
					logger.info(f"Found iframe with src: {iframe_url}")
					driver.get(iframe_url)
					time.sleep(random.uniform(1, 2))
					m3u8_url, cookies = extract_m3u8_urls(driver, iframe_url, site_config)
					if m3u8_url:
						video_url = m3u8_url
						headers = headers or general_config.get('headers', {}).copy()
						headers["Cookie"] = cookies
						headers["Referer"] = iframe_url
						headers["User-Agent"] = general_config.get('selenium_user_agent', random.choice(general_config['user_agents']))
						soup = fetch_page(original_url, general_config['user_agents'], headers, use_selenium, driver)
						data = extract_data(soup, site_config['scrapers']['video_scraper'], driver, site_config) if soup else {'title': original_url.split('/')[-2]}
					else:
						logger.error("Failed to extract M3U8 URL; falling back to page scrape.")
						video_url = None
				else:
					logger.debug("Iframe found but no src attribute.")
					video_url = None
			except Exception as e:
				logger.debug(f"No iframe found or error piercing: {e}")
				video_url = None
			soup = fetch_page(original_url, general_config['user_agents'], headers or {}, use_selenium, driver)
			data = extract_data(soup, site_config['scrapers']['video_scraper'], driver, site_config) if soup else {'title': original_url.split('/')[-2]}
		else:
			soup = fetch_page(original_url, general_config['user_agents'], headers or {}, use_selenium, driver)
			data = extract_data(soup, site_config['scrapers']['video_scraper'], driver, site_config) if soup else {'title': original_url.split('/')[-2]}
			video_url = data.get('download_url')
	else:
		soup = fetch_page(original_url, general_config['user_agents'], headers or {}, use_selenium, driver)
		if soup is None and use_selenium:
			logger.warning("Selenium failed; retrying with requests")
			soup = fetch_page(original_url, general_config['user_agents'], headers or {}, False, None)
		if soup is None:
			logger.error(f"Failed to fetch video page: {original_url}")
			return
		data = extract_data(soup, site_config['scrapers']['video_scraper'], driver, site_config)
		video_url = data.get('download_url')
	
	logger.debug(f"Extracted video data: {data}")
	if not video_url or video_url.strip() == '':
		video_url = original_url
		logger.debug(f"download_url empty or missing; falling back to page URL: {video_url}")
	else:
		logger.debug(f"video_url: {video_url}")
	video_title = data.get('title', '').strip() or 'Untitled'
	data['Title'] = video_title
	data['URL'] = original_url
	
	if should_ignore_video(data, general_config['ignored']):
		logger.info(f"Ignoring video: {video_title}")
		return
	
	file_name = construct_filename(video_title, site_config, general_config)
	destination_config = general_config['download_destinations'][0]
	overwrite = overwrite_files or site_config.get('overwrite_files', general_config.get('overwrite_files', False))
	nfo_overwrite = overwrite_files or force_new_nfo
	
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
	
	# Handle existing files
	temp_exists = os.path.exists(destination_path)
	download_method = site_config['download'].get('method', 'curl')
	origin_to_use = urllib.parse.urlparse(iframe_url if iframe_url else original_url).scheme + "://" + urllib.parse.urlparse(iframe_url if iframe_url else original_url).netloc
	
	make_nfo = general_config.get('make_nfo', False)
	has_selectors = has_metadata_selectors(site_config)
	
	if make_nfo and has_selectors:
		if destination_config['type'] == 'smb':
			smb_nfo_path = os.path.join(destination_config['path'], f"{file_name.rsplit('.', 1)[0]}.nfo")
			temp_nfo_path = os.path.join(temp_dir, f"{file_name.rsplit('.', 1)[0]}.nfo")
			nfo_exists = file_exists_on_smb(destination_config, smb_nfo_path)
			if nfo_overwrite or not nfo_exists:
				logger.debug(f"Calling generate_nfo_file for {destination_path} with metadata: {data}")
				generate_nfo_file(destination_path, data)
				if os.path.exists(temp_nfo_path):
					upload_to_smb(temp_nfo_path, smb_nfo_path, destination_config, nfo_overwrite)
					os.remove(temp_nfo_path)
					if nfo_exists:
						logger.info(f"Overwriting existing NFO at {smb_nfo_path}")
					else:
						logger.info(f"Uploaded new NFO to {smb_nfo_path}")
			else:
				logger.debug(f"NFO file already exists at SMB destination: {smb_nfo_path}, skipping generation")
		else:
			nfo_path = f"{destination_path.rsplit('.', 1)[0]}.nfo"
			nfo_exists = os.path.exists(nfo_path)
			if nfo_overwrite or not nfo_exists:
				logger.debug(f"Calling generate_nfo_file for {destination_path} with metadata: {data}")
				generate_nfo_file(destination_path, data)
				if nfo_exists:
					logger.info(f"Overwriting existing NFO at {nfo_path}")
			else:
				logger.debug(f"NFO file already exists at local destination: {nfo_path}, skipping generation")
	
	if video_exists and not overwrite_files:
		logger.info(f"File '{file_name}' exists at destination. Skipping download.")
		return
	elif not overwrite_files and temp_exists:
		logger.debug(f"File '{file_name}' found in temp folder: {destination_path}")
		video_info = get_video_metadata(destination_path)
		if video_info:
			logger.info(f"Valid video found in temp folder: {file_name}. Skipping download and proceeding to upload.")
			try:
				if destination_config['type'] == 'smb':
					upload_to_smb(destination_path, smb_destination_path, destination_config, overwrite_files)
					os.remove(destination_path)
				elif destination_config['type'] == 'local':
					apply_permissions(destination_path, destination_config)
			except Exception as e:
				logger.error(f"Post-download processing failed for existing temp file: {e}")
			return
		else:
			logger.warning(f"Invalid or corrupt file in temp folder: {destination_path}. Deleting and re-downloading.")
			os.remove(destination_path)
	
	# Proceed with download
	logger.info(f"Downloading: {file_name}")
	if download_file(video_url, destination_path, download_method, general_config, site_config, headers=headers, metadata=data, origin=origin_to_use, overwrite=overwrite_files):
		try:
			if destination_config['type'] == 'smb':
				upload_to_smb(destination_path, smb_destination_path, destination_config, overwrite_files)
				os.remove(destination_path)
			elif destination_config['type'] == 'local':
				apply_permissions(destination_path, destination_config)
		except Exception as e:
			logger.error(f"Post-download processing failed: {e}")
	else:
		logger.error(f"Download failed; skipping post-processing for {file_name}")
	
	time.sleep(general_config['sleep']['between_videos'])


def pierce_iframe(driver, url, site_config):
	"""
	Attempts to pierce into an iframe if specified in site_config.
	Returns the final URL loaded (iframe src or original URL).
	"""
	iframe_config = site_config.get('iframe', {})
	if not iframe_config.get('enabled', False):
		logger.debug("Iframe piercing disabled in site_config.")
		driver.get(url)
		return url
	
	logger.debug(f"Attempting iframe piercing for: {url}")
	driver.get(url)
	time.sleep(random.uniform(1, 2))  # Initial page load
	
	try:
		iframe_selector = iframe_config.get('selector', 'iframe')  # Default to 'iframe' tag
		iframe = driver.find_element(By.CSS_SELECTOR, iframe_selector)
		iframe_url = iframe.get_attribute("src")
		if iframe_url:
			logger.info(f"Found iframe with src: {iframe_url}")
			driver.get(iframe_url)
			time.sleep(random.uniform(1, 2))  # Allow iframe to load
			return iframe_url
		else:
			logger.debug("Iframe found but no src attribute.")
			return url
	except Exception as e:
		logger.debug(f"No iframe found or error piercing: {e}")
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
	
	logger.debug("Waiting for network requests...")
	time.sleep(5)  # Adjustable via site_config if needed
	
	logs = driver.get_log("performance")
	m3u8_urls = []
	logger.debug(f"Analyzing {len(logs)} performance logs")
	for log in logs:
		try:
			message = json.loads(log["message"])["message"]
			if "Network.responseReceived" in message["method"]:
				request_url = message["params"]["response"]["url"]
				# logger.debug(f"Network response: {request_url}")
				if ".m3u8" in request_url:
					m3u8_urls.append(request_url)
					logger.info(f"Found M3U8 URL: {request_url}")
		except KeyError:
			# logger.debug("Skipping log entry due to missing keys")
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
		logger.debug(f"Extracting field: '{field}'")
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
				logger.debug(f"Text for '{field}' is None; defaulting to empty string")
				value = ''
		
		logger.debug(f"Initial value for '{field}': {value}")
		
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
					elif 'first' in step and step['first']:
						if isinstance(value, list):
							value = value[0] if value else ''
							logger.debug(f"Applied 'first' for '{field}': selected {value}")
						else:
							logger.debug(f"Skipping 'first' for '{field}' as value is not a list: {value}")
			elif isinstance(value, list) and field not in ['tags', 'actors', 'studios']:
				# Default to first value for lists without postProcess, except multi-value fields
				value = value[0] if value else ''
				logger.debug(f"No postProcess for '{field}' with multiple values; defaulted to first: {value}")
		
		data[field] = value if value or isinstance(value, list) else ''
		logger.debug(f"Final value for '{field}': {data[field]}")
	
	return data

def process_list_page(url, site_config, general_config, current_page=1, mode=None, identifier=None, overwrite_files=False, headers=None, force_new_nfo=False):
	use_selenium = site_config.get('use_selenium', False)
	driver = get_selenium_driver(general_config) if use_selenium else None
	soup = fetch_page(url, general_config['user_agents'], headers if headers else {}, use_selenium, driver)
	if soup is None:
		logger.error(f"Failed to fetch page: {url}")
		return None, None
	
	list_scraper = site_config['scrapers']['list_scraper']
	base_url = site_config['base_url']
	container_selector = list_scraper['video_container']['selector']
	
	container = None
	if isinstance(container_selector, list):
		logger.debug(f"Searching for container with selector list: {container_selector}")
		for selector in container_selector:
			container = soup.select_one(selector)
			if container:
				logger.debug(f"Found container with selector '{selector}': {container.name}[class={container.get('class', [])}]")
				break
		if not container:
			logger.error(f"Could not find video container at {url} with any selector in {container_selector}")
			logger.debug(f"Page HTML excerpt: {str(soup.body)[:500] if soup.body else str(soup)[:500]}...")
			return None, None
	else:
		logger.debug(f"Searching for container with selector: '{container_selector}'")
		container = soup.select_one(container_selector)
		if not container:
			logger.error(f"Could not find video container at {url} with selector '{container_selector}'")
			logger.debug(f"Page HTML excerpt: {str(soup.body)[:500] if soup.body else str(soup)[:500]}...")
			return None, None
		logger.debug(f"Found container: {container.name}[class={container.get('class', [])}]")
	
	item_selector = list_scraper['video_item']['selector']
	logger.debug(f"Searching for video items with selector: '{item_selector}'")
	video_elements = container.select(item_selector)
	logger.debug(f"Found {len(video_elements)} video items")
	if not video_elements:
		logger.info(f"No videos found on page {current_page} with selector '{item_selector}'")
		logger.debug(f"Container HTML excerpt: {str(container)[:500]}...")
		return None, None
	
	for video_element in video_elements:
		logger.debug(f"Processing video element: {video_element.get('data-video-id', 'no data-video-id')}")
		video_data = extract_data(video_element, list_scraper['video_item']['fields'], driver, site_config)
		if 'url' in video_data:
			video_url = video_data['url']
			if not video_url.startswith(('http://', 'https://')):
				video_url = f"http:{video_url}" if video_url.startswith('//') else urllib.parse.urljoin(base_url, video_url)
		elif 'video_key' in video_data:
			# Pass mode='video' to construct_url for video-specific encoding rules
			video_url = construct_url(base_url, site_config['modes']['video']['url_pattern'], site_config, mode='video', video_id=video_data['video_key'])
		else:
			logger.warning("Unable to construct video URL")
			continue
		video_title = video_data.get('title', '').strip() or video_element.text.strip()
		logger.info(f"Found video: {video_title} - {video_url}")
		process_video_page(video_url, site_config, general_config, overwrite_files, headers, force_new_nfo)
	
	# Pagination logic
	if mode not in site_config['modes']:
		logger.warning(f"No pagination for mode '{mode}' as it’s not defined in site_config['modes']")
		return None, None
	
	mode_config = site_config['modes'][mode]
	scraper_pagination = list_scraper.get('pagination', {})
	url_pattern_pages = mode_config.get('url_pattern_pages')
	max_pages = mode_config.get('max_pages', scraper_pagination.get('max_pages', float('inf')))
	
	if current_page >= max_pages:
		logger.warning(f"Stopping pagination: current_page={current_page} >= max_pages={max_pages}")
		return None, None
	
	next_url = None
	if url_pattern_pages:
		# Pass mode to construct_url for mode-specific encoding rules
		next_url = construct_url(
			base_url,
			url_pattern_pages,
			site_config,
			mode=mode,
			**{mode: identifier, 'page': current_page + 1}
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
		return next_url, current_page + 1
	logger.warning("No next page URL generated; stopping pagination")
	return None, None

	
def should_ignore_video(data, ignored_terms):
	if not ignored_terms:
		logger.debug(f"No ignored terms...")
		return False
	logger.debug(f"Applying ignored terms subroutine...")
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
					logger.info(f"Ignoring video due to term '{term}' in {field}: '{value}'")
					return True
		elif isinstance(value, list):
			for item in value:
				item_lower = item.lower()
				for term, term_pattern, encoded_pattern in zip(ignored_terms_lower, term_patterns, encoded_patterns):
					if term_pattern.search(item_lower) or encoded_pattern.search(item_lower):
						logger.info(f"Ignoring video due to term '{term}' in {field}: '{item}'")
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
			logger.info(f"Uploaded to SMB: {smb_path}")
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
			logger.info(
				f"Download completed: {os.path.basename(destination_path)}\n"
				f"  Size: {video_info['size_str']}\n"
				f"  Duration: {video_info['duration']}\n"
				f"  Resolution: {video_info['resolution']}\n"
				f"  Bitrate: {video_info['bitrate']}"
			)
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
						pbar.total = pbar.n  # Grow total with downloaded amount
	
	if os.path.exists(destination_path):
		final_size = os.path.getsize(destination_path)
		logger.info(f"Download completed: {os.path.basename(destination_path)}, Size: {final_size / 1024 / 1024:.2f} MB")
	else:
		logger.error("Download failed: File not found")
		return False
	
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
	
	logger.info("curl download completed successfully")
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
	logger.info("wget download completed successfully")
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
	logger.info("yt-dlp download completed successfully")
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
	else:
		logger.debug("No cookie provided for fetch")
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
	logger.info("FFmpeg download completed successfully")
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

def process_fallback_download(url, general_config, overwrite_files=False):
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
			if not overwrite_files and file_exists_on_smb(destination_config, smb_destination_path):
				logger.info(f"File '{downloaded_file}' exists on SMB. Skipping.")
				continue
			upload_to_smb(source_path, smb_destination_path, destination_config)
		elif destination_config['type'] == 'local':
			final_path = os.path.join(destination_config['path'], downloaded_file)
			if not overwrite_files and os.path.exists(final_path):
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
				logger.debug(f"Matched URL '{url}' to mode '{mode}' with exact pattern '{pattern}'")
				return mode, config['scraper']
			continue
		
		regex_pattern = '^/' + '/'.join(regex_parts)
		if placeholder_found and len(path_segments) > len(pattern_segments):
			regex_pattern += r'(?:/.*)?'
		regex_pattern += '$'
		
		if re.match(regex_pattern, effective_path):
			logger.debug(f"Matched URL '{url}' to mode '{mode}' with pattern '{pattern}'")
			return mode, config['scraper']
	
	logger.debug(f"No mode matched for URL: {url}")
	return None, None

def has_metadata_selectors(site_config):
	"""
	Check if the site config has selectors for metadata fields beyond title and download_url.
	"""
	video_scraper = site_config.get('scrapers', {}).get('video_scraper', {})
	metadata_fields = {'tags', 'actors', 'studio', 'studios', 'date', 'code', 'image'}
	return any(field in video_scraper for field in metadata_fields)


def custom_title_case(text, uppercase_list=None, preserve_mixed_case=False):
	if not text:
		return text
	uppercase_list = uppercase_list or []  # Ensure it’s never None
	if preserve_mixed_case and re.search(r'[a-z][A-Z]|[A-Z][a-z]', text) and text not in uppercase_list:
		return text
	upper_set = set(term.upper() for term in uppercase_list)
	words = text.split()
	if not words:
		word_upper = text.upper()
		return word_upper if word_upper in upper_set else text.title()
	if not preserve_mixed_case or len(words) > 1:
		result = []
		for word in words:
			word_upper = word.upper()
			if word_upper in upper_set:
				result.append(word_upper)
			else:
				result.append(word.title())
		final_text = ' '.join(result)
	else:
		final_text = text.title()
		for term in uppercase_list:
			pattern = re.compile(r'\b' + re.escape(term) + r'\b', re.IGNORECASE)
			final_text = pattern.sub(term.upper(), final_text)
	return final_text
	

def main():
	parser = argparse.ArgumentParser(
		description="Smutscrape: Scrape and download adult content from various sites with metadata saved in .nfo files."
	)
	parser.add_argument("args", nargs="*", help="Site code and mode followed by a query (e.g., '9v search \"big boobs\"'), or a direct URL.")
	parser.add_argument("--debug", action="store_true", help="Enable detailed debug logging.")
	parser.add_argument("--overwrite_files", action="store_true", help="Overwrite existing video files.")
	parser.add_argument("--force_new_nfo", action="store_true", help="Regenerate .nfo files even if they exist.")
	parser.add_argument("--start_on_page", type=int, default=1, help="Start scraping from this page number.")
	args = parser.parse_args()
	
	log_level = "DEBUG" if args.debug else "INFO"
	logger.remove()
	logger.add(sys.stderr, level=log_level)
	general_config = load_config(os.path.join(SCRIPT_DIR, "config.yaml"))

	if not args.args:  # No arguments provided
		logger.info("Smutscrape: A tool to scrape and download adult videos with metadata.")
		logger.info("Usage: scrape {site_code} {mode} {query}  OR  scrape {url}")
		logger.info("Examples:")
		logger.info("  scrape ph pornstar \"Massy Sweet\"  # Scrape a pornstar's videos")
		logger.info("  scrape https://motherless.com/2ABC9F3  # Scrape a specific video")
		
		logger.info("Supported Sites and Modes (loaded from configs):")
		config_dir = os.path.join(SCRIPT_DIR, "configs")  # Adjust if CONFIG_DIR differs
		if not os.path.exists(config_dir):
			logger.error(f"Configs directory '{config_dir}' not found.")
			sys.exit(1)
		
		logger.info("  {:<8} {:<30} {}".format("Code", "Site", "Modes"))  # Header
		supported_sites = []
		for site_config_file in os.listdir(config_dir):
			if site_config_file.endswith(".yaml"):
				site_code = site_config_file[:-5]
				try:
					site_config = load_site_config(site_code)
					site_name = site_config.get("name", site_code)
					modes = ", ".join(site_config.get("modes", {}).keys())
					supported_sites.append((site_code, site_name, modes))
				except Exception as e:
					logger.warning(f"Failed to load config for '{site_code}': {e}")
		
		if supported_sites:
			for site_code, site_name, modes in sorted(supported_sites):
				logger.info("  {:<8} {:<30} {}".format(site_code, site_name, modes))
		else:
			logger.info("  No valid site configs found in 'configs' folder.")
		
		logger.info("")
		logger.info("Run 'scrape --help' for more options.")
		sys.exit(0)

	try:
		if len(args.args) == 1 and args.args[0].startswith(("http://", "https://")):
			url = args.args[0]
			logger.debug(f"Looking for config matches for {url}...")
			matched_site_config = None
			for site_config_file in os.listdir(CONFIG_DIR):
				if site_config_file.endswith(".yaml"):
					site_config = load_site_config(site_config_file[:-5])
					parsed_url = urlparse(url)
					url_netloc = parsed_url.netloc.lower().replace("www.", "")
					parsed_base = urlparse(site_config["base_url"])
					base_netloc = parsed_base.netloc.lower().replace("www.", "")
					if url_netloc == base_netloc:
						matched_site_config = site_config
						break
			
			if matched_site_config:
				headers = general_config.get("headers", {}).copy()
				headers["User-Agent"] = random.choice(general_config["user_agents"])
				mode, scraper = match_url_to_mode(url, matched_site_config)
				if mode:
					logger.info(f"Matched URL to mode '{mode}' with scraper '{scraper}'")
					if mode == "video":
						process_video_page(url, matched_site_config, general_config, args.overwrite_files, headers, args.force_new_nfo)
					else:
						identifier = url.split("/")[-1].split(".")[0]
						current_page = args.start_on_page
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
						while url:
							next_page, new_page_number = process_list_page(
								url, matched_site_config, general_config, current_page,
								mode, identifier, args.overwrite_files, headers, args.force_new_nfo
							)
							if next_page is None:
								break
							url = next_page
							current_page = new_page_number
							time.sleep(general_config["sleep"]["between_pages"])
				else:
					logger.warning("URL didn't match any mode; assuming video page.")
					process_video_page(url, matched_site_config, general_config, args.overwrite_files, headers, args.force_new_nfo)
			else:
				process_fallback_download(url, general_config, args.overwrite_files)
		
		elif len(args.args) >= 3:
			site, mode, identifier = args.args[0], args.args[1], " ".join(args.args[2:])
			site_config = load_site_config(site)
			headers = general_config.get("headers", {})
			handle_vpn(general_config, "start")
			if mode not in site_config["modes"]:
				logger.error(f"Unsupported mode '{mode}' for site '{site}'")
				sys.exit(1)
			mode_config = site_config["modes"][mode]
			current_page = args.start_on_page
			if current_page > 1 and mode_config.get("url_pattern_pages"):
				url = construct_url(
					site_config["base_url"],
					mode_config["url_pattern_pages"],
					site_config,
					mode=mode,
					**{mode: identifier, "page": current_page}
				)
				logger.info(f"Starting at custom page {current_page}: {url}")
			else:
				url = construct_url(
					site_config["base_url"],
					mode_config["url_pattern"],
					site_config,
					mode=mode,
					**{mode: identifier} if mode != "video" else {"video_id": identifier}
				)
				if current_page > 1:
					logger.warning(f"Starting page {current_page} requested, but no 'url_pattern_pages' defined; starting at page 1")
			if mode == "video":
				process_video_page(url, site_config, general_config, args.overwrite_files, headers, args.force_new_nfo)
			else:
				while url:
					next_page, new_page_number = process_list_page(
						url, site_config, general_config, current_page, mode,
						identifier, args.overwrite_files, headers, args.force_new_nfo 
					)
					if next_page is None:
						break
					url = next_page
					current_page = new_page_number
					time.sleep(general_config["sleep"]["between_pages"])
		else:
			logger.error("Invalid arguments. Provide site, mode, and identifier, or a URL.")
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
		logger.info("Scraping completed.")

if __name__ == "__main__":
	main()
