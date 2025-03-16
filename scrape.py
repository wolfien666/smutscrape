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
import uuid
import tempfile
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

def construct_url(base_url, pattern, site_config, **kwargs):
	encoding_rules = site_config.get('url_encoding_rules', {})
	encoded_kwargs = {}
	logger.debug(f"Constructing URL...")
	for k, v in kwargs.items():
		if isinstance(v, str):
			encoded_v = v
			for original, replacement in encoding_rules.items():
				encoded_v = encoded_v.replace(original, replacement)
			encoded_kwargs[k] = encoded_v
		else:
			encoded_kwargs[k] = v
	path = pattern.format(**encoded_kwargs)
	return urllib.parse.urljoin(base_url, path)


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
	original_url = url  # Preserve the original URL for metadata and NFO
	
	# Handle M3U8 mode with iframe piercing
	if site_config.get('m3u8_mode', False) and driver:
		video_scraper = site_config['scrapers']['video_scraper']
		iframe_config = None
		for field, config in video_scraper.items():
			if isinstance(config, dict) and 'iframe' in config:
				iframe_config = {'enabled': True, 'selector': config['iframe']}
				break
		if iframe_config:
			logger.debug(f"Piercing iframe '{iframe_config['selector']}' for M3U8 extraction")
			driver.get(original_url)  # Load original page first
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
						# Fetch original page for metadata
						soup = fetch_page(original_url, general_config['user_agents'], headers, use_selenium, driver)
						data = extract_data(soup, site_config['scrapers']['video_scraper'], driver, site_config) if soup else {'title': original_url.split('/')[-2]}  # Use slug before trailing slash
					else:
						logger.error("Failed to extract M3U8 URL; falling back to page scrape.")
						video_url = None
				else:
					logger.debug("Iframe found but no src attribute.")
					video_url = None
			except Exception as e:
				logger.debug(f"No iframe found or error piercing: {e}")
				video_url = None
			# Always fetch original page for metadata, even if iframe fails
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
	data['URL'] = original_url  # Use original URL for NFO, not iframe or M3U8
	
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
		# Create a dedicated temporary directory for downloads using tempfile
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
	
	# NFO generation and upload logic
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
	
	# Download logic
	if video_exists and not overwrite_files:
		logger.info(f"File '{file_name}' exists. Skipping download.")
	else:
		download_method = site_config['download'].get('method', 'curl')
		logger.info(f"Downloading: {file_name}")
		if download_file(video_url, destination_path, download_method, general_config, site_config, headers=headers, metadata=data):
			if destination_config['type'] == 'smb':
				upload_to_smb(destination_path, smb_destination_path, destination_config, overwrite_files)
				os.remove(destination_path)
			elif destination_config['type'] == 'local':
				apply_permissions(destination_path, destination_config)
	
	time.sleep(general_config['sleep']['between_videos'])


