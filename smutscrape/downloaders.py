#!/usr/bin/env python3
"""
Download Manager Module for Smutscrape

This module provides various download methods and a unified interface
for downloading video files using different tools and protocols.
"""

import os
import re
import json
import random
import requests
import subprocess
import shlex
import cloudscraper
import urllib.parse
import tempfile
import shutil
import uuid
import time
from datetime import datetime
from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple, Any
from tqdm import tqdm
from loguru import logger


class DownloadError(Exception):
    """Custom exception for download failures"""
    pass


class BaseDownloader(ABC):
    """Abstract base class for all downloaders"""
    
    def __init__(self, general_config: Dict[str, Any], site_config: Dict[str, Any]):
        self.general_config = general_config
        self.site_config = site_config
    
    @abstractmethod
    def download(self, url: str, destination_path: str, headers: Optional[Dict] = None, 
                 metadata: Optional[Dict] = None, desc: str = "Downloading", **kwargs) -> bool:
        """
        Download a file from the given URL to the destination path.
        
        Args:
            url: The URL to download from
            destination_path: Where to save the file
            headers: Optional HTTP headers
            metadata: Optional metadata for the download
            desc: Description for progress display
            **kwargs: Additional downloader-specific options
            
        Returns:
            bool: True if download succeeded, False otherwise
        """
        pass
    
    def get_user_agent(self, headers: Optional[Dict] = None) -> str:
        """Get a user agent string, either from headers or randomly from config"""
        if headers and 'User-Agent' in headers:
            return headers['User-Agent']
        return random.choice(self.general_config.get('user_agents', ['Mozilla/5.0']))


class RequestsDownloader(BaseDownloader):
    """Downloader using Python requests library"""
    
    def download(self, url: str, destination_path: str, headers: Optional[Dict] = None,
                 metadata: Optional[Dict] = None, desc: str = "Downloading", **kwargs) -> bool:
        """Download using requests library with progress bar"""
        headers = headers or {}
        headers["User-Agent"] = self.get_user_agent(headers)
        
        logger.debug(f"Executing requests GET: {url} with headers: {headers}")
        
        try:
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
                logger.info(f"Successfully completed download to {destination_path}")
                return True
            else:
                logger.error("Download failed: File not found")
                return False
                
        except Exception as e:
            logger.error(f"Requests download failed: {e}")
            return False


class CurlDownloader(BaseDownloader):
    """Downloader using curl command line tool"""
    
    def download(self, url: str, destination_path: str, headers: Optional[Dict] = None,
                 metadata: Optional[Dict] = None, desc: str = "Downloading", **kwargs) -> bool:
        """Download using curl with native progress display"""
        headers = headers or {}
        ua = self.get_user_agent(headers)
        
        # Build curl command
        command = ["curl", "-L", "-o", destination_path, "--retry", "3", "--max-time", "600", "-#", 
                   "-w", "Downloaded: %{size_download} bytes / Total: %{size_total} bytes (%{speed_download} bytes/s)\n"]
        
        command.extend(["-A", ua])
        if "Referer" in headers:
            command.extend(["-H", f"Referer: {headers['Referer']}"])
        if "Cookie" in headers:
            command.extend(["-H", f"Cookie: {headers['Cookie']}"])
        command.append(url)
        
        logger.debug(f"Executing curl command: {' '.join(shlex.quote(arg) for arg in command)}")
        
        try:
            # Pipe curl output directly to terminal
            import sys
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
            
        except Exception as e:
            logger.error(f"Curl download failed: {e}")
            return False


