"""Hacker News source - fetch top/new stories via API."""

from datetime import datetime
from typing import Optional

from ..models import ContentItem, ContentType, SourceType
from . import BaseSource


class HackerNewsSource(BaseSource):
    """Fetch top stories from Hacker News API."""
    
    BASE_URL = "https://hacker-news.firebaseio.com/v0"
    
    def __init__(self, max_items: int = 30, story_type: str = "top"):
        """
        Args:
            max_items: Maximum stories to fetch
            story_type: One of 'top', 'new', 'best'
        """
        super().__init__()
        self.max_items = max_items
        self.story_type = story_type
    
    @property
    def source_name(self) -> str:
        return "hacker_news"
    
    async def _get_story_ids(self) -> list[int]:
        """Get list of story IDs."""
        url = f"{self.BASE_URL}/{self.story_type}stories.json"
        data = await self.fetch_json(url)
        return data[:self.max_items] if data else []
    
    async def _get_story(self, story_id: int) -> Optional[dict]:
        """Fetch a single story by ID."""
        try:
            url = f"{self.BASE_URL}/item/{story_id}.json"
            return await self.fetch_json(url)
        except Exception:
            return None
    
    def _parse_timestamp(self, ts: int) -> datetime:
        """Convert Unix timestamp to datetime."""
        return datetime.utcfromtimestamp(ts)
    
    async def fetch(self) -> list[ContentItem]:
        """Fetch top stories from Hacker News."""
        story_ids = await self._get_story_ids()
        
        items = []
        for story_id in story_ids:
            story = await self._get_story(story_id)
            if not story or story.get('type') != 'story':
                continue
            
            # Skip if no URL (Ask HN, etc.) - we can include these later if wanted
            url = story.get('url')
            if not url:
                url = f"https://news.ycombinator.com/item?id={story_id}"
            
            try:
                item = ContentItem(
                    id=f"hn_{story_id}",
                    source_type=SourceType.HACKER_NEWS,
                    source_name="hacker_news",
                    content_type=ContentType.DISCUSSION,
                    title=story.get('title', 'Untitled'),
                    url=url,
                    author=story.get('by'),
                    published_at=self._parse_timestamp(story.get('time', 0)),
                    engagement={
                        "score": story.get('score', 0),
                        "comments": story.get('descendants', 0),
                    },
                    tags=self._infer_tags(story.get('title', '')),
                )
                items.append(item)
            except Exception as e:
                # Skip malformed entries
                continue
        
        return items
    
    def _infer_tags(self, title: str) -> list[str]:
        """Infer tags from title keywords."""
        title_lower = title.lower()
        tags = []
        
        # AI/ML related
        ai_keywords = ['ai', 'gpt', 'llm', 'claude', 'anthropic', 'openai', 'machine learning', 
                       'neural', 'transformer', 'model', 'agent']
        for kw in ai_keywords:
            if kw in title_lower:
                tags.append('ai')
                break
        
        # Show HN
        if title_lower.startswith('show hn'):
            tags.append('show-hn')
        
        # Ask HN
        if title_lower.startswith('ask hn'):
            tags.append('ask-hn')
        
        return tags