def download_with_ffmpeg(url, destination_path, general_config, headers=None):
	headers = headers or {}
	ua = headers.get('User-Agent', random.choice(general_config['user_agents']))
	if "Headless" in ua:
		ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
	
	# Step 1: Fetch the .m3u8 file with requests to mimic browser context
	fetch_headers = {
		"User-Agent": ua,
		"Referer": headers.get("Referer", ""),
		"Accept": "application/vnd.apple.mpegurl",
		"Origin": "https://bestwish.lol",
	}
	if "Cookie" in headers and headers["Cookie"]:
		fetch_headers["Cookie"] = headers["Cookie"]
	
	logger.debug(f"Fetching M3U8 with headers: {fetch_headers}")
	try:
		scraper = cloudscraper.create_scraper()  # Handles potential Cloudflare checks
		response = scraper.get(url, headers=fetch_headers, timeout=30)
		response.raise_for_status()
		m3u8_content = response.text
		logger.debug(f"Fetched M3U8 content: {m3u8_content[:100]}...")
	except requests.exceptions.RequestException as e:
		logger.error(f"Failed to fetch M3U8: {e}")
		return False
	
	# Step 2: Write M3U8 to a temp file and resolve absolute segment URLs
	temp_m3u8_path = destination_path + ".m3u8"
	with open(temp_m3u8_path, "w", encoding="utf-8") as f:
		# Rewrite relative segment URLs to absolute
		base_url = url.rsplit('/', 1)[0] + "/"
		for line in m3u8_content.splitlines():
			if line and not line.startswith("#"):
				if not line.startswith("http"):
					line = urllib.parse.urljoin(base_url, line)
				f.write(line + "\n")
			else:
				f.write(line + "\n")
	
	# Step 3: Use ffmpeg with the local M3U8 file and protocol whitelist, no headers
	command = [
		"ffmpeg",
		"-protocol_whitelist", "file,http,https,tcp,tls,crypto",
		"-i", temp_m3u8_path,
		"-c", "copy",
		"-bsf:a", "aac_adtstoasc",
		destination_path
	]
	
	logger.debug(f"Executing FFmpeg command: {' '.join(shlex.quote(arg) for arg in command)}")
	process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
	pbar = tqdm(total=100, unit='%', desc="Downloading (FFmpeg)")
	last_percent = 0
	try:
		for line in process.stderr:
			# logger.debug(f"FFmpeg output: {line.strip()}")
			if 'frame=' in line or 'size=' in line:
				if last_percent < 90:
					last_percent += random.uniform(1, 5)
					pbar.update(min(last_percent, 100) - pbar.n)
		pbar.n = 100
	except KeyboardInterrupt:
		process.terminate()
		pbar.close()
		os.remove(temp_m3u8_path)  # Cleanup on interrupt
		return False
	pbar.close()
	return_code = process.wait()
	if os.path.exists(temp_m3u8_path):
		os.remove(temp_m3u8_path)  # Cleanup after completion
	
	if return_code != 0:
		logger.error(f"FFmpeg failed with return code {return_code}")
	else:
		logger.info("FFmpeg download completed successfully")
	return return_code == 0


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
			# Handle attribute-based extraction (e.g., alt)
			values = [element.get(config['attribute']) for element in elements if element.get(config['attribute'])]
			value = values if len(values) > 1 or field in ['tags', 'actors', 'studios'] else values[0] if values else ''
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
			# Extract all values, strip, and filter out empty ones
			values = [element.text.strip() for element in elements if hasattr(element, 'text') and element.text and element.text.strip()]
			# Normalize and deduplicate
			normalized_values = {v.lower() for v in values if v}
			value = [v for v in values if v.lower() in normalized_values]
			# Remove duplicates while preserving order
			seen = set()
			value = [v for v in value if not (v.lower() in seen or seen.add(v.lower()))]
		
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
		
		data[field] = value if value or isinstance(value, list) else ''
		logger.debug(f"Final value for '{field}': {data[field]}")
	
	return data

