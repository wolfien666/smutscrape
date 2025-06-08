#!/usr/bin/env python3
"""
Session and State Management Module for Smutscrape

This module handles state file operations, progress tracking, and session management.
"""

import os
import time
from typing import Set, Optional
from loguru import logger


class SessionManager:
    """Manages session state and processed URL tracking."""
    
    def __init__(self, state_file_path: str):
        """Initialize session manager with state file path.
        
        Args:
            state_file_path: Path to the state file for tracking processed URLs
        """
        self.state_file = state_file_path
        self.processed_urls: Set[str] = set()
        self.last_vpn_action_time = 0
        
        # Load existing state
        self.load_state()
    
    def load_state(self) -> Set[str]:
        """Load processed video URLs from state file.
        
        Returns:
            Set of processed URLs
        """
        if not os.path.exists(self.state_file):
            self.processed_urls = set()
            return self.processed_urls
        
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                self.processed_urls = set(line.strip() for line in f if line.strip())
            logger.debug(f"Loaded {len(self.processed_urls)} URLs from state file")
        except Exception as e:
            logger.error(f"Failed to load state file '{self.state_file}': {e}")
            self.processed_urls = set()
        
        return self.processed_urls
    
    def save_state(self, url: str):
        """Append a single URL to the state file.
        
        Args:
            url: URL to mark as processed
        """
        try:
            with open(self.state_file, 'a', encoding='utf-8') as f:
                f.write(f"{url}\n")
            self.processed_urls.add(url)
            logger.debug(f"Added URL to state: {url}")
        except Exception as e:
            logger.error(f"Failed to append to state file '{self.state_file}': {e}")
    
    def is_processed(self, url: str) -> bool:
        """Check if a URL has been processed.
        
        Args:
            url: URL to check
            
        Returns:
            True if URL has been processed, False otherwise
        """
        return url in self.processed_urls
    
    def mark_processed(self, url: str):
        """Mark a URL as processed without immediately saving to file.
        
        Args:
            url: URL to mark as processed
        """
        self.processed_urls.add(url)
    
    def update_vpn_time(self, timestamp: Optional[float] = None):
        """Update the last VPN action timestamp.
        
        Args:
            timestamp: Timestamp to set, or current time if None
        """
        self.last_vpn_action_time = timestamp or time.time()
    
    def should_refresh_vpn(self, interval: int = 300) -> bool:
        """Check if VPN should be refreshed based on time interval.
        
        Args:
            interval: Interval in seconds between VPN refreshes
            
        Returns:
            True if VPN should be refreshed
        """
        current_time = time.time()
        return current_time - self.last_vpn_action_time > interval
    
    def get_state_count(self) -> int:
        """Get the number of processed URLs.
        
        Returns:
            Number of processed URLs
        """
        return len(self.processed_urls)

def is_url_processed(url, state_set):
	"""Check if a URL is in the state set."""
	return url in state_set