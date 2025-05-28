# sites.py
"""
Site configuration classes for managing website-specific scraping configurations.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import yaml
import os
from pathlib import Path
from loguru import logger


@dataclass
class SiteMode:
    """Represents a single scraping mode (e.g., video, model, category)"""
    name: str
    url_pattern: str
    url_pattern_pages: Optional[str] = None
    scraper: str = "list_scraper"
    tip: Optional[str] = None
    note: Optional[str] = None
    examples: List[str] = field(default_factory=list)
    url_encoding_rules: Dict[str, str] = field(default_factory=dict)


@dataclass
class ScraperConfig:
    """Configuration for a specific scraper (video_scraper, list_scraper, etc.)"""
    selectors: Dict[str, Any]
    
    def get_selector(self, field: str) -> Optional[Any]:
        return self.selectors.get(field)


@dataclass
class DownloadConfig:
    """Download-specific configuration"""
    method: str = "curl"
    additional_params: Dict[str, Any] = field(default_factory=dict)


class SiteConfig:
    """Main site configuration class"""
    
    def __init__(self, config_dict: Dict[str, Any], config_path: Optional[str] = None):
        self.config_path = config_path
        self._raw_config = config_dict
        
        # Basic info
        self.name = config_dict.get('name', '')
        self.shortcode = config_dict.get('shortcode', '')
        self.domain = config_dict.get('domain', '')
        self.base_url = config_dict.get('base_url', '')
        
        # Behavior flags
        self.no_overwrite = config_dict.get('no_overwrite', False)
        self.use_selenium = config_dict.get('use_selenium', False)
        self.m3u8_mode = config_dict.get('m3u8_mode', False)
        self.mp4_mode = config_dict.get('mp4_mode', False)
        self.selector_style = config_dict.get('selector_style', 'css')
        
        # Naming
        self.name_prefix = config_dict.get('name_prefix', '')
        self.name_suffix = config_dict.get('name_suffix', '')
        self.unique_name = config_dict.get('unique_name', False)
        
        # URL encoding rules
        self.url_encoding_rules = config_dict.get('url_encoding_rules', {})
        
        # Download configuration
        download_dict = config_dict.get('download', {})
        self.download = DownloadConfig(
            method=download_dict.get('method', 'curl'),
            additional_params={k: v for k, v in download_dict.items() if k != 'method'}
        )
        
        # Modes
        self.modes = self._parse_modes(config_dict.get('modes', {}))
        
        # Scrapers
        self.scrapers = self._parse_scrapers(config_dict.get('scrapers', {}))
        
        # Iframe handling
        self.iframe = config_dict.get('iframe', {})
        
        # Ignored terms
        self.ignored_terms = config_dict.get('ignored_terms', [])
    
    def _parse_modes(self, modes_dict: Dict[str, Any]) -> Dict[str, SiteMode]:
        """Parse modes from configuration"""
        modes = {}
        for mode_name, mode_config in modes_dict.items():
            mode = SiteMode(
                name=mode_name,
                url_pattern=mode_config.get('url_pattern', ''),
                url_pattern_pages=mode_config.get('url_pattern_pages'),
                scraper=mode_config.get('scraper', 'list_scraper'),
                tip=mode_config.get('tip'),
                note=mode_config.get('note'),
                examples=mode_config.get('examples', []),
                url_encoding_rules=mode_config.get('url_encoding_rules', {})
            )
            modes[mode_name] = mode
        return modes
    
    def _parse_scrapers(self, scrapers_dict: Dict[str, Any]) -> Dict[str, ScraperConfig]:
        """Parse scraper configurations"""
        scrapers = {}
        for scraper_name, scraper_config in scrapers_dict.items():
            scrapers[scraper_name] = ScraperConfig(selectors=scraper_config)
        return scrapers
    
    def get_mode(self, mode_name: str) -> Optional[SiteMode]:
        """Get a specific mode configuration"""
        return self.modes.get(mode_name)
    
    def get_scraper(self, scraper_name: str) -> Optional[ScraperConfig]:
        """Get a specific scraper configuration"""
        return self.scrapers.get(scraper_name)
    
    def has_mode(self, mode_name: str) -> bool:
        """Check if a mode exists"""
        return mode_name in self.modes
    
    def get_available_modes(self) -> List[str]:
        """Get list of available modes (excluding 'video')"""
        return [m for m in self.modes.keys() if m != 'video']
    
    def has_metadata_selectors(self, return_fields: bool = False) -> Any:
        """
        Check if the site config has selectors for metadata fields beyond title, download_url, and image.
        If return_fields=True, return the list of fields instead of a boolean.
        """
        video_scraper = self.scrapers.get('video_scraper')
        if not video_scraper:
            return [] if return_fields else False
            
        excluded = {'title', 'download_url', 'image'}
        metadata_fields = [field for field in video_scraper.selectors.keys() if field not in excluded]
        
        if return_fields:
            return sorted(metadata_fields) if metadata_fields else []
        return bool(metadata_fields)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from the raw config dict for backward compatibility"""
        return self._raw_config.get(key, default)
    
    @classmethod
    def from_file(cls, file_path: str) -> 'SiteConfig':
        """Load site configuration from YAML file"""
        with open(file_path, 'r') as f:
            config_dict = yaml.safe_load(f)
        return cls(config_dict, config_path=file_path)
    
    @classmethod
    def load_by_identifier(cls, identifier: str, sites_dir: str) -> Optional['SiteConfig']:
        """Load site config by URL, shortcode, name, or domain"""
        from urllib.parse import urlparse
        
        identifier_lower = identifier.lower()
        is_url = bool(urlparse(identifier).netloc) or bool(urlparse(identifier).scheme)
        parsed_netloc = urlparse(identifier).netloc.lower().replace('www.', '') if is_url else None
        
        for config_file in os.listdir(sites_dir):
            if not config_file.endswith('.yaml'):
                continue
                
            config_path = os.path.join(sites_dir, config_file)
            try:
                site_config = cls.from_file(config_path)
                
                # Match based on identifier type
                if is_url and parsed_netloc == site_config.domain.lower():
                    logger.debug(f"Matched URL '{identifier}' to config '{config_file}' by domain '{site_config.domain}'")
                    return site_config
                elif identifier_lower in [
                    site_config.shortcode.lower(),
                    site_config.name.lower(),
                    site_config.domain.lower()
                ]:
                    logger.debug(f"Matched identifier '{identifier}' to config '{config_file}'")
                    return site_config
                    
            except Exception as e:
                logger.warning(f"Failed to load config '{config_file}': {e}")
                continue
                
        logger.debug(f"No site config matched for identifier '{identifier}'")
        return None 