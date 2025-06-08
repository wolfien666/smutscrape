#!/usr/bin/env python3
"""
Utilities Module for Smutscrape

This module contains utility functions for terminal display, ASCII art rendering,
color manipulation, and VPN management.
"""

import os
import re
import random
import subprocess
import time
import string
from urllib.parse import urlparse
from typing import Tuple, Optional, Dict, Any, List
from loguru import logger
from termcolor import colored
from rich.console import Console
from rich.table import Table
from rich.style import Style
from rich.text import Text
import art

# Initialize console for rich output
console = Console()


def get_terminal_width() -> int:
    """Get the terminal width in columns."""
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def color_distance(color1: Tuple[int, int, int], color2: Tuple[int, int, int]) -> float:
    """Calculate perceptual distance between two RGB colors using a simplified CIEDE2000 approach."""
    # Convert to HSV for more perceptual measurement
    hsv1 = rgb_to_hsv(*color1)
    hsv2 = rgb_to_hsv(*color2)
    
    # Calculate hue distance (in degrees, accounting for wrap-around)
    hue_dist = min(abs(hsv1[0] - hsv2[0]), 360 - abs(hsv1[0] - hsv2[0])) / 180.0
    
    # Calculate saturation and value distances
    sat_dist = abs(hsv1[1] - hsv2[1])
    val_dist = abs(hsv1[2] - hsv2[2])
    
    # Weighted combination (hue changes are more noticeable)
    # Scale is 0-1 where 1 is maximum possible distance
    return 0.6 * hue_dist + 0.2 * sat_dist + 0.2 * val_dist


def hsv_to_rgb(h: float, s: float, v: float) -> Tuple[int, int, int]:
    """Convert HSV color to RGB color."""
    if s == 0.0:
        return int(v * 255), int(v * 255), int(v * 255)
    
    i = int(h * 6)
    f = (h * 6) - i
    p = v * (1 - s)
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))
    
    i %= 6
    
    if i == 0:
        r, g, b = v, t, p
    elif i == 1:
        r, g, b = q, v, p
    elif i == 2:
        r, g, b = p, v, t
    elif i == 3:
        r, g, b = p, q, v
    elif i == 4:
        r, g, b = t, p, v
    else:
        r, g, b = v, p, q
    
    return int(r * 255), int(g * 255), int(b * 255)


def rgb_to_hsv(r: int, g: int, b: int) -> Tuple[float, float, float]:
    """Convert RGB color to HSV color."""
    r, g, b = r/255.0, g/255.0, b/255.0
    mx = max(r, g, b)
    mn = min(r, g, b)
    df = mx - mn
    
    if mx == mn:
        h = 0
    elif mx == r:
        h = (60 * ((g-b)/df) + 360) % 360
    elif mx == g:
        h = (60 * ((b-r)/df) + 120) % 360
    elif mx == b:
        h = (60 * ((r-g)/df) + 240) % 360
        
    s = 0 if mx == 0 else df/mx
    v = mx
    
    return h, s, v


def interpolate_color(start_rgb: Tuple[int, int, int], end_rgb: Tuple[int, int, int], 
                     steps: int, current_step: int) -> Tuple[int, int, int]:
    """Interpolate between two RGB colors."""
    r = start_rgb[0] + (end_rgb[0] - start_rgb[0]) * current_step / (steps - 1) if steps > 1 else start_rgb[0]
    g = start_rgb[1] + (end_rgb[1] - start_rgb[1]) * current_step / (steps - 1) if steps > 1 else start_rgb[1]
    b = start_rgb[2] + (end_rgb[2] - start_rgb[2]) * current_step / (steps - 1) if steps > 1 else start_rgb[2]
    return int(r), int(g), int(b)


def generate_adaptive_gradient(num_lines: int) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    """Generate subtle red/purple/pink gradients with HSV fixes."""
    base_gradients = [
        ((94, 38, 95), (199, 62, 119)),     
        ((76, 25, 91), (181, 58, 127)),     
        ((109, 33, 79), (214, 93, 107)),    
        ((126, 35, 58), (228, 116, 112)),   
        ((82, 19, 64), (188, 65, 119)),     
        ((55, 23, 62), (168, 45, 106)),     
        ((139, 0, 55), (255, 105, 97))      
    ]
    
    start_rgb, end_rgb = random.choice(base_gradients)
    start_h, start_s, start_v = rgb_to_hsv(*start_rgb)
    end_h, end_s, end_v = rgb_to_hsv(*end_rgb)
    
    line_factor = min(num_lines / 12, 1.0)
    hue_scale = 0.4 + (line_factor * 0.6)
    sat_scale = 0.8 + (0.3 * line_factor)
    
    hue_diff = ((end_h - start_h + 180) % 360) - 180
    adj_hue_diff = hue_diff * hue_scale
    new_end_h = (start_h + adj_hue_diff) % 360
    
    if 60 < new_end_h < 270:
        new_end_h = 270 if new_end_h > 180 else 60
    
    new_end_s = min(end_s * sat_scale, 0.9)
    new_end_v = end_v * (0.85 + (0.15 * line_factor))
    
    # FIX APPLIED HERE: Normalize hue to 0-1 range
    new_end_rgb = hsv_to_rgb(new_end_h / 360.0, new_end_s, new_end_v)
    
    clamped_rgb = tuple(min(max(v, 0), 255) for v in new_end_rgb)
    return start_rgb, clamped_rgb


