# models.py
"""
Domain models for the smutscrape application.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime


@dataclass
class VideoMetadata:
    """Represents metadata for a video"""
    title: str
    url: str
    download_url: Optional[str] = None
    date: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None
    actors: List[str] = field(default_factory=list)
    studios: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    duration: Optional[str] = None
    resolution: Optional[str] = None
    bitrate: Optional[str] = None
    size: Optional[int] = None
    size_str: Optional[str] = None
    
    def to_nfo_dict(self) -> Dict[str, Any]:
        """Convert to dictionary suitable for NFO generation"""
        return {
            'title': self.title,
            'url': self.url,
            'date': self.date,
            'Code': self.code,
            'description': self.description,
            'Image': self.image,
            'actors': self.actors,
            'studios': self.studios,
            'tags': self.tags,
            'studio': self.studios[0] if self.studios else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoMetadata':
        """Create VideoMetadata from a dictionary"""
        return cls(
            title=data.get('title', ''),
            url=data.get('url', ''),
            download_url=data.get('download_url'),
            date=data.get('date'),
            code=data.get('code') or data.get('Code'),
            description=data.get('description'),
            image=data.get('image') or data.get('Image'),
            actors=data.get('actors', []),
            studios=data.get('studios', []),
            tags=data.get('tags', []),
            duration=data.get('duration'),
            resolution=data.get('resolution'),
            bitrate=data.get('bitrate'),
            size=data.get('size'),
            size_str=data.get('size_str')
        )


@dataclass
class DownloadJob:
    """Represents a single download job"""
    url: str
    destination_path: str
    site_config: Any  # Avoid circular import by using Any
    metadata: Optional[VideoMetadata] = None
    overwrite: bool = False
    headers: Dict[str, str] = field(default_factory=dict)
    method: Optional[str] = None
    
    def __post_init__(self):
        """Set download method from site config if not explicitly provided"""
        if self.method is None and self.site_config:
            self.method = self.site_config.download.method


@dataclass 
class ProcessingState:
    """Tracks the state of processing"""
    processed_urls: set = field(default_factory=set)
    current_page: int = 1
    video_offset: int = 0
    
    def mark_processed(self, url: str):
        """Mark a URL as processed"""
        self.processed_urls.add(url)
    
    def is_processed(self, url: str) -> bool:
        """Check if a URL has been processed"""
        return url in self.processed_urls
    
    def update_position(self, page: int, offset: int = 0):
        """Update current page and video offset"""
        self.current_page = page
        self.video_offset = offset
    
    @classmethod
    def from_file(cls, file_path: str) -> 'ProcessingState':
        """Load processing state from a file"""
        state = cls()
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    url = line.strip()
                    if url:
                        state.processed_urls.add(url)
        except FileNotFoundError:
            pass
        return state
    
    def save_to_file(self, file_path: str):
        """Save processing state to a file"""
        with open(file_path, 'w', encoding='utf-8') as f:
            for url in sorted(self.processed_urls):
                f.write(f"{url}\n")


@dataclass
class ScrapedVideo:
    """Represents a video scraped from a list page"""
    title: str
    url: str
    thumbnail: Optional[str] = None
    duration: Optional[str] = None
    video_key: Optional[str] = None
    additional_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        result = {
            'title': self.title,
            'url': self.url
        }
        if self.thumbnail:
            result['thumbnail'] = self.thumbnail
        if self.duration:
            result['duration'] = self.duration
        if self.video_key:
            result['video_key'] = self.video_key
        result.update(self.additional_data)
        return result


@dataclass
class PageResult:
    """Results from processing a single page"""
    videos: List[ScrapedVideo] = field(default_factory=list)
    next_page_url: Optional[str] = None
    next_page_number: Optional[int] = None
    success: bool = True
    error_message: Optional[str] = None
    
    def add_video(self, video: ScrapedVideo):
        """Add a video to the results"""
        self.videos.append(video)
    
    @property
    def video_count(self) -> int:
        """Get the number of videos found"""
        return len(self.videos) 