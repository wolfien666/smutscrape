#!/usr/bin/env python3

import argparse
import yaml
import requests
import cloudscraper
from bs4 import BeautifulSoup
import os
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
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

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
    for char in invalid_chars:
        title = title.replace(char, "")
    return title

def construct_filename(title, site_config, general_config):
    prefix = site_config.get('name_prefix', '')
    suffix = site_config.get('name_suffix', '')
    processed_title = process_title(title, general_config['file_naming']['invalid_chars'])
    return f"{prefix}{processed_title}{suffix}{general_config['file_naming']['extension']}"

def construct_url(base_url, pattern, site_config, **kwargs):
    encoding_rules = site_config.get('url_encoding_rules', {})
    encoded_kwargs = {}
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
    create_new = force_new or 'selenium_driver' not in general_config
    if not create_new:
        try:
            driver = general_config['selenium_driver']
            driver.current_url
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
        host = general_config['chromedriver']['host']
        port = general_config['chromedriver']['port']
        selenium_url = f"http://{host}:{port}/wd/hub"
        try:
            driver = webdriver.Remote(command_executor=selenium_url, options=chrome_options)
            general_config['selenium_driver'] = driver
            logger.info(f"Connected to Selenium at {selenium_url}")
        except Exception as e:
            logger.error(f"Failed to connect to Selenium at {selenium_url}: {e}")
            general_config['selenium_driver'] = None
    return general_config['selenium_driver']

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
            driver.get(url)
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

def extract_data(soup, selectors):
    data = {}
    for field, config in selectors.items():
        if isinstance(config, str):
            elements = soup.select(config)
        elif isinstance(config, dict):
            if 'selector' in config:
                elements = soup.select(config['selector'])
            elif 'attribute' in config:
                elements = [soup]
            else:
                elements = []
        if elements:
            if isinstance(config, dict) and 'attribute' in config:
                value = elements[0].get(config['attribute'])
            else:
                value = elements[0].text.strip()
            if isinstance(config, dict) and 'json_key' in config:
                try:
                    json_data = json.loads(value)
                    value = json_data.get(config['json_key'])
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse JSON for field {field}")
            if field in ['tags', 'genres', 'actors', 'producers']:
                value = [element.text.strip() for element in elements]
            data[field] = value
    return data

def process_list_page(url, site_config, general_config, current_page=1, mode=None, identifier=None, overwrite_files=False, headers=None):
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
        video_data = extract_data(video_element, list_scraper['video_item']['fields'])
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
        process_video_page(video_url, site_config, general_config, overwrite_files, headers)
    
    pagination_config = list_scraper.get('pagination', {})
    max_pages = pagination_config.get('max_pages', float('inf'))
    if current_page < max_pages:
        if mode in site_config['modes']:
            encoded_identifier = identifier
            for original, replacement in site_config.get('url_encoding_rules', {}).items():
                encoded_identifier = encoded_identifier.replace(original, replacement)
            url_pattern = site_config['modes'][mode]['url_pattern'].format(**{mode: encoded_identifier})
        else:
            url_pattern = url
        if 'subsequent_pages' in pagination_config:
            next_url = pagination_config['subsequent_pages'].format(url_pattern=url_pattern, page=current_page + 1, search=encoded_identifier)
        else:
            next_page = soup.select_one(pagination_config.get('next_page', {}).get('selector', ''))
            next_url = next_page.get(pagination_config.get('next_page', {}).get('attribute', '')) if next_page else None
        if next_url:
            if not next_url.startswith(('http://', 'https://')):
                next_url = urllib.parse.urljoin(base_url, next_url)
            return next_url, current_page + 1
    return None, None

def should_ignore_video(data, ignored_terms):
    for term in ignored_terms:
        term_lower = term.lower()
        url_encoded_term = term.lower().replace(' ', '-')
        for field, value in data.items():
            if isinstance(value, str):
                words = value.lower().split()
                if term_lower in words or url_encoded_term in words:
                    logger.info(f"Ignoring video due to term '{term}' in {field}")
                    return True
            elif isinstance(value, list):
                for item in value:
                    words = item.lower().split()
                    if term_lower in words or url_encoded_term in words:
                        logger.info(f"Ignoring video due to term '{term}' in {field}")
                        return True
    return False