def render_ascii(input_text: str, general_config: Dict[str, Any], term_width: int, font: Optional[str] = None) -> bool:
    """Render ASCII art for the given input text using the art library with a specified or random font and gradient.

    Args:
        input_text (str): The text to render as ASCII art.
        general_config (dict): Configuration dictionary containing a list of fonts.
        term_width (int): The width of the terminal in characters.
        font (str, optional): Specific font to use. If None, a random font is selected from the config.

    Returns:
        bool: True if rendering succeeded, False otherwise.
    """
    # Calculate max width (90% of terminal width)
    max_width = int(term_width * 0.9)
    logger.debug(f"Terminal width: {term_width}, Max width (90%): {max_width}")

    # If a specific font is provided, try to use it
    selected_font = None
    art_width = None
    if font:
        try:
            # Test if the font is valid by rendering the text
            art_text = art.text2art(input_text, font=font)
            art_text = art_text.replace("\t", "    ")
            lines = [line.rstrip() for line in art_text.splitlines() if line.strip()]
            if lines:
                max_line_width = max(len(line) for line in lines)
                # logger.debug(f"Specified font '{font}': Unbounded width = {max_line_width}")
                if max_line_width <= max_width:
                    selected_font = font
                    art_width = max_line_width
                    logger.debug(f"Specified font '{font}' fits within max_width {max_width}. Using it.")
                else:
                    logger.debug(f"Specified font '{font}' width {max_line_width} exceeds max_width {max_width}. Falling back to random selection.")
            else:
                logger.debug(f"Specified font '{font}': No valid lines rendered. Falling back to random selection.")
        except Exception as e:
            logger.debug(f"Specified font '{font}' rendering failed: {e}. Falling back to random selection.")

    # If no valid font was specified or the specified font doesn't fit, select a random font
    if not selected_font:
        fonts = general_config.get("fonts", [])
        if not fonts:
            logger.warning("No fonts specified in general_config['fonts']. Falling back to default.")
            fonts = ["standard"]

        # Sample all fonts to get their unbounded width
        font_widths = {}
        for font in fonts:
            try:
                art_text = art.text2art(input_text, font=font)
                art_text = art_text.replace("\t", "    ")
                lines = [line.rstrip() for line in art_text.splitlines() if line.strip()]
                if lines:
                    max_line_width = max(len(line) for line in lines)
                    font_widths[font] = max_line_width
                    # logger.debug(f"Font '{font}': Unbounded width = {max_line_width}")
            except Exception as e:
                logger.debug(f"Font '{font}' rendering failed: {e}, skipping.")
                continue

        if not font_widths:
            # logger.warning("No valid fonts found. Using fallback.")
            selected_font = "standard"
            art_width = len(input_text)
        else:
            # Filter fonts that fit within max_width
            qualifying_fonts = [(font, width) for font, width in font_widths.items() if width <= max_width]
            # logger.debug(f"Qualifying fonts (width <= {max_width}): {qualifying_fonts}")
            
            if not qualifying_fonts:
                # If no qualifying fonts, use the narrowest available
                qualifying_fonts = sorted(font_widths.items(), key=lambda x: x[1])
                selected_font, art_width = qualifying_fonts[0]
                logger.debug(f"No fonts fit within {max_width} characters. Using narrowest available: '{selected_font}' with width {art_width}")
            else:
                # Simply take the largest qualifying font
                sorted_fonts = sorted(qualifying_fonts, key=lambda x: x[1], reverse=True)
                selected_font, art_width = sorted_fonts[0]
                logger.debug(f"Selected largest qualifying font: '{selected_font}' with width {art_width}")

    # Render final art with the selected font
    try:
        art_text = art.text2art(input_text, font=selected_font)
        art_text = art_text.replace("\t", "    ")
        lines = [line.rstrip() for line in art_text.splitlines() if line.strip()]
        # logger.debug(f"Raw lines before trimming: {[line for line in lines]}")
    except Exception as e:
        logger.error(f"Failed to render ASCII art with font '{selected_font}': {e}")
        return False
    
    # Trim each line to max_width
    final_lines = []
    for line in lines:
        line_width = len(line)
        if line_width > max_width:
            # logger.debug(f"Line '{line}' width {line_width} exceeds max_width {max_width}. Trimming.")
            final_lines.append(line[:max_width])
        else:
            final_lines.append(line)
        #logger.debug(f"Line width after trimming: {len(final_lines[-1])}, Line: '{final_lines[-1]}'")
    art_width = max(len(line) for line in final_lines) if final_lines else len(input_text)
    logger.debug(f"Adjusted art_width: {art_width}")

    # Pad lines to art_width for consistent centering
    final_lines = [line.ljust(art_width) for line in final_lines]

    # Center the art
    left_padding = (term_width - art_width) // 2 if art_width < term_width else 0
    centered_lines = [" " * left_padding + line for line in final_lines]
    logger.debug(f"Art centered with padding: {left_padding}, Total lines: {len(centered_lines)}, Final width: {art_width}")

    # Apply adaptive gradient
    start_rgb, end_rgb = generate_adaptive_gradient(len(centered_lines))
    logger.debug(f"start_rgb: {start_rgb}, end_rgb: {end_rgb}")
    steps = len(centered_lines)

    for i, line in enumerate(centered_lines):
        if steps > 1:
            rgb = interpolate_color(start_rgb, end_rgb, steps, i)
        else:
            rgb = start_rgb
        style = Style(color=f"rgb({rgb[0]},{rgb[1]},{rgb[2]})", bold=True)
        text = Text(line, style=style)
        console.print(text, justify="left", overflow="crop", no_wrap=True)

    return True


