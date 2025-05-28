#!/usr/bin/env python3
"""
Download managers for various protocols and methods.
Handles downloading videos via requests, curl, wget, yt-dlp, and ffmpeg.
"""

import os
import re
import sys
import json
import shlex
import random
import subprocess
import urllib.parse
from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple, Any

import requests
import cloudscraper
from loguru import logger
from tqdm import tqdm


class DownloadError(Exception):
    """Custom exception for download failures."""
    pass


class BaseDownloader(ABC):
    """Abstract base class for all downloaders."""
    
    def __init__(self, general_config: Dict[str, Any], site_config: Dict[str, Any] = None):
        self.general_config = general_config
        self.site_config = site_config or {}
    
    @abstractmethod
    def download(self, url: str, destination_path: str, headers: Optional[Dict[str, str]] = None, 
                 desc: str = "Downloading", **kwargs) -> bool:
        """
        Download a file from URL to destination path.
        
        Args:
            url: Source URL
            destination_path: Where to save the file
            headers: Optional HTTP headers
            desc: Description for progress bar
            **kwargs: Additional downloader-specific options
            
        Returns:
            bool: True if successful, False otherwise
        """
        pass
    
    def get_user_agent(self, headers: Optional[Dict[str, str]] = None) -> str:
        """Get a user agent string, either from headers or randomly from config."""
        if headers and headers.get('User-Agent'):
            return headers['User-Agent']
        return random.choice(self.general_config.get('user_agents', ['Mozilla/5.0']))
    
    def prepare_headers(self, headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Prepare headers with user agent."""
        headers = headers or {}
        if 'User-Agent' not in headers:
            headers['User-Agent'] = self.get_user_agent()
        return headers


class RequestsDownloader(BaseDownloader):
    """Download using Python requests library."""
    
    def download(self, url: str, destination_path: str, headers: Optional[Dict[str, str]] = None,
                 desc: str = "Downloading", **kwargs) -> bool:
        headers = self.prepare_headers(headers)
        
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
    """Download using curl command-line tool."""
    
    def download(self, url: str, destination_path: str, headers: Optional[Dict[str, str]] = None,
                 desc: str = "Downloading", **kwargs) -> bool:
        headers = self.prepare_headers(headers)
        ua = headers.get('User-Agent')
        
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
            process = subprocess.Popen(
                command,
                stdout=sys.stdout,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
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
    """Download using wget command-line tool."""
    
    def download(self, url: str, destination_path: str, headers: Optional[Dict[str, str]] = None,
                 desc: str = "Downloading", **kwargs) -> bool:
        headers = self.prepare_headers(headers)
        ua = headers.get('User-Agent')
        
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
    
    def _get_content_length(self, url: str, headers: Dict[str, str]) -> Optional[int]:
        """Attempt to fetch Content-Length header for progress bar accuracy."""
        try:
            fetch_headers = {"User-Agent": headers.get('User-Agent')}
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
    """Download using yt-dlp tool."""
    
    def download(self, url: str, destination_path: str, headers: Optional[Dict[str, str]] = None,
                 desc: str = "Downloading", metadata: Optional[Dict[str, Any]] = None,
                 overwrite: bool = False, impersonate: bool = False, **kwargs) -> bool:
        headers = self.prepare_headers(headers)
        ua = headers.get('User-Agent')
        
        command = ["yt-dlp", "-o", destination_path, "--user-agent", ua, "--progress"]
        
        # Debug logging for impersonate parameter
        logger.debug(f"impersonate value: {impersonate}, type: {type(impersonate)}")
        
        if overwrite:
            command.append("--force-overwrite")
        
        if metadata and 'Image' in metadata:
            command.extend(["--embed-thumbnail", "--convert-thumbnails", "jpg"])
        
        # Smart handling of impersonate parameter
        if impersonate:
            # If impersonate is True, use default value
            # If impersonate is a string, use that string
            impersonate_value = "generic:impersonate" if impersonate is True else impersonate
            logger.debug(f"Adding impersonate arg: {impersonate_value}")
            command.extend(["--extractor-args", impersonate_value])
        
        command.append(url)
        
        # Log the full command for debugging
        cmd_string = ' '.join(shlex.quote(str(arg)) for arg in command)
        logger.debug(f"Executing yt-dlp command: {cmd_string}")
        
        try:
            process = subprocess.Popen(
                command,
                stdout=sys.stdout,  # Direct yt-dlp progress to terminal
                stderr=subprocess.STDOUT,  # Combine stderr with stdout
                universal_newlines=True,
                bufsize=1  # Line buffering for real-time output
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
    """Download HLS streams using ffmpeg."""
    
    def download(self, url: str, destination_path: str, headers: Optional[Dict[str, str]] = None,
                 desc: str = "Downloading", origin: Optional[str] = None, **kwargs) -> bool:
        headers = self.prepare_headers(headers)
        ua = headers.get('User-Agent')
        
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
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch M3U8: {e}")
            return False
        
        # Save M3U8 content to temporary file
        temp_m3u8_path = destination_path + ".m3u8"
        try:
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
            
            # Build ffmpeg command
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
            if return_code != 0:
                logger.error(f"FFmpeg failed with return code {return_code}")
                return False
                
            logger.info(f"Successfully completed ffmpeg download to {destination_path}")
            return True
            
        except Exception as e:
            logger.error(f"FFmpeg download failed: {e}")
            return False
            
        finally:
            # Clean up temporary M3U8 file
            if os.path.exists(temp_m3u8_path):
                os.remove(temp_m3u8_path)


class DownloadManager:
    """Factory class to manage different downloaders."""
    
    DOWNLOADERS = {
        'requests': RequestsDownloader,
        'curl': CurlDownloader,
        'wget': WgetDownloader,
        'yt-dlp': YtDlpDownloader,
        'ytdlp': YtDlpDownloader,  # Alias
        'ffmpeg': FFmpegDownloader,
    }
    
    def __init__(self, general_config: Dict[str, Any], site_config: Dict[str, Any] = None):
        self.general_config = general_config
        self.site_config = site_config
        self._downloaders = {}
    
    def get_downloader(self, method: str) -> BaseDownloader:
        """Get or create a downloader instance for the specified method."""
        if method not in self._downloaders:
            downloader_class = self.DOWNLOADERS.get(method)
            if not downloader_class:
                raise ValueError(f"Unknown download method: {method}")
            self._downloaders[method] = downloader_class(self.general_config, self.site_config)
        return self._downloaders[method]
    
    def download(self, url: str, destination_path: str, method: str,
                 headers: Optional[Dict[str, str]] = None, **kwargs) -> bool:
        """
        Download a file using the specified method.
        
        Args:
            url: Source URL
            destination_path: Where to save the file
            method: Download method (requests, curl, wget, yt-dlp, ffmpeg)
            headers: Optional HTTP headers
            **kwargs: Additional method-specific options
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not url:
            logger.error("Invalid or empty URL")
            return False
            
        os.makedirs(os.path.dirname(destination_path), exist_ok=True)
        
        if url.startswith('//'):
            url = 'http:' + url
        
        desc = kwargs.pop('desc', f"Downloading {os.path.basename(destination_path)}")
        temp_path = os.path.join(os.path.dirname(destination_path), f".{os.path.basename(destination_path)}")
        
        try:
            downloader = self.get_downloader(method)
            success = downloader.download(url, temp_path, headers, desc=desc, **kwargs)
            
            if success and os.path.exists(temp_path):
                # Validate the download if it's a video
                if method in ['ffmpeg', 'yt-dlp', 'ytdlp'] or destination_path.endswith(('.mp4', '.mkv', '.avi', '.webm')):
                    video_info = self._get_video_metadata(temp_path)
                    if video_info:
                        os.rename(temp_path, destination_path)
                        logger.debug(f"Download completed: {os.path.basename(destination_path)}")
                        logger.info(f"Size: {video_info['size_str']} · Duration: {video_info['duration']} · Resolution: {video_info['resolution']}")
                        return True
                    else:
                        logger.warning(f"Download completed but metadata invalid for {temp_path}. Removing.")
                        os.remove(temp_path)
                        return False
                else:
                    # Non-video file, just rename
                    os.rename(temp_path, destination_path)
                    logger.debug(f"Download completed: {os.path.basename(destination_path)}")
                    return True
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
    
    def _get_video_metadata(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Extract video duration, resolution, and bitrate using ffprobe, with sanity check."""
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
            
            # Sanity check: reject if file is too small for claimed duration (e.g., < 10KB/s)
            if duration > 0 and file_size / duration < 10240:  # ~10KB/s minimum, adjustable
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


# Convenience function for backwards compatibility
def download_file(url: str, destination_path: str, method: str, general_config: Dict[str, Any],
                  site_config: Dict[str, Any], headers: Optional[Dict[str, str]] = None,
                  metadata: Optional[Dict[str, Any]] = None, origin: Optional[str] = None,
                  overwrite: bool = False) -> bool:
    """
    Legacy function for downloading files. Use DownloadManager instead.
    """
    manager = DownloadManager(general_config, site_config)
    return manager.download(
        url, destination_path, method, headers,
        metadata=metadata, origin=origin, overwrite=overwrite
    ) 