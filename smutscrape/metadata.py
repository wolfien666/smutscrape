#!/usr/bin/env python3
"""
Metadata Module for Smutscrape

This module provides functionality for generating NFO files and managing metadata.
"""

import os
import re
import yaml
from typing import Dict, Any, Optional
from loguru import logger
from smutscrape.utilities import custom_title_case


# ============================================================================
# Metadata Processing Utilities
# ============================================================================

def finalize_metadata(metadata: Dict[str, Any], general_config: Dict[str, Any]) -> Dict[str, Any]:
    """Finalize metadata: deduplicate across fields, apply capitalization rules."""
    case_overrides = general_config.get('case_overrides', [])
    tag_case_overrides = general_config.get('tag_case_overrides', [])
    tag_overrides = case_overrides + tag_case_overrides  # Combine for tags
    
    final_metadata = metadata.copy()
    
    # Normalize fields to lists and strip '#'
    actors = [actor.lstrip('#') for actor in final_metadata.get('actors', []) if actor and actor.strip() != "and"]
    studios = [studio.lstrip('#') for studio in final_metadata.get('studios', []) if studio and studio.strip() != "and"]
    tags = [tag.lstrip('#') for tag in final_metadata.get('tags', []) if tag and tag.strip() != "and"]
    
    # Deduplicate: Actors > Studios > Tags
    actors_lower = set(a.lower() for a in actors)
    studios = [s for s in studios if s.lower() not in actors_lower]
    studios_lower = set(s.lower() for s in studios)
    tags = [t for t in tags if t.lower() not in actors_lower and t.lower() not in studios_lower]
    
    # Apply capitalization
    final_metadata['actors'] = [custom_title_case(a, case_overrides, preserve_mixed_case=True) for a in actors]
    final_metadata['studios'] = [custom_title_case(s, case_overrides, preserve_mixed_case=True) for s in studios]
    final_metadata['tags'] = [custom_title_case(t, tag_overrides) for t in tags]
    if 'title' in final_metadata and final_metadata['title']:
        final_metadata['title'] = custom_title_case(final_metadata['title'].strip(), case_overrides)
    if 'studio' in final_metadata and final_metadata['studio']:
        final_metadata['studio'] = custom_title_case(final_metadata['studio'].lstrip('#'), case_overrides, preserve_mixed_case=True)
    
    # Log the final values for each field in the metadata
    for field in final_metadata:
        logger.debug(f"Final value for '{field}': {final_metadata[field]}")
    
    return final_metadata


def generate_nfo(destination_path: str, metadata: Dict[str, Any], overwrite: bool = False) -> bool:
    """Generate an NFO file alongside the video.

    Args:
        destination_path (str): Path to the video file.
        metadata (dict): Metadata to include in the NFO file.
        overwrite (bool): If True, overwrite existing NFO file. Defaults to False.

    Returns:
        bool: True if NFO generation succeeded, False otherwise.
    """
    # Compute NFO file path
    nfo_path = f"{destination_path.rsplit('.', 1)[0]}.nfo"

    # Check if NFO exists and respect overwrite flag
    if os.path.exists(nfo_path) and not overwrite:
        logger.debug(f"NFO exists at {nfo_path}. Skipping generation.")
        return True

    try:
        # Write the NFO file
        with open(nfo_path, 'w', encoding='utf-8') as f:
            f.write('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n')
            f.write('<movie>\n')
            if 'title' in metadata and metadata['title']:
                f.write(f"  <title>{metadata['title']}</title>\n")
            if 'url' in metadata and metadata['url']:
                f.write(f"  <url>{metadata['url']}</url>\n")
            if 'date' in metadata and metadata['date']:
                f.write(f"  <premiered>{metadata['date']}</premiered>\n")
            if 'Code' in metadata and metadata['Code']:
                f.write(f"  <uniqueid>{metadata['Code']}</uniqueid>\n")
            if 'tags' in metadata and metadata['tags']:
                for tag in metadata['tags']:
                    f.write(f"  <tag>{tag}</tag>\n")
            if 'actors' in metadata and metadata['actors']:
                for i, performer in enumerate(metadata['actors'], 1):
                    f.write(f"  <actor>\n    <name>{performer}</name>\n    <order>{i}</order>\n  </actor>\n")
            if 'Image' in metadata and metadata['Image']:
                f.write(f"  <thumb aspect=\"poster\">{metadata['Image']}</thumb>\n")
            if 'studios' in metadata and metadata['studios']:
                for studio in metadata['studios']:
                    f.write(f"  <studio>{studio}</studio>\n")
            elif 'studio' in metadata and metadata['studio']:
                f.write(f"  <studio>{metadata['studio']}</studio>\n")
            if 'description' in metadata and metadata['description']:
                f.write(f"  <plot>{metadata['description']}</plot>\n")
            f.write('</movie>\n')

        # Log success
        logger.success(f"{'Replaced' if os.path.exists(nfo_path) else 'Generated'} NFO at {nfo_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to generate NFO at {nfo_path}: {e}", exc_info=True)
        return False