def display_options():
    """Display command-line options."""
    console.print("[bold][yellow]optional arguments:[/yellow][/bold]")
    console.print("  [magenta]-o[/magenta], [magenta]--overwrite[/magenta]               replace files with same name at download destination")
    console.print("  [magenta]-n[/magenta], [magenta]--re_nfo[/magenta]                  replace metadata in existing .nfo files")
    console.print("  [magenta]-a[/magenta], [magenta]--applystate[/magenta]              add URLs to .state if file already present")
    console.print("  [magenta]-p[/magenta], [magenta]--page[/magenta] [yellow]{ pg. }.{ vid. }[/yellow]   start scraping on given page of results")
    console.print("  [magenta]-t[/magenta], [magenta]--table[/magenta] [yellow]{ path }[/yellow]          output table of current site configurations")
    console.print("  [magenta]-d[/magenta], [magenta]--debug[/magenta]                   enable detailed debug logging")
    console.print("  [magenta]-h[/magenta], [magenta]--help[/magenta]                    show help submenu")


def display_global_examples(site_dir: str):
    """Display random examples from all sites."""
    import yaml
    
    console.print("[yellow][bold]examples[/bold] (generated from ./sites/):[/yellow]")
    
    # Collect all site/mode/example combos
    all_examples = []
    for site_config_file in os.listdir(site_dir):
        if site_config_file.endswith(".yaml"):
            try:
                with open(os.path.join(site_dir, site_config_file), 'r') as f:
                    site_config = yaml.safe_load(f)
                site_name = site_config.get("name", "Unknown")
                shortcode = site_config.get("shortcode", "??")
                modes = site_config.get("modes", {})
                for mode, config in modes.items():
                    tip = config.get("tip", "No description available")
                    examples = config.get("examples", ["N/A"])
                    for example in examples:
                        all_examples.append((site_name, shortcode, mode, tip, example))
            except Exception as e:
                logger.warning(f"Failed to load config '{site_config_file}': {e}")
    
    # Randomly select up to 10 examples
    selected_examples = random.sample(all_examples, min(10, len(all_examples))) if all_examples else []
    
    # Display in a borderless table
    table = Table(show_edge=False, expand=True, show_lines=False, show_header=True)
    table.add_column("[magenta][bold]command[/bold][/magenta]", justify="right")
    table.add_column("[yellow]action[/yellow]", justify="left")
    
    for site_name, shortcode, mode, tip, example in selected_examples:
        cmd = f"[red]scrape[/red] [magenta]{shortcode}[/magenta] [yellow]{mode}[/yellow] [blue]\"{example}\"[/blue]"
        effect = f"{tip} [blue]\"{example}\"[/blue] on [magenta]{site_name}[/magenta]"
        table.add_row(cmd, effect)
    
    console.print(table)
    console.print()