def process_list_page(url, site_config, general_config, current_page=1, mode=None, identifier=None, overwrite_files=False, headers=None, force_new_nfo=False):
	use_selenium = site_config.get('use_selenium', False)
	driver = get_selenium_driver(general_config) if use_selenium else None
	soup = fetch_page(url, general_config['user_agents'], headers if headers else {}, use_selenium, driver)
	if soup is None:
		return None, None
	
	list_scraper = site_config['scrapers']['list_scraper']
	base_url = site_config['base_url']
	container = None
	for selector in list_scraper['video_container']['selector']:
		container = soup.select_one(selector)
		if container:
			break
	if not container:
		logger.error(f"Could not find video container at {url}")
		return None, None
	
	video_elements = container.select(list_scraper['video_item']['selector'])
	if not video_elements:
		logger.info(f"No videos found on page {current_page}")
		return None, None
	
	for video_element in video_elements:
		video_data = extract_data(video_element, list_scraper['video_item']['fields'], driver, site_config)
		if 'url' in video_data:
			video_url = video_data['url']
			if not video_url.startswith(('http://', 'https://')):
				video_url = f"http:{video_url}" if video_url.startswith('//') else urllib.parse.urljoin(base_url, video_url)
		elif 'video_key' in video_data:
			video_url = construct_url(base_url, site_config['modes']['video']['url_pattern'], site_config, video_id=video_data['video_key'])
		else:
			logger.warning("Unable to construct video URL")
			continue
		video_title = video_data.get('title', '') or video_element.text.strip()
		logger.info(f"Found video: {video_title} - {video_url}")
		# def process_video_page(url, site_config, general_config, overwrite_files=False, headers=None, force_new_nfo=False):
		process_video_page(video_url, site_config, general_config, overwrite_files, headers, force_new_nfo)
	
	# Determine pagination method
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
		# URL pattern-based pagination
		if scraper_pagination:
			logger.warning(f"Both 'url_pattern_pages' and 'list_scraper.pagination' are defined; prioritizing 'url_pattern_pages'")
		encoded_identifier = identifier
		for original, replacement in site_config.get('url_encoding_rules', {}).items():
			encoded_identifier = encoded_identifier.replace(original, replacement)
		next_url = construct_url(
			base_url,
			url_pattern_pages,
			site_config,
			**{mode: encoded_identifier, 'page': current_page + 1}
		)
		logger.info(f"Generated next page URL (pattern-based): {next_url}")
	elif scraper_pagination:
		# Scraper-based pagination
		if 'subsequent_pages' in scraper_pagination:
			encoded_identifier = identifier
			for original, replacement in site_config.get('url_encoding_rules', {}).items():
				encoded_identifier = encoded_identifier.replace(original, replacement)
			url_pattern = mode_config['url_pattern']
			next_url = scraper_pagination['subsequent_pages'].format(
				url_pattern=url_pattern, page=current_page + 1, search=encoded_identifier
			)
			next_url = urllib.parse.urljoin(base_url, next_url)
			logger.info(f"Generated next page URL (subsequent_pages): {next_url}")
		elif 'next_page' in scraper_pagination:
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
			with open(local_path, 'rb') as file:
				with tqdm(total=os.path.getsize(local_path), unit='B', unit_scale=True, desc="Uploading to SMB") as pbar:
					conn.storeFile(destination_config['share'], smb_path, file)
					pbar.update(os.path.getsize(local_path))
			logger.info(f"Uploaded to SMB: {smb_path}")
		else:
			logger.error("Failed to connect to SMB share.")
	except Exception as e:
		logger.error(f"Error uploading to SMB: {e}")
	finally:
		conn.close()

def download_file(url, destination_path, method, general_config, site_config, headers=None, metadata=None):
	if not url:
		logger.error("Invalid or empty URL")
		return False
	os.makedirs(os.path.dirname(destination_path), exist_ok=True)
	if url.startswith('//'):
		url = 'http:' + url
	
	use_headers = headers and any(k in headers for k in ["Cookie"])
	success = False
	
	if method == 'curl':
		if use_headers:
			curl_headers = (
				f"-A \"{headers.get('User-Agent', random.choice(general_config['user_agents']))}\" "
				f"-H \"Referer: {headers.get('Referer', site_config.get('base_url', ''))}\" "
			)
			if "Cookie" in headers:
				curl_headers += f"-H \"Cookie: {headers['Cookie']}\" "
			command = f"curl -L -o \"{destination_path}\" {curl_headers} --retry 3 --max-time 600 \"{url}\""
		else:
			command = f"curl -L -o \"{destination_path}\" \"{url}\""
		logger.debug(f"Executing curl command: {command}")
		success = download_with_curl(command)
	elif method == 'wget':
		if use_headers:
			wget_headers = (
				f"--user-agent=\"{headers.get('User-Agent', random.choice(general_config['user_agents']))}\" "
				f"--referer=\"{headers.get('Referer', site_config.get('base_url', ''))}\" "
			)
			if "Cookie" in headers:
				wget_headers += f"--header=\"Cookie: {headers['Cookie']}\" "
			command = f"wget {wget_headers} --tries=3 --timeout=600 -O \"{destination_path}\" \"{url}\""
		else:
			command = f"wget -O \"{destination_path}\" \"{url}\""
		logger.debug(f"Executing wget command: {command}")
		success = download_with_wget(command)
	elif method == 'yt-dlp':
		user_agent = headers.get('User-Agent', random.choice(general_config['user_agents']) if general_config.get('user_agents') else "Mozilla/5.0")
		command = f"yt-dlp -o \"{destination_path}\" --user-agent \"{user_agent}\""
		if 'Image' in metadata:
			command += f" --embed-thumbnail --convert-thumbnails jpg"
			logger.debug(f"Embedding image as thumbnail: {metadata['Image']}")
		command += f" \"{url}\""
		logger.debug(f"Executing yt-dlp command: {command}")
		success = download_with_ytdlp(command)
	elif method == 'ffmpeg':
		success = download_with_ffmpeg(url, destination_path, general_config, headers)
	
	return success

