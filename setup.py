#!/usr/bin/env python3
"""
Setup script for Smutscrape package
"""

from setuptools import setup, find_packages
import os

# Read the README file for long description
def read_readme():
    with open("README.md", "r", encoding="utf-8") as fh:
        return fh.read()

# Read requirements from requirements.txt
def read_requirements():
    with open("requirements.txt", "r", encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="smutscrape",
    version="1.0.0",
    author="Smutscrape Contributors",
    author_email="",
    description="Adult content scraper with metadata support",
    long_description=read_readme(),
    long_description_content_type="text/markdown",
    url="",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
    install_requires=read_requirements(),
    extras_require={
        "selenium": ["selenium", "webdriver-manager"],
        "api": ["fastapi", "uvicorn"],
        "dev": ["pytest", "black", "flake8", "mypy"],
    },
    entry_points={
        "console_scripts": [
            "smutscrape=smutscrape.cli:main",
        ],
    },
    include_package_data=True,
    package_data={
        "smutscrape": ["*.py"],
        "": ["sites/*.yaml", "config/*.yaml", "*.md", "*.txt"],
    },
    zip_safe=False,
) 