def process_video_page(url, site_config, general_config, overwrite_files=False, headers=None):
    global last_vpn_action_time
    vpn_config = general_config.get('vpn', {})
    if vpn_config.get('enabled', False):
        current_time = time.time()
        if current_time - last_vpn_action_time > vpn_config.get('new_node_time', 300):
            handle_vpn(general_config, 'new_node')
    
    logger.info(f"Processing video page: {url}")
    use_selenium = site_config.get('use_selenium', False)
    driver = get_selenium_driver(general_config) if use_selenium else None
    soup = fetch_page(url, general_config['user_agents'], headers if headers else {}, use_selenium, driver)
    if soup is None and use_selenium:
        logger.warning("Selenium failed; retrying with requests")
        soup = fetch_page(url, general_config['user_agents'], headers if headers else {}, False, None)
    if soup is None:
        logger.error(f"Failed to fetch video page: {url}")
        return
    
    data = extract_data(soup, site_config['scrapers']['video_scraper'])
    if should_ignore_video(data, general_config['ignored']):
        logger.info(f"Ignoring video: {data.get('title', url)}")
        return

    video_url = data.get('download_url', url)
    file_name = construct_filename(data.get('title', 'Untitled'), site_config, general_config)
    destination_config = general_config['download_destinations'][0]
    no_overwrite = site_config.get('no_overwrite', False)
    
    if destination_config['type'] == 'smb':
        smb_destination_path = os.path.join(destination_config['path'], file_name)
        if no_overwrite and file_exists_on_smb(destination_config, smb_destination_path):
            logger.info(f"File '{file_name}' exists on SMB share. Skipping.")
            return
        temp_dir = os.path.join(os.getcwd(), 'temp_downloads')
        os.makedirs(temp_dir, exist_ok=True)
        destination_path = os.path.join(temp_dir, file_name)
    else:
        destination_path = os.path.join(destination_config['path'], file_name)
        if no_overwrite and os.path.exists(destination_path):
            logger.info(f"File '{file_name}' exists locally. Skipping.")
            return
    
    download_method = site_config['download'].get('method', 'yt-dlp')
    logger.info(f"Downloading: {file_name}")
    if download_file(video_url, destination_path, download_method, general_config):
        if destination_config['type'] == 'smb':
            upload_to_smb(destination_path, smb_destination_path, destination_config, no_overwrite)
            os.remove(destination_path)
        elif destination_config['type'] == 'local':
            apply_permissions(destination_path, destination_config)
    time.sleep(general_config['sleep']['between_videos'])

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

def upload_to_smb(local_path, smb_path, destination_config, no_overwrite=False):
    conn = SMBConnection(destination_config['username'], destination_config['password'], "videoscraper", destination_config['server'])
    try:
        if conn.connect(destination_config['server'], 445):
            if no_overwrite and file_exists_on_smb(destination_config, smb_path):
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

def download_file(url, destination_path, method, general_config):
    if not url:
        logger.error("Invalid or empty URL")
        return False
    os.makedirs(os.path.dirname(destination_path), exist_ok=True)
    if url.startswith('//'):
        url = 'http:' + url
    user_agent = random.choice(general_config['user_agents']) if general_config.get('user_agents') else "Mozilla/5.0"
    
    if method == 'curl':
        command = f"curl -# -o \"{destination_path}\" -A \"{user_agent}\" \"{url}\""
        return download_with_curl_wget(command)
    elif method == 'wget':
        command = f"wget -O \"{destination_path}\" --user-agent=\"{user_agent}\" --progress=bar:force \"{url}\""
        return download_with_curl_wget(command)
    elif method == 'yt-dlp':
        command = f"yt-dlp -o \"{destination_path}\" --user-agent \"{user_agent}\" \"{url}\""
        return download_with_ytdlp(command)
    else:
        logger.error(f"Unsupported download method: {method}")
        return False