def display_usage(term_width: int, global_table):
    """Display usage information with the sites table."""
    console.print("usage: [red]scrape[/red] [magenta]{site}[/magenta] [yellow]{mode}[/yellow] [blue]{query}[/blue]")
    console.print("       [red]scrape[/red] [blue]{url}[/blue]")
    console.print()
    console.print("[yellow][bold]supported sites[/bold] (loaded from ./sites/):[/yellow]")
    console.print()
    console.print(global_table)  # Print the table object
    console.print()
    console.print()
    # Note: display_global_examples and display_options need to be called separately


# ============================================================================
# URL and Text Processing Utilities
# ============================================================================

def is_url(string: str) -> bool:
    """Check if a string is a URL by parsing it with urlparse."""
    parsed = urlparse(string)
    # A string is considered a URL if it has a netloc (domain) or a scheme
    return bool(parsed.netloc) or bool(parsed.scheme)


def process_title(title: str, invalid_chars: List[str]) -> str:
    """Process title by removing invalid characters."""
    logger.debug(f"Processing {title} for invalid chars...")
    for char in invalid_chars:
        title = title.replace(char, "")
    logger.debug(f"Processed title: {title}")
    return title


def custom_title_case(text: str, uppercase_list: Optional[List[str]] = None, 
                     preserve_mixed_case: bool = False) -> str:
    """Apply custom title casing with exact match overrides from uppercase_list."""
    if not text:
        return text
    uppercase_list = uppercase_list or []
    
    # If preserving mixed case (e.g., "McFly") and not in uppercase_list, return as-is
    if preserve_mixed_case and re.search(r'[a-z][A-Z]|[A-Z][a-z]', text) and text.lower() not in {u.lower() for u in uppercase_list}:
        return text
    
    # Build a case-insensitive mapping of overrides to their exact form
    override_map = {term.lower(): term for term in uppercase_list}
    
    # Split into words
    words = text.split()
    if not words:
        # Single word: check for override match
        text_lower = text.lower()
        return override_map.get(text_lower, text.title())
    
    # Process each word
    result = []
    for word in words:
        word_lower = word.lower()
        if word_lower in override_map:
            result.append(override_map[word_lower])  # Use exact form (e.g., "BrutalX")
        else:
            result.append(word.title() if not preserve_mixed_case or len(words) > 1 else word)
    
    final_text = ' '.join(result)
    return final_text


def construct_filename(title: str, site_config: Dict[str, Any], 
                      general_config: Dict[str, Any]) -> str:
    """Construct a filename from title and configuration parameters."""
    prefix = site_config.get('name_prefix', '')
    suffix = site_config.get('name_suffix', '')
    extension = general_config['file_naming']['extension']
    invalid_chars = general_config['file_naming']['invalid_chars']
    max_chars = general_config['file_naming'].get('max_chars', 255)  # Default to 255 if not specified
    
    # Get unique name settings - use boolean values to handle YAML's various ways of representing true/false
    unique_name = bool(site_config.get("unique_name", False))
    make_unique = bool(general_config['file_naming'].get('make_unique', False))
    
    # Process title by removing invalid characters
    processed_title = process_title(title, invalid_chars)
    
    # Generate a unique ID if needed (6 random characters)
    unique_id = '_' + ''.join(random.choices(string.ascii_lowercase + string.ascii_uppercase + string.digits, k=6)) if unique_name or make_unique else ''
    
    # Calculate available length for the title, accounting for the unique ID if present
    fixed_length = len(prefix) + len(suffix) + len(extension) + len(unique_id)
    max_title_chars = min(max_chars, 255) - fixed_length  # Hard cap at 255 chars total
    
    if max_title_chars <= 0:
        logger.warning(f"Fixed filename parts ({fixed_length} chars) exceed max_chars ({max_chars}); truncating to fit.")
        max_title_chars = max(1, 255 - fixed_length)  # Ensure at least 1 char for title if possible
    
    # Truncate title if necessary
    if len(processed_title) > max_title_chars:
        processed_title = processed_title[:max_title_chars].rstrip()
        logger.debug(f"Truncated title to {max_title_chars} chars: {processed_title}")
    
    # Construct final filename with unique ID before extension
    if unique_id:
        filename = f"{prefix}{processed_title}{suffix}{unique_id}{extension}"
    else:
        filename = f"{prefix}{processed_title}{suffix}{extension}"
    
    # Double-check byte length (Linux limit is 255 bytes, not chars)
    while len(filename.encode('utf-8')) > 255:
        excess = len(filename.encode('utf-8')) - 255
        trim_chars = excess // 4 + 1  # Rough estimate for UTF-8; adjust conservatively
        processed_title = processed_title[:-trim_chars].rstrip()
        
        # Reconstruct the filename with the trimmed title
        if unique_id:
            filename = f"{prefix}{processed_title}{suffix}{unique_id}{extension}"
        else:
            filename = f"{prefix}{processed_title}{suffix}{extension}"
            
        logger.debug(f"Filename exceeded 255 bytes; trimmed to: {filename}")

    logger.debug(f"Generated filename: {filename}")
    return filename


