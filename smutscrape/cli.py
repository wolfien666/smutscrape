#!/usr/bin/env python3
"""
Command Line Interface Module for Smutscrape
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
from smutscrape.core import process_url, process_list_page, process_video_page
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
    if isinstance(site_config, SiteConfiguration):
        return site_config.get_available_modes(exclude_video=True)
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
        if is_url_flag:
            console.print("═" * term_width, style=Style(color="yellow"))
            console.print()
            render_ascii(config.get("domain", "unknown"), general_config, term_width)
            console.print()
            # Pass filters to process_url
            process_url(arg, config, general_config, args.overwrite, args.re_nfo, args.page, apply_state=args.applystate, state_set=state_set, after_date=args.after, min_duration=args.min_duration)
        else:
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

    mode = args[1]
    identifier = " ".join(args[2:]) if len(args) > 2 else ""

    if mode not in site_config.get('modes', {}):
        logger.error(f"Unsupported mode '{mode}' for site '{args[0]}'")
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
    
    # Construct URL logic... (simplified)
    kwargs_for_url = {mode: identifier}
    if page_num > 1: kwargs_for_url["page"] = page_num
    
    constructed_url = construct_url(
        site_config["base_url"],
        mode_config["url_pattern_pages"] if page_num > 1 and "url_pattern_pages" in mode_config else mode_config["url_pattern"],
        site_config,
        mode=mode,
        **kwargs_for_url
    )
    
    if mode == 'video':
        process_video_page(constructed_url, site_config, general_config, args_obj.overwrite, general_config.get('headers', {}), args_obj.re_nfo, apply_state=args_obj.applystate, state_set=state_set)
    else:
        current_url_to_process = constructed_url
        current_page_num_for_list = page_num
        current_video_offset_for_list = video_offset
        
        while current_url_to_process:
            next_page_url, next_page_number, page_processed_successfully = process_list_page(
                current_url_to_process, site_config, general_config, 
                current_page_num_for_list, current_video_offset_for_list,
                mode, identifier, args_obj.overwrite, general_config.get('headers', {}), 
                args_obj.re_nfo, apply_state=args_obj.applystate, state_set=state_set,
                after_date=args_obj.after, min_duration=args_obj.min_duration
            )
            current_video_offset_for_list = 0 
            current_url_to_process = next_page_url
            if next_page_number: current_page_num_for_list = next_page_number
            else: current_url_to_process = None
            if current_url_to_process:
                import time
                time.sleep(general_config['sleep']['between_pages'])

def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Smutscrape: Scrape and download adult content.")
    parser.add_argument("args", nargs="*", help="Site shortcode/mode/query or URL.")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable detailed debug logging.")
    parser.add_argument("-o", "--overwrite", action="store_true", help="Overwrite existing video files.")
    parser.add_argument("-n", "--re_nfo", action="store_true", help="Regenerate .nfo files.")
    parser.add_argument("-p", "--page", type=str, default="1", help="Start from page.number.")
    parser.add_argument("-a", "--applystate", action="store_true", help="Apply state.")
    parser.add_argument("-A", "--after", type=str, help="Filter videos uploaded after YYYY-MM-DD.")
    parser.add_argument("-D", "--min-duration", type=float, help="Filter videos longer than X minutes.")
    parser.add_argument("--gui", action="store_true", help="Launch the graphical user interface.")

    args = parser.parse_args()
    
    if args.gui:
        from smutscrape.gui import launch_gui
        launch_gui()
        return

    log_level = "DEBUG" if args.debug else "INFO"
    logger.remove()
    logger.add(sys.stderr, level=log_level)
    
    general_config = load_configuration('general')
    state_set = get_session_manager().processed_urls
    term_width = get_terminal_width()
    
    page_parts = args.page.split('.')
    args.page_num = int(page_parts[0])
    args.video_offset = int(page_parts[1]) if len(page_parts) > 1 else 0
    
    if len(args.args) == 1:
        handle_single_arg(args.args[0], general_config, args, term_width, state_set)
    elif len(args.args) >= 2:
        handle_multi_arg(args.args, general_config, args, state_set)
    else:
        display_usage(term_width, get_site_manager().generate_global_table(term_width))

if __name__ == "__main__":
    main()
