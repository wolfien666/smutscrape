#!/usr/bin/env python3
"""
Command Line Interface Module for Smutscrape

This module handles all CLI argument parsing, command processing,
and user interface logic for the Smutscrape application.
"""

import argparse
import sys
import os
from loguru import logger
from rich.style import Style

# Import core functionality
from config import ConfigManager
from smutscrape.session import SessionManager
from smutscrape.utilities import (
    get_terminal_width, render_ascii, display_options, 
    display_global_examples, display_usage, handle_vpn, console,
    is_url
)
from smutscrape.core import process_url
from smutscrape.sites import SiteConfiguration

# Global manager instances
config_manager = None
session_manager = None

def get_config_manager():
    """Get or create the configuration manager instance."""
    global config_manager
    if config_manager is None:
        config_manager = ConfigManager(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    return config_manager

def get_session_manager():
    """Get or create the session manager instance."""
    global session_manager
    if session_manager is None:
        script_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        state_file = os.path.join(script_dir, '.state')
        session_manager = SessionManager(state_file)
    return session_manager

def get_site_manager():
    """Get the site manager instance via config manager."""
    return get_config_manager().site_manager

def load_configuration(config_type='general', identifier=None):
    """Load general or site-specific configuration based on identifier type."""
    if config_type == 'general':
        return get_config_manager().general_config
    elif config_type == 'site':
        if not identifier:
            raise ValueError("Site identifier required for site config loading")
        return get_config_manager().get_site_config(identifier)
    else:
        raise ValueError(f"Unknown config type: {config_type}")

def get_available_modes(site_config):
    """Return a list of available scrape modes for a site config, excluding 'video'."""
    # If it's a SiteConfiguration object, use its method
    if isinstance(site_config, SiteConfiguration):
        return site_config.get_available_modes(exclude_video=True)
    
    # Backward compatibility for dict configs
    return [m for m in site_config.get("modes", {}).keys() if m != "video"]

def cleanup(general_config):
    """Clean up resources like Selenium driver."""
    get_config_manager().cleanup()
    print()

def handle_single_arg(arg, general_config, args, term_width, state_set):
    """Handle single argument processing (URL or site identifier)."""
    is_url_flag = is_url(arg)
    config = load_configuration('site', arg)
    if config:
        # Configuration loaded successfully
        if is_url_flag:
            # Check for Selenium availability if needed
            try:
                from selenium import webdriver
                SELENIUM_AVAILABLE = True
            except ImportError:
                SELENIUM_AVAILABLE = False
                
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
            get_config_manager().download_manager.process_fallback_download(arg, args.overwrite)
        else:
            logger.error(f"Could not match the provided argument '{arg}' to a site configuration.")
            sys.exit(1)

def handle_multi_arg(args, general_config, args_obj, state_set):
    """Handle multi-argument processing (site mode query)."""
    from urllib.parse import urlparse
    from smutscrape.core import construct_url
    
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
    
    # Check for Selenium availability if needed
    try:
        from selenium import webdriver
        SELENIUM_AVAILABLE = True
    except ImportError:
        SELENIUM_AVAILABLE = False
        
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

    # Import the processing functions
    from smutscrape.core import process_video_page, process_rss_feed, process_list_page
    import time

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
    """Main CLI entry point."""
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

    args = parser.parse_args()
    
    # CLI mode processing
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
    
    # Load state once at startup using session manager
    state_set = get_session_manager().processed_urls
    logger.debug(f"Loaded {len(state_set)} URLs from state file")
    
    print()
    render_ascii("Smutscrape", general_config, term_width)
    
    if args.table:
        get_site_manager().generate_global_table(term_width, output_path=args.table)
        logger.info(f"Generated site table at '{args.table}'")
        sys.exit(0)
    
    if not args.args:
        print()
        global_table = get_site_manager().generate_global_table(term_width)
        script_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        site_dir = os.path.join(script_dir, 'sites')
        display_usage(term_width, global_table)
        display_global_examples(site_dir)
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
            global_table = get_site_manager().generate_global_table(term_width)
            script_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
            site_dir = os.path.join(script_dir, 'sites')
            display_usage(term_width, global_table)
            display_global_examples(site_dir)
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
