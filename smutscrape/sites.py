#!/usr/bin/env python3
"""
Sites Module for Smutscrape

This module provides a class-based structure for site configurations,
offering type safety, validation, and encapsulation of site-specific logic.
"""

import os
import yaml
import random
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from urllib.parse import urlparse
from loguru import logger
from rich.table import Table
from rich.console import Group


@dataclass
class ModeConfig:
    """Configuration for a specific mode (e.g., 'channel', 'search', 'video')"""
    name: str
    tip: str
    examples: List[str]
    url_pattern: str
    url_pattern_pages: Optional[str] = None
    scraper: Optional[str] = None
    max_pages: Optional[int] = None
    url_encoding_rules: Dict[str, str] = field(default_factory=dict)
    video_id_placeholder: Optional[str] = None  # For video mode
    
    def supports_pagination(self) -> bool:
        """Check if this mode supports pagination"""
        return bool(self.url_pattern_pages)
    
    def get_url_pattern(self, page_num: int = 1) -> str:
        """Get the appropriate URL pattern based on page number"""
        if page_num > 1 and self.url_pattern_pages:
            return self.url_pattern_pages
        return self.url_pattern


@dataclass 
class ScraperFieldConfig:
    """Configuration for a scraper field"""
    selector: Union[str, List[str]]
    attribute: Optional[str] = None
    iframe: Optional[str] = None
    post_process: Optional[List[Dict[str, Any]]] = None
    
    @classmethod
    def from_dict(cls, data: Union[str, Dict[str, Any]]) -> 'ScraperFieldConfig':
        """Create from dictionary or string"""
        if isinstance(data, str):
            return cls(selector=data)
        
        selector = data.get('selector', '')
        return cls(
            selector=selector,
            attribute=data.get('attribute'),
            iframe=data.get('iframe'),
            post_process=data.get('postProcess', [])
        )


@dataclass
class ScraperConfig:
    """Configuration for a scraper (video, list, or rss)"""
    name: str
    fields: Dict[str, ScraperFieldConfig]
    pagination: Optional[Dict[str, Any]] = None
    video_container: Optional[Dict[str, str]] = None
    video_item: Optional[Dict[str, Any]] = None
    
    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'ScraperConfig':
        """Create from dictionary"""
        # Handle different scraper structures
        if name == 'list_scraper':
            fields = {}
            if 'video_item' in data and 'fields' in data['video_item']:
                fields = {
                    field_name: ScraperFieldConfig.from_dict(field_config)
                    for field_name, field_config in data['video_item']['fields'].items()
                }
            return cls(
                name=name,
                fields=fields,
                pagination=data.get('pagination'),
                video_container=data.get('video_container'),
                video_item=data.get('video_item')
            )
        else:
            # Video or RSS scraper
            fields = {
                field_name: ScraperFieldConfig.from_dict(field_config)
                for field_name, field_config in data.items()
                if field_name not in ['pagination', 'video_container', 'video_item']
            }
            return cls(name=name, fields=fields)


@dataclass
class DownloadConfig:
    """Configuration for download settings"""
    method: str = "curl"
    impersonate: Union[bool, str] = False
    
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> 'DownloadConfig':
        """Create from dictionary"""
        if not data:
            return cls()
        return cls(
            method=data.get('method', 'curl'),
            impersonate=data.get('impersonate', False)
        )


