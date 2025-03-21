#!/usr/bin/env python3
"""
Font Preview Script

This script displays a text string in all fonts listed in config.yaml,
sorted from widest to narrowest, with the font name above each rendering.

Usage:
    python font_preview.py "Your text here"
"""

import sys
import yaml
import art
from rich.console import Console
from rich.text import Text
from rich.style import Style
import random
import os
import math

console = Console()

def load_config():
    """Load configuration from config.yaml file."""
    try:
        with open("config.yaml", "r") as file:
            config = yaml.safe_load(file)
        return config
    except Exception as e:
        console.print(f"[bold red]Error loading config.yaml: {e}[/bold red]")
        sys.exit(1)

def measure_font_width(text, font):
    """Measure the maximum width of text rendered in a specific font."""
    try:
        art_text = art.text2art(text, font=font)
        art_text = art_text.replace("\t", "    ")
        lines = [line.rstrip() for line in art_text.splitlines() if line.strip()]
        if lines:
            return max(len(line) for line in lines)
        return 0
    except Exception as e:
        console.print(f"[bold yellow]Warning: Font '{font}' rendering failed: {e}[/bold yellow]")
        return 0

def hsv_to_rgb(h, s, v):
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

def rgb_to_hsv(r, g, b):
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

def interpolate_color(start_rgb, end_rgb, steps, current_step):
    """Interpolate between two RGB colors."""
    r = start_rgb[0] + (end_rgb[0] - start_rgb[0]) * current_step / (steps - 1) if steps > 1 else start_rgb[0]
    g = start_rgb[1] + (end_rgb[1] - start_rgb[1]) * current_step / (steps - 1) if steps > 1 else start_rgb[1]
    b = start_rgb[2] + (end_rgb[2] - start_rgb[2]) * current_step / (steps - 1) if steps > 1 else start_rgb[2]
    return int(r), int(g), int(b)

def generate_adaptive_gradient(num_lines):
    """Generate a gradient pair with intensity adapted to the number of lines."""
    # Base gradient pairs
    base_gradients = [
        ((255, 165, 0), (255, 105, 180)),  # Orange to Pink
        ((0, 0, 255), (255, 0, 0)),        # Blue to Red
        ((75, 0, 130), (238, 130, 238)),   # Indigo to Violet
        ((255, 215, 0), (255, 69, 0)),     # Gold to Red-Orange
        ((0, 191, 255), (138, 43, 226)),   # Deep Sky Blue to Blue Violet
        ((50, 205, 50), (0, 191, 255)),    # Lime Green to Deep Sky Blue
    ]
    
    # Choose a base gradient
    start_rgb, end_rgb = random.choice(base_gradients)
    
    # Convert to HSV for easier manipulation
    start_hsv = rgb_to_hsv(*start_rgb)
    end_hsv = rgb_to_hsv(*end_rgb)
    
    # Calculate how much to scale the gradient based on line count
    # More lines = more spectrum coverage, fewer lines = less coverage
    
    # For very short ASCII art (1-3 lines), use a very subtle gradient
    if num_lines <= 3:
        # Scale down the hue difference for short ASCII art
        hue_diff = (end_hsv[0] - start_hsv[0]) % 360
        if hue_diff > 180:
            hue_diff = 360 - hue_diff
        
        # Reduce the hue difference based on line count
        scale_factor = 0.2 + (num_lines / 10)  # 0.3 for 1 line, 0.4 for 2 lines, 0.5 for 3 lines
        new_hue_diff = hue_diff * scale_factor
        
        # Calculate new end hue
        new_end_hue = (start_hsv[0] + (new_hue_diff if hue_diff < 180 else -new_hue_diff)) % 360
        
        # Create new end color with scaled hue but original saturation and value
        new_end_hsv = (new_end_hue, end_hsv[1], end_hsv[2])
        new_end_rgb = hsv_to_rgb(*new_end_hsv)
        
        return start_rgb, new_end_rgb
    
    # For medium ASCII art (4-7 lines), use a moderate gradient
    elif num_lines <= 7:
        # Use the original gradient but maybe with slightly reduced intensity
        return start_rgb, end_rgb
    
    # For large ASCII art (8+ lines), can use full gradient or even enhanced
    else:
        # For large ASCII art, we can use the full gradient or even enhance it
        # by increasing saturation or value contrast if desired
        return start_rgb, end_rgb

