"""RSS source - generic RSS feed fetcher for company blogs, etc."""

import hashlib
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import feedparser
from bs4 import BeautifulSoup

from ..models import ContentItem, ContentType, SourceType
from . import BaseSource


class RSSSource(BaseSource):
    """Fetch content from generic RSS feeds."""
    
    def __init__(self, feeds: list[str], max_items: int = 10):
        """
        Args:
            feeds: List of RSS feed URLs
            max_items: Max items per feed
        """
        super().__init__()
        self.feeds = feeds
        self.max_items = max_items
    
    @property
    def source_name(self) -> str:
        return "rss"
    
    def _get_source_name(self, url: str, feed: dict) -> str:
        """Extract a readable source name."""
        # Try feed title first
        if feed.feed.get('title'):
            return feed.feed['title']
        
        # Fall back to domain
        parsed = urlparse(url)
        return parsed.netloc.replace('www.', '')
    
    def _get_source_type(self, url: str) -> SourceType:
        """Determine source type from URL."""
        domain = urlparse(url).netloc.lower()

        # Company blogs
        if 'anthropic' in domain:
            return SourceType.COMPANY_BLOG
        if 'openai' in domain:
            return SourceType.COMPANY_BLOG
        if 'google' in domain:
            return SourceType.COMPANY_BLOG
        if 'huggingface' in domain:
            return SourceType.HUGGINGFACE
        if 'medium' in domain:
            return SourceType.MEDIUM

        # Mainstream news
        if 'nytimes' in domain:
            return SourceType.NYT
        if 'washingtonpost' in domain:
            return SourceType.WAPO
        if 'theverge' in domain:
            return SourceType.VERGE
        if 'arstechnica' in domain:
            return SourceType.ARS_TECHNICA
        if 'techcrunch' in domain:
            return SourceType.TECHCRUNCH
        if 'wired' in domain:
            return SourceType.WIRED
        if 'technologyreview' in domain:
            return SourceType.MIT_TECH_REVIEW

        return SourceType.RSS
    
    def _parse_date(self, entry: dict) -> Optional[datetime]:
        """Parse date from feed entry."""
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            try:
                return datetime(*entry.published_parsed[:6])
            except (ValueError, TypeError):
                pass
        if hasattr(entry, 'updated_parsed') and entry.updated_parsed:
            try:
                return datetime(*entry.updated_parsed[:6])
            except (ValueError, TypeError):
                pass
        return None
    
    def _extract_summary(self, entry: dict) -> Optional[str]:
        """Extract clean summary from entry."""
        summary = entry.get('summary', '') or entry.get('description', '')
        if summary:
            soup = BeautifulSoup(summary, 'lxml')
            text = soup.get_text(separator=' ', strip=True)
            if len(text) > 500:
                text = text[:500] + "..."
            return text
        return None
    
    def _generate_id(self, url: str, entry: dict) -> str:
        """Generate unique ID for entry."""
        link = entry.get('link', entry.get('id', ''))
        return hashlib.sha256(f"rss:{url}:{link}".encode()).hexdigest()[:16]
    
    async def fetch_feed(self, feed_url: str) -> list[ContentItem]:
        """Fetch items from a single feed."""
        try:
            xml = await self.fetch_url(feed_url)
            feed = feedparser.parse(xml)
            
            source_name = self._get_source_name(feed_url, feed)
            source_type = self._get_source_type(feed_url)
            
            items = []
            for entry in feed.entries[:self.max_items]:
                try:
                    item = ContentItem(
                        id=self._generate_id(feed_url, entry),
                        source_type=source_type,
                        source_name=source_name,
                        content_type=ContentType.ARTICLE,
                        title=entry.get('title', 'Untitled'),
                        url=entry.get('link', feed_url),
                        author=entry.get('author'),
                        published_at=self._parse_date(entry),
                        summary=self._extract_summary(entry),
                        tags=self._extract_tags(entry),
                    )
                    items.append(item)
                except Exception:
                    continue
            
            return items
            
        except Exception as e:
            print(f"Error fetching feed {feed_url}: {e}")
            return []
    
    def _extract_tags(self, entry: dict) -> list[str]:
        """Extract tags from entry."""
        tags = []
        if hasattr(entry, 'tags'):
            for tag in entry.tags:
                if hasattr(tag, 'term'):
                    tags.append(tag.term.lower())
        return tags
    
    async def fetch(self) -> list[ContentItem]:
        """Fetch from all configured feeds."""
        all_items = []
        
        for feed_url in self.feeds:
            items = await self.fetch_feed(feed_url)
            all_items.extend(items)
        
        # Sort by date
        all_items.sort(
            key=lambda x: x.published_at or datetime.min,
            reverse=True
        )
        
        return all_items
