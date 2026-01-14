"""Substack source - fetch posts via RSS feeds."""

import hashlib
from datetime import datetime
from typing import Optional

import feedparser
from bs4 import BeautifulSoup

from ..models import ContentItem, ContentType, SourceType
from . import BaseSource


class SubstackSource(BaseSource):
    """Fetch content from Substack publications via RSS."""
    
    def __init__(self, handles: list[str], max_items: int = 10):
        super().__init__()
        self.handles = handles
        self.max_items = max_items
    
    @property
    def source_name(self) -> str:
        return "substack"
    
    def _get_feed_url(self, handle: str) -> str:
        """Get RSS feed URL for a Substack handle."""
        # Handle both formats: 'publication' and 'publication.substack.com'
        if ".substack.com" in handle:
            return f"https://{handle}/feed"
        return f"https://{handle}.substack.com/feed"
    
    def _parse_date(self, entry: dict) -> Optional[datetime]:
        """Parse date from feed entry."""
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            try:
                return datetime(*entry.published_parsed[:6])
            except (ValueError, TypeError):
                pass
        return None
    
    def _extract_summary(self, entry: dict) -> Optional[str]:
        """Extract clean summary from entry."""
        summary = entry.get('summary', '') or entry.get('description', '')
        if summary:
            # Strip HTML tags
            soup = BeautifulSoup(summary, 'lxml')
            text = soup.get_text(separator=' ', strip=True)
            # Truncate if too long
            if len(text) > 500:
                text = text[:500] + "..."
            return text
        return None
    
    def _generate_id(self, handle: str, entry: dict) -> str:
        """Generate unique ID for entry."""
        url = entry.get('link', '')
        return hashlib.sha256(f"substack:{handle}:{url}".encode()).hexdigest()[:16]
    
    async def fetch_publication(self, handle: str) -> list[ContentItem]:
        """Fetch posts from a single publication."""
        feed_url = self._get_feed_url(handle)
        
        try:
            xml = await self.fetch_url(feed_url)
            feed = feedparser.parse(xml)
            
            items = []
            for entry in feed.entries[:self.max_items]:
                try:
                    item = ContentItem(
                        id=self._generate_id(handle, entry),
                        source_type=SourceType.SUBSTACK,
                        source_name=handle,
                        content_type=ContentType.ARTICLE,
                        title=entry.get('title', 'Untitled'),
                        url=entry.get('link', f"https://{handle}.substack.com"),
                        author=entry.get('author', handle),
                        published_at=self._parse_date(entry),
                        summary=self._extract_summary(entry),
                        tags=self._extract_tags(entry),
                    )
                    items.append(item)
                except Exception as e:
                    # Skip malformed entries
                    continue
            
            return items
            
        except Exception as e:
            # Log error but don't fail entire aggregation
            print(f"Error fetching {handle}: {e}")
            return []
    
    def _extract_tags(self, entry: dict) -> list[str]:
        """Extract tags/categories from entry."""
        tags = []
        if hasattr(entry, 'tags'):
            for tag in entry.tags:
                if hasattr(tag, 'term'):
                    tags.append(tag.term.lower())
        return tags
    
    async def fetch(self) -> list[ContentItem]:
        """Fetch posts from all configured publications."""
        all_items = []
        
        for handle in self.handles:
            items = await self.fetch_publication(handle)
            all_items.extend(items)
        
        # Sort by published date, most recent first
        all_items.sort(
            key=lambda x: x.published_at or datetime.min,
            reverse=True
        )
        
        return all_items