def should_ignore_video(data: Dict[str, Any], ignored_terms: List[str]) -> bool:
    """Check if video should be ignored based on metadata and ignored terms."""
    if not ignored_terms:
        return False
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
                    logger.warning(f"Ignoring video due to term '{term}' in {field}: '{value}'")
                    return True
        elif isinstance(value, list):
            for item in value:
                item_lower = item.lower()
                for term, term_pattern, encoded_pattern in zip(ignored_terms_lower, term_patterns, encoded_patterns):
                    if term_pattern.search(item_lower) or encoded_pattern.search(item_lower):
                        logger.warning(f"Ignoring video due to term '{term}' in {field}: '{item}'")
                        return True
    return False


# ============================================================================
# URL Pattern Processing Utilities
# ============================================================================

def parse_url_pattern(pattern: str) -> List[Dict[str, Any]]:
    """Parse URL pattern into components."""
    components = []
    current_segment = ""
    
    i = 0
    while i < len(pattern):
        if pattern[i] == "{":
            if current_segment:
                components.append({"type": "static", "value": current_segment})
                current_segment = ""
            j = i + 1
            while j < len(pattern) and pattern[j] != "}":
                j += 1
            if j < len(pattern):
                placeholder = pattern[i+1:j]
                components.append({"type": "wildcard", "name": placeholder, "numeric": placeholder == "page"})
                i = j + 1
            else:
                raise ValueError(f"Unclosed placeholder in pattern: {pattern}")
        else:
            current_segment += pattern[i]
            i += 1
    
    if current_segment:
        components.append({"type": "static", "value": current_segment})
    
    logger.debug(f"Parsed pattern '{pattern}' into components: {components}")
    return components


def pattern_to_regex(pattern: str) -> Tuple[re.Pattern, int, int]:
    """Convert URL pattern to regex with static count and length."""
    regex = ""
    static_count = 0
    static_length = 0
    in_wildcard = False
    current_static = ""
    numeric_wildcards = {"page"}
    
    for char in pattern.rstrip("/"):
        if char == "{":
            if current_static:
                regex += re.escape(current_static)
                static_count += 1
                static_length += len(current_static)
                current_static = ""
            in_wildcard = True
            wildcard_name = ""
        elif char == "}":
            if in_wildcard:
                if wildcard_name in numeric_wildcards:
                    regex += f"(?P<{wildcard_name}>\\d+)"
                else:
                    regex += f"(?P<{wildcard_name}>[^/?&#]+)"
                in_wildcard = False
            else:
                current_static += char
        elif in_wildcard:
            wildcard_name += char
        else:
            current_static += char
    
    if current_static:
        regex += re.escape(current_static)
        static_count += 1
        static_length += len(current_static)
    
    if "?" not in pattern and "&" not in pattern:
        regex = f"^{regex}$"
    else:
        regex = f"^{regex}(?:$|&.*)"
    
    return re.compile(regex, re.IGNORECASE), static_count, static_length


#

# ============================================================================
# VPN Management
# ============================================================================

def handle_vpn(general_config: Dict[str, Any], action: str = 'start') -> Optional[float]:
    """Handle VPN operations (start, stop, new_node).
    
    Args:
        general_config: Configuration dictionary containing VPN settings
        action: The VPN action to perform ('start', 'stop', 'new_node')
        
    Returns:
        Current timestamp if successful, None otherwise
    """
    vpn_config = general_config.get('vpn', {})
    if not vpn_config.get('enabled', False):
        return None
        
    vpn_bin = vpn_config.get('vpn_bin', '')
    cmd = vpn_config.get(f"{action}_cmd", '').format(vpn_bin=vpn_bin)
    
    try:
        subprocess.run(cmd, shell=True, check=True)
        current_time = time.time()
        logger.info(f"VPN {action} executed")
        return current_time
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed VPN {action}: {e}")
        return None 