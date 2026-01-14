"""Reddit source - fetch posts from subreddits."""

import hashlib
from datetime import datetime
from typing import Optional

from ..models import ContentItem, ContentType, SourceType
from . import BaseSource


class RedditSource(BaseSource):
    """Fetch posts from Reddit subreddits via JSON API."""
    
    def __init__(self, subreddits: list[str], max_items: int = 25, sort: str = "hot"):
        """
        Args:
            subreddits: List of subreddit names
            max_items: Max posts per subreddit
            sort: 'hot', 'new', 'top'
        """
        super().__init__()
        self.subreddits = subreddits
        self.max_items = max_items
        self.sort = sort
    
    @property
    def source_name(self) -> str:
        return "reddit"
    
    async def get_client(self):
        """Override to add Reddit-specific headers."""
        client = await super().get_client()
        # Reddit requires a proper User-Agent
        client.headers["User-Agent"] = "IntelligenceBrief/1.0 (by /u/IntelBriefBot)"
        return client
    
    async def fetch_subreddit(self, subreddit: str) -> list[ContentItem]:
        """Fetch posts from a single subreddit."""
        url = f"https://www.reddit.com/r/{subreddit}/{self.sort}.json"
        
        try:
            data = await self.fetch_json(url, params={"limit": self.max_items})
            return self._parse_listing(data, subreddit)
        except Exception as e:
            print(f"Error fetching r/{subreddit}: {e}")
            return []
    
    def _parse_listing(self, data: dict, subreddit: str) -> list[ContentItem]:
        """Parse Reddit JSON listing."""
        items = []
        
        posts = data.get('data', {}).get('children', [])
        for post_data in posts:
            try:
                post = post_data.get('data', {})
                item = self._parse_post(post, subreddit)
                if item:
                    items.append(item)
            except Exception:
                continue
        
        return items
    
    def _parse_post(self, post: dict, subreddit: str) -> Optional[ContentItem]:
        """Parse a single post."""
        post_id = post.get('id')
        if not post_id:
            return None
        
        title = post.get('title', 'Untitled')
        
        # URL - could be external link or reddit self-post
        url = post.get('url', '')
        permalink = f"https://reddit.com{post.get('permalink', '')}"
        is_self = post.get('is_self', False)
        
        if is_self or not url:
            url = permalink
        
        # Published date
        created_utc = post.get('created_utc', 0)
        published_at = datetime.utcfromtimestamp(created_utc) if created_utc else None
        
        # Summary - self text or empty
        selftext = post.get('selftext', '')
        summary = selftext[:500] + "..." if len(selftext) > 500 else selftext if selftext else None
        
        # Tags
        tags = [f"r/{subreddit}"]
        flair = post.get('link_flair_text')
        if flair:
            tags.append(flair.lower())
        
        return ContentItem(
            id=f"reddit_{post_id}",
            source_type=SourceType.REDDIT,
            source_name=f"r/{subreddit}",
            content_type=ContentType.DISCUSSION,
            title=title,
            url=url,
            author=post.get('author'),
            published_at=published_at,
            summary=summary,
            tags=tags,
            engagement={
                "score": post.get('score', 0),
                "upvote_ratio": post.get('upvote_ratio', 0),
                "comments": post.get('num_comments', 0),
            },
        )
    
    async def fetch(self) -> list[ContentItem]:
        """Fetch posts from all configured subreddits."""
        all_items = []
        
        for subreddit in self.subreddits:
            items = await self.fetch_subreddit(subreddit)
            all_items.extend(items)
        
        # Sort by score
        all_items.sort(
            key=lambda x: x.engagement.get('score', 0) if x.engagement else 0,
            reverse=True
        )
        
        return all_items