class WgetDownloader(BaseDownloader):
    """Downloader using wget command line tool"""
    
    def download(self, url: str, destination_path: str, headers: Optional[Dict] = None,
                 metadata: Optional[Dict] = None, desc: str = "Downloading", **kwargs) -> bool:
        """Download using wget with custom progress parsing"""
        headers = headers or {}
        ua = self.get_user_agent(headers)
        
        command = ["wget", "--tries=3", "--timeout=600", "-O", destination_path]
        command.extend(["--user-agent", ua])
        if "Referer" in headers:
            command.extend(["--referer", headers['Referer']])
        if "Cookie" in headers:
            command.extend(["--header", f"Cookie: {headers['Cookie']}"])
        command.append(url)
        
        logger.debug(f"Executing wget command: {' '.join(shlex.quote(arg) for arg in command)}")
        
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            
            total_size = self._get_content_length(url, headers)
            progress_regex = re.compile(r'(\d+)%\s+(\d+[KMG]?)')
            
            with tqdm(total=total_size, unit='B', unit_scale=True, desc=desc, disable=not total_size) as pbar:
                for line in process.stdout:
                    match = progress_regex.search(line)
                    if match:
                        percent, _ = match.groups()
                        if total_size:
                            pbar.update((int(percent) * total_size // 100) - pbar.n)
                    elif "Length:" in line and total_size is None:
                        size_match = re.search(r'Length: (\d+)', line)
                        if size_match:
                            size = int(size_match.group(1))
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
            
        except Exception as e:
            logger.error(f"Wget download failed: {e}")
            return False
    
    def _get_content_length(self, url: str, headers: Dict) -> Optional[int]:
        """Attempt to fetch Content-Length header for progress bar accuracy"""
        try:
            ua = self.get_user_agent(headers)
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


class YtDlpDownloader(BaseDownloader):
    """Downloader using yt-dlp"""
    
    def download(self, url: str, destination_path: str, headers: Optional[Dict] = None,
                 metadata: Optional[Dict] = None, desc: str = "Downloading", 
                 overwrite: bool = False, impersonate: bool = False, **kwargs) -> bool:
        """Download using yt-dlp with various options"""
        headers = headers or {}
        ua = self.get_user_agent(headers)
        
        command = ["yt-dlp", "-o", destination_path, "--user-agent", ua, "--progress"]
        
        if overwrite:
            command.append("--force-overwrite")
        
        if metadata and 'Image' in metadata:
            command.extend(["--embed-thumbnail", "--convert-thumbnails", "jpg"])
        
        # Smart handling of impersonate parameter
        logger.debug(f"impersonate value: {impersonate}, type: {type(impersonate)}")
        if impersonate:
            impersonate_value = "generic:impersonate" if impersonate is True else impersonate
            logger.debug(f"Adding impersonate arg: {impersonate_value}")
            command.extend(["--extractor-args", impersonate_value])
        
        command.append(url)
        
        cmd_string = ' '.join(shlex.quote(str(arg)) for arg in command)
        logger.debug(f"Executing yt-dlp command: {cmd_string}")
        
        try:
            import sys
            process = subprocess.Popen(
                command,
                stdout=sys.stdout,  # Direct yt-dlp progress to terminal
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            return_code = process.wait()
            if return_code != 0:
                logger.error(f"yt-dlp failed with return code {return_code}")
                return False
                
            logger.debug(f"Successfully completed yt-dlp download to {destination_path}")
            return True
            
        except Exception as e:
            logger.error(f"Exception during yt-dlp execution: {str(e)}")
            return False


class FFmpegDownloader(BaseDownloader):
    """Downloader using FFmpeg for M3U8/streaming content"""
    
    def download(self, url: str, destination_path: str, headers: Optional[Dict] = None,
                 metadata: Optional[Dict] = None, desc: str = "Downloading", 
                 origin: Optional[str] = None, **kwargs) -> bool:
        """Download M3U8 streams using FFmpeg"""
        headers = headers or {}
        ua = self.get_user_agent(headers)
        
        # Prepare headers for M3U8 fetch
        fetch_headers = {
            "User-Agent": ua,
            "Referer": headers.get("Referer", ""),
            "Accept": "application/vnd.apple.mpegurl",
        }
        if "Cookie" in headers and headers["Cookie"]:
            logger.debug(f"Including provided cookie: {headers['Cookie']}")
            fetch_headers["Cookie"] = headers["Cookie"]
            
        if origin:
            logger.debug(f"Including header for origin: {origin}")
            fetch_headers["Origin"] = origin
        else:
            logger.debug("No origin url provided; omitting origin header")
        
        logger.debug(f"Fetching M3U8 with headers: {fetch_headers}")
        
        try:
            # Fetch M3U8 content
            scraper = cloudscraper.create_scraper()
            response = scraper.get(url, headers=fetch_headers, timeout=30)
            response.raise_for_status()
            m3u8_content = response.text
            logger.debug(f"Fetched M3U8 content: {m3u8_content[:100]}...")
            
            # Write M3U8 content with resolved URLs
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
            
            # Build FFmpeg command
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
            
            # Run FFmpeg with progress tracking
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
            
            # Cleanup
            if os.path.exists(temp_m3u8_path):
                os.remove(temp_m3u8_path)
            
            if return_code != 0:
                logger.error(f"FFmpeg failed with return code {return_code}")
                return False
                
            logger.info(f"Successfully completed ffmpeg download to {destination_path}")
            return True
            
        except Exception as e:
            logger.error(f"FFmpeg download failed: {e}")
            if 'temp_m3u8_path' in locals() and os.path.exists(temp_m3u8_path):
                os.remove(temp_m3u8_path)
            return False


class DownloadManager:
    """Manager class to handle different download methods"""
    
    def __init__(self, general_config: Dict[str, Any]):
        self.general_config = general_config
        self.downloaders = {
            'requests': RequestsDownloader,
            'curl': CurlDownloader,
            'wget': WgetDownloader,
            'yt-dlp': YtDlpDownloader,
            'ffmpeg': FFmpegDownloader
        }
    
    def get_downloader(self, method: str, site_config: Dict[str, Any]) -> Optional[BaseDownloader]:
        """Get a downloader instance for the specified method"""
        downloader_class = self.downloaders.get(method)
        if not downloader_class:
            logger.error(f"Unknown download method: {method}")
            return None
        return downloader_class(self.general_config, site_config)
    
    def download_file(self, url: str, destination_path: str, method: str, 
                      site_config: Dict[str, Any], headers: Optional[Dict] = None, 
                      metadata: Optional[Dict] = None, origin: Optional[str] = None, 
                      overwrite: bool = False) -> bool:
        """
        Download a file using the specified method.
        
        Args:
            url: URL to download from
            destination_path: Where to save the file
            method: Download method to use
            site_config: Site configuration
            headers: Optional HTTP headers
            metadata: Optional metadata
            origin: Optional origin URL (for FFmpeg)
            overwrite: Whether to overwrite existing files
            
        Returns:
            bool: True if download succeeded, False otherwise
        """
        if not url:
            logger.error("Invalid or empty URL")
            return False
            
        os.makedirs(os.path.dirname(destination_path), exist_ok=True)
        
        if url.startswith('//'):
            url = 'http:' + url
        
        use_headers = headers and any(k in headers for k in ["Cookie"])
        desc = f"Downloading {os.path.basename(destination_path)}"
        
        # Use temporary file during download
        temp_path = os.path.join(os.path.dirname(destination_path), f".{os.path.basename(destination_path)}")
        
        try:
            downloader = self.get_downloader(method, site_config)
            if not downloader:
                return False
            
            # Prepare kwargs for specific downloaders
            kwargs = {}
            if method == 'yt-dlp':
                kwargs['overwrite'] = overwrite
                kwargs['impersonate'] = site_config.get("download", {}).get("impersonate", False)
            elif method == 'ffmpeg':
                kwargs['origin'] = origin
            
            # Execute download
            success = downloader.download(
                url=url,
                destination_path=temp_path,
                headers=headers,
                metadata=metadata,
                desc=desc,
                **kwargs
            )
            
            if success and os.path.exists(temp_path):
                # Validate downloaded file
                video_info = self.get_video_metadata(temp_path)
                if video_info:
                    os.rename(temp_path, destination_path)
                    logger.debug(f"Download completed: {os.path.basename(destination_path)}")
                    logger.info(f"Size: {video_info['size_str']} · Duration: {video_info['duration']} · Resolution: {video_info['resolution']}")
                    return True
                else:
                    logger.warning(f"Download completed but metadata invalid for {temp_path}. Removing.")
                    os.remove(temp_path)
                    return False
            elif not success:
                logger.error(f"Download failed for {temp_path}")
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                return False
                
        except Exception as e:
            logger.error(f"Download method '{method}' failed: {e}")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return False
        
        return False
    
    def get_video_metadata(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Extract video duration, resolution, and bitrate using ffprobe"""
        command = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration,bit_rate,size:stream=width,height",
            "-of", "json",
            file_path
        ]
        
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                  universal_newlines=True, check=True)
            metadata = json.loads(result.stdout)
            
            # File size in bytes
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
            
            # Sanity check: reject if file is too small for claimed duration
            if duration > 0 and file_size / duration < 10240:  # ~10KB/s minimum
                logger.warning(f"File {file_path} too small ({file_size} bytes) for duration {duration}s")
                return None
            
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
    
    def process_fallback_download(self, url: str, overwrite: bool = False):
        """
        Fallback download using yt-dlp and direct detection for unsupported sites.
        
        Args:
            url: URL to download
            overwrite: Whether to overwrite existing files
            
        Returns:
            bool: True if download succeeded, False otherwise
        """
        destination_config = self.general_config['download_destinations'][0]
        temp_dir = os.path.join(tempfile.gettempdir(), f"download_{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(temp_dir, exist_ok=True)
        logger.info(f"Fallback download for: {url}")
        
        success, downloaded_files = download_with_ytdlp_fallback(url, temp_dir, self.general_config)
        
        if not success or not downloaded_files:
            logger.warning(f"yt-dlp fallback failed for {url}. Attempting direct detection fallback.")
            if self._fallback_detect_and_download(url, overwrite):
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
        # Import storage manager here to avoid circular imports
        from smutscrape.storage import get_storage_manager
        
        for downloaded_file in downloaded_files:
            source_path = os.path.join(temp_dir, downloaded_file)
            if destination_config['type'] == 'smb':
                smb_destination_path = os.path.join(destination_config['path'], downloaded_file)
                if not overwrite and get_storage_manager().file_exists_on_smb(destination_config, smb_destination_path):
                    logger.info(f"File '{downloaded_file}' exists on SMB. Skipping.")
                    continue
                get_storage_manager().upload_to_smb(source_path, smb_destination_path, destination_config)
            elif destination_config['type'] == 'local':
                final_path = os.path.join(destination_config['path'], downloaded_file)
                if not overwrite and os.path.exists(final_path):
                    logger.info(f"File '{downloaded_file}' exists locally. Skipping.")
                    continue
                os.makedirs(os.path.dirname(final_path), exist_ok=True)
                shutil.move(source_path, final_path)
                get_storage_manager().apply_permissions(final_path, destination_config)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return True
    
    def _fallback_detect_and_download(self, url: str, overwrite: bool = False) -> bool:
        """Helper function for fallback: tries to detect MP4 then M3U8 and download."""
        logger.info(f"Fallback: Attempting direct detection for {url}")
        driver = None
        video_url_detected = None
        download_method = None
        detection_headers = self.general_config.get("headers", {}).copy()
        detection_headers["User-Agent"] = random.choice(self.general_config["user_agents"])

        # Import here to avoid circular imports
        try:
            from config import get_config_manager
            from smutscrape.utilities import is_url
            from smutscrape.storage import get_storage_manager
        except ImportError as e:
            logger.error(f"Fallback: Failed to import required modules: {e}")
            return False

        try:
            from selenium.webdriver.common.by import By
            driver = get_config_manager().get_selenium_driver()
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
            mp4_found_url, mp4_cookies = self._extract_mp4_urls(driver, current_url_for_scan)
            if mp4_found_url:
                video_url_detected = mp4_found_url
                download_method = 'requests'
                detection_headers.update({"Cookie": mp4_cookies, "Referer": current_url_for_scan,
                                     "User-Agent": get_config_manager().selenium_user_agent or detection_headers["User-Agent"]})
                logger.info(f"Fallback: Detected MP4: {video_url_detected}")
            else:
                logger.info(f"Fallback: MP4 not found via direct detection for {current_url_for_scan}, trying M3U8.")
                # Try M3U8 detection
                m3u8_found_url, m3u8_cookies = self._extract_m3u8_urls(driver, current_url_for_scan)
                if m3u8_found_url:
                    video_url_detected = m3u8_found_url
                    download_method = 'ffmpeg'
                    detection_headers.update({"Cookie": m3u8_cookies, "Referer": current_url_for_scan,
                                         "User-Agent": get_config_manager().selenium_user_agent or detection_headers["User-Agent"]})
                    logger.info(f"Fallback: Detected M3U8: {video_url_detected}")
                else:
                    logger.warning(f"Fallback: Direct detection failed for MP4 and M3U8 on {current_url_for_scan}.")
                    return False
        except Exception as e:
            logger.warning(f"Fallback: Selenium not available or failed, cannot perform direct MP4/M3U8 detection: {e}")
            return False

        if not video_url_detected or not download_method:
            logger.debug("Fallback: video_url_detected or download_method is missing after detection attempts.")
            return False

        title_from_url_path = url.split('/')[-1].split('?')[0] if '/' in url else url
        title = re.sub(r'[^a-zA-Z0-9_.-]', '_', title_from_url_path) or "fallback_video"
        invalid_chars = self.general_config['file_naming']['invalid_chars']
        
        # Import process_title here to avoid circular imports
        from smutscrape.utilities import process_title, construct_filename
        processed_title = process_title(title, invalid_chars)
        
        filename = construct_filename(processed_title, {}, self.general_config) # Use empty site_config for basic construction

        destination_config = self.general_config['download_destinations'][0]
        temp_storage_path = destination_config.get('temporary_storage', os.path.join(tempfile.gettempdir(), 'smutscrape'))
        os.makedirs(temp_storage_path, exist_ok=True)
        # Use a unique name for the temporary download to avoid collision
        temp_filename_for_download = str(uuid.uuid4().hex[:8]) + "_" + filename
        local_temp_path = os.path.join(temp_storage_path, temp_filename_for_download)

        logger.info(f"Fallback: Downloading detected video {video_url_detected} as {temp_filename_for_download} using {download_method}")
        # Download using the detected method
        success = self.download_file(
            url=video_url_detected,
            destination_path=local_temp_path,
            method=download_method,
            site_config={"download": {"method": download_method}},
            headers=detection_headers,
            overwrite=overwrite
        )

        if success:
            final_filename_at_destination = filename # This is the desired final name, not the temp one.
            if destination_config['type'] == 'smb':
                smb_final_path = os.path.join(destination_config['path'], final_filename_at_destination)
                if not overwrite and get_storage_manager().file_exists_on_smb(destination_config, smb_final_path):
                    logger.info(f"Fallback: File '{final_filename_at_destination}' exists on SMB. Skipping upload.")
                    os.remove(local_temp_path) # Clean up temp file
                    return True
                get_storage_manager().upload_to_smb(local_temp_path, smb_final_path, destination_config, overwrite)
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
                get_storage_manager().apply_permissions(local_final_storage_path, destination_config)
                logger.success(f"Fallback: Moved detected video to local destination: {local_final_storage_path}")
                return True
        else:
            logger.error(f"Fallback: Download of detected video failed for {video_url_detected}")
            if os.path.exists(local_temp_path):
                os.remove(local_temp_path)
        return False
    
    def _extract_mp4_urls(self, driver, url):
        """Extract MP4 URLs from network traffic"""
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

        # Prioritize higher resolution if discernible from URL
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
    
    def _extract_m3u8_urls(self, driver, url):
        """Extract M3U8 URLs from network traffic"""
        logger.debug(f"Extracting M3U8 URLs from: {url}")
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
    
    def extract_mp4_urls(self, driver, url, site_config=None):
        """Public method to extract MP4 URLs from network traffic"""
        return self._extract_mp4_urls(driver, url)
    
    def extract_m3u8_urls(self, driver, url, site_config=None):
        """Public method to extract M3U8 URLs from network traffic"""
        return self._extract_m3u8_urls(driver, url)


def download_with_ytdlp_fallback(url: str, temp_dir: str, general_config: Dict[str, Any]) -> Tuple[bool, list]:
    """
    Fallback download using yt-dlp for unsupported sites.
    
    Args:
        url: URL to download
        temp_dir: Temporary directory for downloads
        general_config: General configuration
        
    Returns:
        Tuple of (success, list of downloaded files)
    """
    command = f"yt-dlp --paths {temp_dir} --format best --add-metadata"
    if general_config.get('user_agents'):
        command += f" --user-agent \"{random.choice(general_config['user_agents'])}\""
    command += f" \"{url}\""
    
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, 
                              stderr=subprocess.STDOUT, universal_newlines=True, cwd=temp_dir)
    
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