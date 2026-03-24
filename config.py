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

    def __init__(self, config_path: str = None):
        self._config_path = config_path or self._find_config()
        self._general_config = None
        self._selenium_driver = None

    def _find_config(self) -> str:
        candidates = [
            os.path.join(os.path.dirname(os.path.realpath(__file__)), 'config.yaml'),
            os.path.join(os.path.expanduser('~'), '.smutscrape', 'config.yaml'),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return candidates[0]

    @staticmethod
    def _safe_yaml_load(path: str) -> dict:
        """
        Load a YAML file safely on all platforms.

        On Windows, users often write download paths with raw backslashes inside
        double-quoted YAML strings, e.g.::

            path: "R:\\smutscrape\\videos"

        YAML treats backslash as an escape character inside double-quoted strings,
        so ``\\i`` (as in ``\\inc``) triggers ``unknown escape character 'i'``.

        Strategy:
          1. Try ``yaml.safe_load`` as-is (fast path, works on Linux/macOS).
          2. On ``ScannerError``, read the raw text, convert every
             double-quoted value that contains a backslash to use
             a YAML single-quoted string (where backslashes are literal),
             then retry.
        """
        with open(path, 'r', encoding='utf-8') as fh:
            raw = fh.read()

        # Fast path
        try:
            return yaml.safe_load(raw)
        except yaml.YAMLError:
            pass

        # Slow path: convert "...\\..."-style double-quoted strings to single-quoted
        # Only touch double-quoted scalars that contain a backslash.
        def _dq_to_sq(m):
            inner = m.group(1)
            # Already has single-quote inside — can't trivially convert; leave alone
            if "'" in inner:
                return m.group(0)
            # Un-escape common YAML double-quote escapes that are safe to keep literal
            inner_fixed = inner.replace('\\\\', '\\')  # \\\\ → \\
            return f"'{inner_fixed}'"

        fixed = re.sub(r'"((?:[^"\\]|\\.)*)"', _dq_to_sq, raw)
        try:
            result = yaml.safe_load(fixed)
            logger.warning(
                f"[CONFIG] Loaded '{path}' after fixing Windows-style backslash escapes "
                "in double-quoted strings. Consider using forward slashes or single-quoted "
                "strings in your config.yaml to avoid this."
            )
            return result
        except yaml.YAMLError as e:
            logger.error(f"Failed to load general config from '{path}': {e}")
            raise

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
            logger.error(f"Config file not found: '{self._config_path}'. Copy example-config.yaml to config.yaml and edit it.")
            raise

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
            from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
            host = selenium_config.get('host', '127.0.0.1')
            port = selenium_config.get('port', '4444')
            remote_url = f"http://{host}:{port}/wd/hub"
            try:
                driver = webdriver.Remote(
                    command_executor=remote_url,
                    options=chrome_options
                )
                logger.debug(f"Connected to remote Selenium at {remote_url}")
            except Exception as e:
                logger.error(f"Failed to connect to remote Selenium at {remote_url}: {e}")
                return None
        else:
            # local mode
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
                    # Final fallback: let selenium find chromedriver on PATH itself
                    try:
                        driver = webdriver.Chrome(options=chrome_options)
                    except Exception as e:
                        logger.error(f"Failed to initialize Selenium driver: {e}")
                        return None

        if driver:
            try:
                ua = driver.execute_script("return navigator.userAgent;")
                logger.debug(f"Initialized Selenium driver with Chrome version: {driver.capabilities.get('browserVersion', 'unknown')}")
                logger.debug(f"Selenium User-Agent: {ua}")
            except Exception:
                pass
            self._selenium_driver = driver

        return driver
