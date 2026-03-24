#!/usr/bin/env python3
"""
Configuration Manager for Smutscrape
"""
import os
import re
import yaml
from loguru import logger


class ConfigManager:
    """Manages the general configuration for Smutscrape."""

    def __init__(self, script_dir: str = None):
        self._script_dir = script_dir or os.path.dirname(os.path.realpath(__file__))
        self._config_path = self._find_config()
        self._general_config = None
        self._selenium_driver = None
        self._site_manager = None
        self._download_manager = None

    def _find_config(self) -> str:
        candidates = [
            os.path.join(self._script_dir, 'config.yaml'),
            os.path.join(os.path.expanduser('~'), '.smutscrape', 'config.yaml'),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return candidates[0]

    # ------------------------------------------------------------------
    # YAML loader with Windows backslash-path fix
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_yaml_load(path: str) -> dict:
        """
        Load a YAML file safely on all platforms.

        On Windows, paths like ``"R:\\smutscrape\\inc"`` inside double-quoted
        YAML strings trigger ``unknown escape character`` errors because YAML
        treats backslash as an escape.  Strategy:

        1. Try ``yaml.safe_load`` normally (fast path).
        2. On failure, convert all double-quoted strings that contain backslashes
           to single-quoted strings (where backslashes are literal) and retry.
        """
        with open(path, 'r', encoding='utf-8') as fh:
            raw = fh.read()

        try:
            return yaml.safe_load(raw)
        except yaml.YAMLError:
            pass

        def _dq_to_sq(m):
            inner = m.group(1)
            if "'" in inner:
                return m.group(0)          # can't safely single-quote, leave alone
            inner_fixed = inner.replace('\\\\', '\\')
            return f"'{inner_fixed}'"

        fixed = re.sub(r'"((?:[^"\\]|\\.)*)"', _dq_to_sq, raw)
        try:
            result = yaml.safe_load(fixed)
            logger.warning(
                f"[CONFIG] Loaded '{path}' after fixing Windows backslash escapes. "
                "Use forward slashes or single-quoted strings in config.yaml to avoid this."
            )
            return result
        except yaml.YAMLError as e:
            logger.error(f"Failed to load general config from '{path}': {e}")
            raise

    # ------------------------------------------------------------------
    # general_config property
    # ------------------------------------------------------------------
    @property
    def general_config(self) -> dict:
        if self._general_config is None:
            self._load_general_config()
        return self._general_config

    def _load_general_config(self):
        try:
            self._general_config = self._safe_yaml_load(self._config_path)
            logger.debug(f"Loaded general config from '{self._config_path}'")
        except FileNotFoundError:
            logger.error(
                f"Config file not found: '{self._config_path}'. "
                "Copy example-config.yaml to config.yaml and edit it."
            )
            raise

    # ------------------------------------------------------------------
    # site_manager property
    # ------------------------------------------------------------------
    @property
    def site_manager(self):
        if self._site_manager is None:
            from smutscrape.sites import SiteManager
            sites_dir = os.path.join(self._script_dir, 'sites')
            self._site_manager = SiteManager(sites_dir)
        return self._site_manager

    def get_site_config(self, identifier: str):
        """Return the raw dict config for a site by shortcode, name, or URL."""
        site_obj = self.site_manager.get_site_by_identifier(identifier)
        if site_obj:
            return site_obj.to_dict()
        return None

    # ------------------------------------------------------------------
    # download_manager property (lazy, for yt-dlp fallback)
    # ------------------------------------------------------------------
    @property
    def download_manager(self):
        if self._download_manager is None:
            from smutscrape.downloader import DownloadManager
            self._download_manager = DownloadManager(self.general_config)
        return self._download_manager

    # ------------------------------------------------------------------
    # Selenium driver
    # ------------------------------------------------------------------
    def get_selenium_driver(self, force_new: bool = False):
        """Initialize and return a Selenium WebDriver instance."""
        if self._selenium_driver is not None and not force_new:
            return self._selenium_driver

        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        selenium_config = self.general_config.get('selenium', {})
        mode = selenium_config.get('mode', 'local')

        driver = None
        if mode == 'remote':
            host = selenium_config.get('host', '127.0.0.1')
            port = selenium_config.get('port', '4444')
            remote_url = f"http://{host}:{port}/wd/hub"
            try:
                driver = webdriver.Remote(command_executor=remote_url, options=chrome_options)
                logger.debug(f"Connected to remote Selenium at {remote_url}")
            except Exception as e:
                logger.error(f"Failed to connect to remote Selenium at {remote_url}: {e}")
                return None
        else:
            chromedriver_path = selenium_config.get('chromedriver_path')
            chrome_binary     = selenium_config.get('chrome_binary')

            if chrome_binary:
                chrome_options.binary_location = chrome_binary

            if chromedriver_path:
                service = Service(executable_path=chromedriver_path)
                try:
                    driver = webdriver.Chrome(service=service, options=chrome_options)
                except Exception as e:
                    logger.error(f"Failed to initialize Selenium driver with explicit path '{chromedriver_path}': {e}")
                    return None
            else:
                try:
                    logger.debug("Using webdriver_manager to fetch ChromeDriver")
                    from webdriver_manager.chrome import ChromeDriverManager
                    service = Service(ChromeDriverManager().install())
                    driver = webdriver.Chrome(service=service, options=chrome_options)
                except Exception:
                    try:
                        driver = webdriver.Chrome(options=chrome_options)
                    except Exception as e:
                        logger.error(f"Failed to initialize Selenium driver: {e}")
                        return None

        if driver:
            try:
                logger.debug(f"Initialized Selenium driver with Chrome version: {driver.capabilities.get('browserVersion', 'unknown')}")
                logger.debug(f"Selenium User-Agent: {driver.execute_script('return navigator.userAgent;')}")
            except Exception:
                pass
            self._selenium_driver = driver

        return driver

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def cleanup(self):
        """Release resources (Selenium driver, etc.)."""
        if self._selenium_driver is not None:
            try:
                self._selenium_driver.quit()
                logger.debug("Selenium driver closed.")
            except Exception:
                pass
            self._selenium_driver = None