def download_with_curl(command):
	process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
	pbar = tqdm(total=100, unit='%', desc="Downloading (curl)")
	last_percent = 0
	try:
		for line in process.stdout:
			# logger.debug(f"curl output: {line.strip()}")
			if '#' in line:  # curl’s progress bar
				percent = min(line.count('#'), 100)
				pbar.update(percent - last_percent)
				last_percent = percent
			elif "< Location:" in line:
				logger.info(f"curl redirect: {line.strip()}")
		pbar.n = 100
	except KeyboardInterrupt:
		process.terminate()
	pbar.close()
	return_code = process.wait()
	if return_code != 0:
		logger.error(f"curl failed with return code {return_code}")
	else:
		logger.info("curl download completed successfully")
	return return_code == 0
	
def download_with_wget(command):
	process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
	progress_regex = re.compile(r'(\d+)%\s+(\d+[KMG]?)')  # Matches "45% 123M"
	pbar = None
	try:
		for line in process.stdout:
			# logger.debug(f"wget output: {line.strip()}")
			match = progress_regex.search(line)
			if match:
				percent, size = match.groups()
				percent = int(percent)
				if pbar is None:
					pbar = tqdm(total=100, unit='%', desc="Downloading (wget)")
				pbar.update(percent - pbar.n)
			elif "Location:" in line:
				logger.info(f"wget redirect: {line.strip()}")
		if pbar:
			pbar.n = 100  # Ensure completion
	except KeyboardInterrupt:
		process.terminate()
		if pbar:
			pbar.close()
		return False
	if pbar:
		pbar.close()
	return_code = process.wait()
	if return_code != 0:
		logger.error(f"wget failed with return code {return_code}")
	else:
		logger.info("wget download completed successfully")
	return return_code == 0
		

