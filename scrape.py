#!/usr/bin/env python3
"""
Smutscrape - Main Entry Point

This is the main entry point for the Smutscrape application.
It routes between CLI mode and API server mode based on the --server flag.
"""

import sys

def main():
    """Route to appropriate mode based on command line arguments."""
    # Check if we're in server mode early (before full argument parsing)
    if "--server" in sys.argv or "-s" in sys.argv:
        from smutscrape.api import main as api_main
        api_main()
    else:
        from smutscrape.cli import main as cli_main
        cli_main()

if __name__ == "__main__":
	main()