def render_text_in_font(text, font):
    """Render text in the specified font with a color gradient and center it properly."""
    try:
        art_text = art.text2art(text, font=font)
        art_text = art_text.replace("\t", "    ")
        lines = [line.rstrip() for line in art_text.splitlines() if line.strip()]
        
        if not lines:
            console.print(f"[bold yellow]Warning: Font '{font}' produced no output[/bold yellow]")
            return
        
        # Get terminal width
        term_width = os.get_terminal_size().columns
        
        # Print font name header
        font_header = f" {font} "
        left_pad = "─" * ((term_width - len(font_header)) // 2)
        right_pad = "─" * (term_width - len(left_pad) - len(font_header))
        
        console.print(f"[bold cyan]{left_pad}{font_header}{right_pad}[/bold cyan]")
        
        # Find the maximum width of the ASCII art
        max_width = max(len(line) for line in lines)
        
        # Generate adaptive gradient colors based on line count
        start_rgb, end_rgb = generate_adaptive_gradient(len(lines))
        steps = len(lines)
        
        # Calculate center padding once
        center_padding = (term_width - max_width) // 2
        
        # Apply gradient to each line and center it properly
        for i, line in enumerate(lines):
            # Pad the line to max_width to ensure consistent centering
            padded_line = line.ljust(max_width)
            # Add center padding
            centered_line = " " * center_padding + padded_line
            
            # Apply gradient color
            rgb = interpolate_color(start_rgb, end_rgb, steps, i)
            style = Style(color=f"rgb({rgb[0]},{rgb[1]},{rgb[2]})", bold=True)
            text = Text(centered_line, style=style)
            console.print(text)
        
        # Print the width information (centered)
        width_info = f"Width: {max_width} characters"
        padding = (term_width - len(width_info)) // 2
        console.print(" " * padding + f"[dim]{width_info}[/dim]")
        console.print()  # Empty line for spacing
        
    except Exception as e:
        console.print(f"[bold red]Error rendering '{font}': {e}[/bold red]")

def main():
    if len(sys.argv) < 2:
        console.print("[bold red]Error: Please provide text to render.[/bold red]")
        console.print(f"Usage: python {sys.argv[0]} \"Your text here\"")
        sys.exit(1)
    
    text = sys.argv[1]
    config = load_config()
    
    # Get fonts directly from the top-level "fonts" key
    fonts = config.get("fonts", [])
    if not fonts:
        console.print("[bold red]Error: No fonts found in config.yaml[/bold red]")
        console.print("Make sure your config.yaml has a 'fonts' list at the top level.")
        sys.exit(1)
    
    # Clean up any trailing characters from font names
    fonts = [font.strip() for font in fonts]
    
    console.print(f"[bold green]Previewing text: '{text}' in {len(fonts)} fonts[/bold green]")
    console.print()
    
    # Measure width of each font
    font_widths = {}
    for font in fonts:
        width = measure_font_width(text, font)
        if width > 0:
            font_widths[font] = width
    
    # Sort fonts by width (widest first)
    sorted_fonts = sorted(font_widths.items(), key=lambda x: x[1], reverse=True)
    
    # Render text in each font
    for font, width in sorted_fonts:
        render_text_in_font(text, font)
    
    # Print summary
    console.print("[bold green]Font Preview Complete[/bold green]")
    console.print(f"Displayed {len(sorted_fonts)} fonts from widest to narrowest")

if __name__ == "__main__":
    main()