class SiteConfiguration:
    """Encapsulates all configuration for a website"""
    
    def __init__(self, config_dict: Dict[str, Any], config_file: str = None):
        """Initialize from a configuration dictionary"""
        self.config_file = config_file
        self._raw_config = config_dict
        
        # Basic properties
        self.name = config_dict.get('name', 'Unknown')
        self.shortcode = config_dict.get('shortcode', '??')
        self.domain = config_dict.get('domain', 'n/a')
        self.base_url = config_dict.get('base_url', '')
        
        # Features
        self.use_selenium = config_dict.get('use_selenium', False)
        self.m3u8_mode = config_dict.get('m3u8_mode', False)
        self.mp4_mode = config_dict.get('mp4_mode', False)
        self.detect_mode = config_dict.get('detect_mode', False)
        
        # File naming
        self.name_prefix = config_dict.get('name_prefix', '')
        self.name_suffix = config_dict.get('name_suffix', '')
        self.unique_name = bool(config_dict.get('unique_name', False))
        self.remove_title_string = config_dict.get('remove_title_string', '')
        
        # Notes
        self.note = config_dict.get('note')
        
        # URL encoding rules
        self.url_encoding_rules = config_dict.get('url_encoding_rules', {})
        
        # Parse modes
        self.modes: Dict[str, ModeConfig] = {}
        for mode_name, mode_data in config_dict.get('modes', {}).items():
            self.modes[mode_name] = ModeConfig(
                name=mode_name,
                tip=mode_data.get('tip', 'No description available'),
                examples=mode_data.get('examples', []),
                url_pattern=mode_data.get('url_pattern', ''),
                url_pattern_pages=mode_data.get('url_pattern_pages'),
                scraper=mode_data.get('scraper'),
                max_pages=mode_data.get('max_pages'),
                url_encoding_rules=mode_data.get('url_encoding_rules', {}),
                video_id_placeholder=mode_data.get('video_id_placeholder')
            )
        
        # Parse scrapers
        self.scrapers: Dict[str, ScraperConfig] = {}
        for scraper_name, scraper_data in config_dict.get('scrapers', {}).items():
            self.scrapers[scraper_name] = ScraperConfig.from_dict(scraper_name, scraper_data)
        
        # Download configuration
        self.download = DownloadConfig.from_dict(config_dict.get('download'))
        
        # Iframe configuration
        self.iframe = config_dict.get('iframe', {'enabled': False})
    
    def matches_url(self, url: str) -> bool:
        """Check if a URL belongs to this site"""
        parsed_url = urlparse(url)
        netloc = parsed_url.netloc.lower().replace('www.', '')
        
        # Check against domain
        if self.domain and self.domain.lower() == netloc:
            return True
        
        # Check against base_url
        if self.base_url:
            base_netloc = urlparse(self.base_url).netloc.lower().replace('www.', '')
            if base_netloc == netloc:
                return True
        
        return False
    
    def matches_identifier(self, identifier: str) -> bool:
        """Check if an identifier matches this site (shortcode, name, or domain)"""
        identifier_lower = identifier.lower()
        return any([
            identifier_lower == self.shortcode.lower(),
            identifier_lower == self.name.lower(),
            identifier_lower == self.domain.lower()
        ])
    
    def get_mode(self, mode_name: str) -> Optional[ModeConfig]:
        """Get a mode configuration by name"""
        return self.modes.get(mode_name)
    
    def get_available_modes(self, exclude_video: bool = True) -> List[str]:
        """Get list of available modes"""
        modes = list(self.modes.keys())
        if exclude_video and 'video' in modes:
            modes.remove('video')
        return modes
    
    def has_mode(self, mode_name: str) -> bool:
        """Check if a mode exists"""
        return mode_name in self.modes
    
    def get_scraper(self, scraper_name: str) -> Optional[ScraperConfig]:
        """Get a scraper configuration by name"""
        return self.scrapers.get(scraper_name)
    
    def has_metadata_selectors(self) -> bool:
        """Check if site has metadata selectors beyond basic fields"""
        video_scraper = self.scrapers.get('video_scraper')
        if not video_scraper:
            return False
        
        excluded = {'title', 'download_url', 'image'}
        metadata_fields = [
            field for field in video_scraper.fields.keys() 
            if field not in excluded
        ]
        return bool(metadata_fields)
    
    def get_metadata_fields(self) -> List[str]:
        """Get list of metadata fields"""
        video_scraper = self.scrapers.get('video_scraper')
        if not video_scraper:
            return []
        
        excluded = {'title', 'download_url', 'image'}
        return sorted([
            field for field in video_scraper.fields.keys() 
            if field not in excluded
        ])
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert back to dictionary format"""
        return self._raw_config
    
    def display_details(self, term_width: int, general_config: Dict[str, Any]):
        """Display a detailed readout for this site config with domain-based ASCII art."""
        from smutscrape.utilities import render_ascii, console
        from rich.table import Table
        
        console.print()
        render_ascii(self.domain, general_config, term_width)
        console.print()
        console.print()
        
        label_width = 12
        
        console.print(f"{'name:':>{label_width}} [bold]{self.name}[/bold] ({self.shortcode})")
        console.print(f"{'homepage:':>{label_width}} [bold]{self.base_url}[/bold]")
        console.print(f"{'downloader:':>{label_width}} [bold]{self.download.method}[/bold]")
        console.print(f"{'metadata:':>{label_width}} {', '.join(self.get_metadata_fields())}") 
        
        if self.note:
            console.print(f"{'note:':>{label_width}} {self.note}")
        if self.name_suffix:
            console.print(f"{'note:':>{label_width}} Filenames are appended with [bold]\"{self.name_suffix}\"[/bold].")
        if self.unique_name:
            console.print(f"{'note:':>{label_width}} Filenames are appended with a UID to avoid filename collisions, at the risk of downloading multiple duplicates.")
        if self.use_selenium:
            console.print(f"{'note:':>{label_width}} [yellow][bold]selenium[/bold][/yellow] and [yellow][bold]chromedriver[/bold][/yellow] are required to scrape this site.")
            console.print(f"{'':>{label_width}} See: https://github.com/io-flux/smutscrape#selenium--chromedriver-%EF%B8%8F%EF%B8%8F")
        
        console.print()
        console.print(f"{'usage:':>{label_width}} [magenta]scrape {self.shortcode} {{mode}} {{query}}[/magenta]")
        console.print(f"{'':>{label_width}} [magenta]scrape {self.base_url}{self.modes.get('video', ModeConfig('video', '', [], '/watch/0123456.html')).url_pattern}[/magenta]")
        console.print()
        
        if self.modes:
            console.print("[yellow][bold]supported modes:[/bold][/yellow]")
            mode_table = Table(show_edge=True, expand=True, width=term_width)
            mode_table.add_column("[bold]mode[/bold]", width=15)
            mode_table.add_column("[bold]function[/bold]", width=(term_width//10)*4)
            mode_table.add_column("[bold]example[/bold]", width=term_width//2)
            
            has_pagination_footnote = False
            has_encoding_footnote = False
            for mode in self.modes.values():
                example = random.choice(mode.examples) if mode.examples else "N/A"
                example_cmd = f"[magenta]scrape {self.shortcode} {mode.name} \"{example}\"[/magenta]"
                
                # Check for footnotes per mode
                supports_pagination = mode.supports_pagination()
                has_special_encoding = " & " in mode.url_encoding_rules or "&" in mode.url_encoding_rules
                footnotes = []
                if supports_pagination:
                    footnotes.append("✦")
                    has_pagination_footnote = True
                if has_special_encoding:
                    footnotes.append("‡")
                    has_encoding_footnote = True
                mode_display = f"[yellow][bold]{mode.name}[/bold][/yellow]" + (f" {''.join(footnotes)}" if footnotes else "")
                mode_table.add_row(mode_display, mode.tip, example_cmd)
            
            # Add all applicable footnotes
            footnotes = []
            if has_pagination_footnote:
                footnotes.append("✦ [italic]supports [bold][green]pagination[/green][/bold]; see [bold][yellow]optional arguments[/yellow][/bold] below.[/italic]")
            if self.use_selenium:
                footnotes.append("† [italic][yellow][bold]selenium[/bold][/yellow] and [yellow][bold]chromedriver[/bold][/yellow] required.[/italic]")
            if has_encoding_footnote:
                footnotes.append("‡ [italic]combine terms with \'&\' to search them together.[/italic]")
            
            from rich.console import Group
            console.print(Group(mode_table, *footnotes) if footnotes else mode_table)
            console.print()
        console.print()
        
        # Note: display_options() should be called separately after this
    
    def __repr__(self) -> str:
        return f"SiteConfiguration(name='{self.name}', shortcode='{self.shortcode}', domain='{self.domain}')"


class SiteManager:
    """Manages all site configurations"""
    
    def __init__(self, site_directory: str):
        """Initialize with a directory containing site YAML files"""
        self.site_directory = site_directory
        self.sites: Dict[str, SiteConfiguration] = {}
        self._load_sites()
    
    def _load_sites(self):
        """Load all site configurations from the directory"""
        if not os.path.exists(self.site_directory):
            logger.error(f"Site directory '{self.site_directory}' does not exist")
            return
        
        for config_file in os.listdir(self.site_directory):
            if config_file.endswith('.yaml'):
                config_path = os.path.join(self.site_directory, config_file)
                try:
                    with open(config_path, 'r') as f:
                        config_dict = yaml.safe_load(f)
                    
                    if config_dict:
                        site = SiteConfiguration(config_dict, config_file)
                        # Store by shortcode for quick lookup
                        self.sites[site.shortcode] = site
                        logger.debug(f"Loaded site config: {site.shortcode} ({site.name})")
                except Exception as e:
                    logger.warning(f"Failed to load site config '{config_file}': {e}")
    
    def get_site_by_identifier(self, identifier: str) -> Optional[SiteConfiguration]:
        """Get site by URL, shortcode, name, or domain"""
        # First check if it's a URL
        parsed = urlparse(identifier)
        if parsed.netloc:  # It's a URL
            for site in self.sites.values():
                if site.matches_url(identifier):
                    return site
        else:
            # Check against shortcode, name, or domain
            for site in self.sites.values():
                if site.matches_identifier(identifier):
                    return site
        
        return None
    
    def get_site_by_shortcode(self, shortcode: str) -> Optional[SiteConfiguration]:
        """Get site by shortcode"""
        return self.sites.get(shortcode)
    
    def get_all_sites(self) -> List[SiteConfiguration]:
        """Get all loaded sites"""
        return list(self.sites.values())
    
    def get_sites_requiring_selenium(self) -> List[SiteConfiguration]:
        """Get all sites that require Selenium"""
        return [site for site in self.sites.values() if site.use_selenium]
    
    def reload(self):
        """Reload all site configurations"""
        self.sites.clear()
        self._load_sites()
    
    def generate_global_table(self, term_width: int, output_path: Optional[str] = None):
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
        
        # Use loaded sites instead of manually loading YAML files
        for site in self.sites.values():
            try:
                site_name = site.name
                site_code = site.shortcode
                use_selenium = site.use_selenium
                
                if use_selenium:
                    selenium_sites.add(site_code)
                
                modes_display_list = []
                for mode_name, mode_config in site.modes.items():
                    supports_pagination = mode_config.supports_pagination()
                    mode_url_rules = mode_config.url_encoding_rules
                    has_special_encoding = " & " in str(mode_url_rules) or "&" in str(mode_url_rules)
                    footnotes = []
                    if supports_pagination:
                        footnotes.append("✦")
                        pagination_modes.add(mode_name)
                    if has_special_encoding:
                        footnotes.append("‡")
                        if site_code not in encoding_rule_sites:
                            encoding_rule_sites.add(site_code)
                    mode_display = f"[yellow][bold]{mode_name}[/bold][/yellow]" + (f" {''.join(footnotes)}" if footnotes else "")
                    modes_display_list.append(mode_display)
                
                metadata = site.get_metadata_fields()
                supported_sites.append((site_code, site_name, modes_display_list, metadata, use_selenium))
            except Exception as e:
                logger.warning(f"Failed to process site '{site.shortcode}': {e}")
        
        if supported_sites:
            for site_code, site_name, modes_display_list, metadata, use_selenium in sorted(supported_sites, key=lambda x: x[0]):
                code_display = f"[magenta][bold]{site_code}[/bold][/magenta]"
                site_display = f"[magenta]{site_name}[/magenta]" + (f" †" if use_selenium else "")
                modes_display = " · ".join(modes_display_list) if modes_display_list else "[gray]None[/gray]"
                metadata_display = " · ".join(f"[green][bold]{field}[/bold][/green]" for field in metadata) if metadata else "None"
                table.add_row(code_display, site_display, modes_display, metadata_display)
        else:
            logger.warning("No valid site configs found in sites directory.")
            table.add_row("[magenta][bold]??[/bold][/magenta]", "[magenta]No sites loaded[/magenta]", "[gray]None[/gray]", "None")
        
        # Prepare footnotes
        footnotes = []
        if pagination_modes:
            footnotes.append("✦ [italic]supports [bold][green]pagination[/green][/bold]; see [bold][yellow]optional arguments[/yellow][/bold] below.[/italic]")
        if selenium_sites:
            footnotes.append("† [italic][yellow][bold]selenium[/bold][/yellow] and [yellow][bold]chromedriver[/bold][/yellow] required.[/italic]")
        if encoding_rule_sites:
            footnotes.append("‡ [italic]combine terms with \'&\' to search them together.[/italic]")

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
                md_lines.append("\n✦ _Supports pagination; see optional arguments below._\n")
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
        
        return Group(table, *footnotes) if footnotes else table