def download_with_curl_wget(command):
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    pbar = tqdm(total=100, unit='%', desc="Downloading")
    last_percent = 0
    try:
        for line in process.stdout:
            if 'curl' in command and '#' in line:
                percent = min(line.count('#'), 100)
                pbar.update(percent - last_percent)
                last_percent = percent
            elif 'wget' in command and '%' in line:
                try:
                    percent = min(int(line.split('%')[0].split()[-1]), 100)
                    pbar.update(percent - last_percent)
                    last_percent = percent
                except ValueError:
                    pass
            logger.debug(line.strip())
    except KeyboardInterrupt:
        process.terminate()
        pbar.close()
        return False
    pbar.close()
    return process.wait() == 0

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
            logger.debug(line.strip())
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
    base_url = site_config['base_url'].rstrip('/')
    for mode, config in site_config['modes'].items():
        pattern = config['url_pattern'].lstrip('/')
        # Escape the pattern, then replace escaped or unescaped placeholders
        regex_pattern = re.escape(pattern)
        # Replace {something} or \{something\} with [^/]+
        regex_pattern = re.sub(r'\\?\{[^}]*\\?\}', r'[^/]+', regex_pattern)
        full_pattern = f"^{base_url}/{regex_pattern}$"
        logger.debug(f"Testing mode '{mode}' with pattern: {full_pattern}")
        if re.match(full_pattern, url):
            logger.debug(f"Matched URL '{url}' to mode '{mode}'")
            return mode, config['scraper']
    logger.debug(f"No mode matched for URL: {url}")
    return None, None

def main():
    parser = argparse.ArgumentParser(description='Video Scraper')
    parser.add_argument('args', nargs='+', help='Site identifier and mode, or direct URL')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--overwrite_files', action='store_true', help='Overwrite existing files')
    args = parser.parse_args()
    log_level = "DEBUG" if args.debug else "INFO"
    logger.remove()
    logger.add(sys.stderr, level=log_level)
    general_config = load_config(os.path.join(SCRIPT_DIR, 'config.yaml'))
    
    try:
        if len(args.args) == 1 and args.args[0].startswith(('http://', 'https://')):
            url = args.args[0]
            matched_site_config = None
            for site_config_file in os.listdir(CONFIG_DIR):
                if site_config_file.endswith('.yaml'):
                    site_config = load_site_config(site_config_file[:-5])
                    if site_config['base_url'] in url:
                        matched_site_config = site_config
                        break
            if matched_site_config:
                headers = general_config.get('headers', {}).copy()
                headers['User-Agent'] = random.choice(general_config['user_agents'])
                mode, scraper = match_url_to_mode(url, matched_site_config)
                if mode:
                    logger.info(f"Matched URL to mode '{mode}' with scraper '{scraper}'")
                    if mode == 'video':
                        process_video_page(url, matched_site_config, general_config, args.overwrite_files, headers)
                    else:
                        identifier = url.split('/')[-1]
                        current_page = 1
                        while url:
                            next_page, new_page_number = process_list_page(
                                url, matched_site_config, general_config, current_page, 
                                mode, identifier, args.overwrite_files, headers
                            )
                            if next_page is None:
                                break
                            url = next_page
                            current_page = new_page_number
                            time.sleep(general_config['sleep']['between_pages'])
                else:
                    logger.warning("URL didn't match any mode; assuming video page.")
                    process_video_page(url, matched_site_config, general_config, args.overwrite_files, headers)
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
            url = construct_url(site_config['base_url'], site_config['modes'][mode]['url_pattern'], site_config, **{mode: identifier} if mode != 'video' else {'video_id': identifier})
            if mode == 'video':
                process_video_page(url, site_config, general_config, args.overwrite_files, headers)
            else:
                current_page = 1
                while url:
                    next_page, new_page_number = process_list_page(url, site_config, general_config, current_page, mode, identifier, args.overwrite_files, headers)
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
