"""GitHub Trending source - scrape trending repositories."""

import hashlib
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup

from ..models import ContentItem, ContentType, SourceType
from . import BaseSource


class GitHubTrendingSource(BaseSource):
    """Scrape GitHub trending repositories."""
    
    BASE_URL = "https://github.com/trending"
    
    def __init__(self, language: str | None = None, since: str = "daily"):
        """
        Args:
            language: Filter by language (e.g., 'python', 'typescript')
            since: Time range - 'daily', 'weekly', 'monthly'
        """
        super().__init__()
        self.language = language
        self.since = since
    
    @property
    def source_name(self) -> str:
        return "github_trending"
    
    def _build_url(self) -> str:
        """Build trending page URL."""
        url = self.BASE_URL
        if self.language:
            url += f"/{self.language}"
        url += f"?since={self.since}"
        return url
    
    async def fetch(self) -> list[ContentItem]:
        """Fetch trending repositories."""
        url = self._build_url()
        
        try:
            html = await self.fetch_url(url)
            return self._parse_page(html)
        except Exception as e:
            print(f"Error fetching GitHub trending: {e}")
            return []
    
    def _parse_page(self, html: str) -> list[ContentItem]:
        """Parse trending page HTML."""
        soup = BeautifulSoup(html, 'lxml')
        items = []
        
        # Find all repo articles
        for article in soup.select('article.Box-row'):
            try:
                item = self._parse_repo(article)
                if item:
                    items.append(item)
            except Exception:
                continue
        
        return items
    
    def _parse_repo(self, article: BeautifulSoup) -> Optional[ContentItem]:
        """Parse a single repository entry."""
        # Repo name and link
        h2 = article.select_one('h2 a')
        if not h2:
            return None
        
        repo_path = h2.get('href', '').strip('/')
        if not repo_path:
            return None
        
        parts = repo_path.split('/')
        if len(parts) != 2:
            return None
        
        owner, repo = parts
        url = f"https://github.com/{repo_path}"
        
        # Description
        desc_elem = article.select_one('p')
        description = desc_elem.get_text(strip=True) if desc_elem else None
        
        # Language
        lang_elem = article.select_one('[itemprop="programmingLanguage"]')
        language = lang_elem.get_text(strip=True) if lang_elem else None
        
        # Stars
        stars = 0
        stars_elem = article.select_one('a[href$="/stargazers"]')
        if stars_elem:
            try:
                stars_text = stars_elem.get_text(strip=True).replace(',', '')
                stars = int(stars_text)
            except ValueError:
                pass
        
        # Stars today
        stars_today = 0
        today_elem = article.select_one('span.float-sm-right')
        if today_elem:
            try:
                text = today_elem.get_text(strip=True)
                # Format: "123 stars today"
                stars_today = int(text.split()[0].replace(',', ''))
            except (ValueError, IndexError):
                pass
        
        # Tags
        tags = ['github-trending']
        if language:
            tags.append(language.lower())
        
        # Check if AI-related
        ai_keywords = ['ai', 'llm', 'gpt', 'claude', 'agent', 'ml', 'neural', 
                       'transformer', 'model', 'inference', 'embedding']
        text_to_check = f"{repo} {description or ''}".lower()
        for kw in ai_keywords:
            if kw in text_to_check:
                tags.append('ai')
                break
        
        return ContentItem(
            id=f"gh_{owner}_{repo}",
            source_type=SourceType.GITHUB,
            source_name="github_trending",
            content_type=ContentType.REPOSITORY,
            title=f"{owner}/{repo}",
            url=url,
            author=owner,
            summary=description,
            tags=tags,
            engagement={
                "stars": stars,
                "stars_today": stars_today,
            },
        )