def download_with_ytdlp(command):
	process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
	progress_regex = re.compile(r'\[download\]\s+(\d+\.\d+)% of ~?\s*(\d+\.\d+)(K|M|G)iB')
	total_size = None
	pbar = None
	try:
		for line in process.stdout:
			progress_match = progress_regex.search(line)
			if progress_match:
				percent, size, size_unit = progress_match.groups()
				if total_size is None:
					total_size = float(size) * {'K': 1024, 'M': 1024**2, 'G': 1024**3}[size_unit]
					pbar = tqdm(total=total_size, unit='B', unit_scale=True, desc="Downloading")
				progress = float(percent) * total_size / 100
				if pbar:
					pbar.update(progress - pbar.n)
			# logger.debug(line.strip())
	except KeyboardInterrupt:
		process.terminate()
		return False
	finally:
		if pbar:
			pbar.close()
	return process.wait() == 0

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
	parser = argparse.ArgumentParser(description='Video Scraper')
	parser.add_argument('args', nargs='+', help='Site identifier and mode, or direct URL')
	parser.add_argument('--debug', action='store_true', help='Enable debug logging')
	parser.add_argument('--overwrite_files', action='store_true', help='Overwrite existing files')
	parser.add_argument('--force_new_nfo', action='store_true', help='Force replacement of existing NFO files')
	parser.add_argument('--start_on_page', type=int, default=1, help='Starting page number for URL-based pagination')
	args = parser.parse_args()
	
	log_level = "DEBUG" if args.debug else "INFO"
	logger.remove()
	logger.add(sys.stderr, level=log_level)
	general_config = load_config(os.path.join(SCRIPT_DIR, 'config.yaml'))
	
	try:
		if len(args.args) == 1 and args.args[0].startswith(('http://', 'https://')):
			url = args.args[0]
			logger.debug(f"Looking for config matches for {url}...")
			matched_site_config = None
			for site_config_file in os.listdir(CONFIG_DIR):
				if site_config_file.endswith('.yaml'):
					site_config = load_site_config(site_config_file[:-5])
					# Normalize both URLs for comparison
					parsed_url = urlparse(url)
					url_netloc = parsed_url.netloc.lower()
					if url_netloc.startswith('www.'):
						url_netloc = url_netloc[4:]
					
					parsed_base = urlparse(site_config['base_url'])
					base_netloc = parsed_base.netloc.lower()
					if base_netloc.startswith('www.'):
						base_netloc = base_netloc[4:]
					
					if url_netloc == base_netloc:
						logger.debug(f"Found a match! {site_config['base_url']} matches {url}")
						matched_site_config = site_config
						break
					else:
						logger.debug(f"{url} does not match {site_config['base_url']} (netloc: {url_netloc} vs {base_netloc})")
			
			if matched_site_config:
				headers = general_config.get('headers', {}).copy()
				headers['User-Agent'] = random.choice(general_config['user_agents'])
				mode, scraper = match_url_to_mode(url, matched_site_config)
				if mode:
					logger.info(f"Matched URL to mode '{mode}' with scraper '{scraper}'")
					if mode == 'video':
						process_video_page(url, matched_site_config, general_config, args.overwrite_files, headers, args.force_new_nfo)
					else:
						identifier = url.split('/')[-1].split('.')[0]
						current_page = args.start_on_page
						mode_config = matched_site_config['modes'][mode]
						if current_page > 1 and mode_config.get('url_pattern_pages'):
							encoded_identifier = identifier
							logger.debug(f"Performing replacements on encoded_identifier...")
							for original, replacement in matched_site_config.get('url_encoding_rules', {}).items():
								encoded_identifier = encoded_identifier.replace(original, replacement)
							url = construct_url(
								matched_site_config['base_url'],
								mode_config['url_pattern_pages'],
								matched_site_config,
								**{mode: encoded_identifier, 'page': current_page}
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
							time.sleep(general_config['sleep']['between_pages'])
				else:
					logger.warning("URL didn't match any mode; assuming video page.")
					process_video_page(url, matched_site_config, general_config, args.overwrite_files, headers, args.force_new_nfo)
			else:
				process_fallback_download(url, general_config, args.overwrite_files)
	
		elif len(args.args) >= 3:
			site, mode, identifier = args.args[0], args.args[1], ' '.join(args.args[2:])
			site_config = load_site_config(site)
			headers = general_config.get('headers', {})
			handle_vpn(general_config, 'start')
			if mode not in site_config['modes']:
				logger.error(f"Unsupported mode '{mode}' for site '{site}'")
				sys.exit(1)
			mode_config = site_config['modes'][mode]
			current_page = args.start_on_page
			if current_page > 1 and mode_config.get('url_pattern_pages'):
				url = construct_url(
					site_config['base_url'],
					mode_config['url_pattern_pages'],
					site_config,
					**{mode: identifier, 'page': current_page}
				)
				logger.info(f"Starting at custom page {current_page}: {url}")
			else:
				url = construct_url(
					site_config['base_url'],
					mode_config['url_pattern'],
					site_config,
					**{mode: identifier} if mode != 'video' else {'video_id': identifier}
				)
				if current_page > 1:
					logger.warning(f"Starting page {current_page} requested, but no 'url_pattern_pages' defined; starting at page 1")
			if mode == 'video':
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
					time.sleep(general_config['sleep']['between_pages'])
		else:
			logger.error("Invalid arguments. Provide site, mode, and identifier, or a URL.")
			sys.exit(1)
	except KeyboardInterrupt:
		logger.warning("Interrupted by user.")
	except Exception as e:
		logger.error(f"Error: {e}")
	finally:
		if 'selenium_driver' in general_config and general_config['selenium_driver'] is not None:
			try:
				general_config['selenium_driver'].quit()
				logger.info("Selenium driver closed cleanly.")
			except Exception as e:
				logger.warning(f"Failed to close Selenium driver: {e}")
		logger.info("Scraping completed.")

if __name__ == "__main__":
	main()
