"""Content aggregator - orchestrates fetching from all sources."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from .models import ContentItem, DailyBrief, StoryItem, SourceType
from .config import get_settings
from .sources.substack import SubstackSource
from .sources.hackernews import HackerNewsSource
from .sources.arxiv import ArxivSource
from .sources.github import GitHubTrendingSource
from .sources.reddit import RedditSource
from .sources.rss import RSSSource
from .sources.podcast import PodcastSource
from .analysis import ContentAnalyzer


class Aggregator:
    """Orchestrates content aggregation from all sources."""
    
    def __init__(self):
        self.settings = get_settings()
        self.analyzer = ContentAnalyzer()
        self._init_sources()
    
    def _init_sources(self):
        """Initialize all content sources."""
        self.sources = []
        
        # Substack
        if self.settings.substack_list:
            self.sources.append(
                SubstackSource(
                    handles=self.settings.substack_list,
                    max_items=self.settings.max_items_per_source
                )
            )
        
        # Hacker News
        self.sources.append(
            HackerNewsSource(
                max_items=self.settings.max_items_per_source,
                story_type="top"
            )
        )
        
        # arXiv
        self.sources.append(
            ArxivSource(max_items=self.settings.max_items_per_source)
        )
        
        # GitHub Trending
        self.sources.append(GitHubTrendingSource(since="daily"))
        
        # Reddit
        if self.settings.reddit_list:
            self.sources.append(
                RedditSource(
                    subreddits=self.settings.reddit_list,
                    max_items=15
                )
            )
        
        # Company blogs (RSS)
        if self.settings.company_blog_list:
            self.sources.append(
                RSSSource(
                    feeds=self.settings.company_blog_list,
                    max_items=10
                )
            )

        # Podcasts (transcribed via Groq)
        if self.settings.podcast_feed_list and self.settings.groq_api_key:
            self.sources.append(
                PodcastSource(
                    feeds=self.settings.podcast_feed_list,
                    groq_api_key=self.settings.groq_api_key,
                    max_items=5,
                    lookback_hours=self.settings.lookback_hours
                )
            )
    
    async def fetch_all(self) -> list[ContentItem]:
        """Fetch content from all sources concurrently."""
        tasks = [source.fetch() for source in self.sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_items = []
        sources_checked = []
        
        for source, result in zip(self.sources, results):
            sources_checked.append(source.source_name)
            
            if isinstance(result, Exception):
                print(f"Error from {source.source_name}: {result}")
                continue
            
            all_items.extend(result)
        
        print(f"Fetched {len(all_items)} items from {len(sources_checked)} sources")
        return all_items
    
    def _filter_by_time(
        self,
        items: list[ContentItem],
        hours: Optional[int] = None
    ) -> list[ContentItem]:
        """Filter items by publication time."""
        if hours is None:
            hours = self.settings.lookback_hours

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        filtered = []
        for item in items:
            if item.published_at is None:
                filtered.append(item)
                continue

            pub_at = item.published_at
            if pub_at.tzinfo is None:
                pub_at = pub_at.replace(tzinfo=timezone.utc)

            if pub_at > cutoff:
                filtered.append(item)

        return filtered
    
    def _deduplicate(self, items: list[ContentItem]) -> list[ContentItem]:
        """Remove duplicate items based on URL."""
        seen_urls = set()
        unique = []
        
        for item in items:
            url_str = str(item.url)
            if url_str not in seen_urls:
                seen_urls.add(url_str)
                unique.append(item)
        
        return unique
    
    async def aggregate_and_analyze(self) -> tuple[list[ContentItem], list[str]]:
        """Fetch, filter, and analyze all content."""
        all_items = await self.fetch_all()
        sources_checked = [s.source_name for s in self.sources]
        
        recent_items = self._filter_by_time(all_items)
        print(f"Filtered to {len(recent_items)} recent items")
        
        unique_items = self._deduplicate(recent_items)
        print(f"Deduplicated to {len(unique_items)} items")
        
        analyzed_items = await self.analyzer.batch_analyze(unique_items)
        print(f"Analyzed {len(analyzed_items)} items")
        
        return analyzed_items, sources_checked
    
    async def close(self):
        """Close all source connections."""
        for source in self.sources:
            await source.close()


class BriefGenerator:
    """Generates the daily intelligence brief - newsletter style."""
    
    def __init__(self):
        self.settings = get_settings()
        self.analyzer = ContentAnalyzer()
    
    async def generate_brief(
        self, 
        items: list[ContentItem],
        sources_checked: list[str]
    ) -> DailyBrief:
        """Generate the daily brief from analyzed items."""
        
        # Sort by relevance
        sorted_items = sorted(
            items, 
            key=lambda x: x.relevance_score or 0, 
            reverse=True
        )
        
        # Filter to relevant items only
        relevant_items = [i for i in sorted_items if (i.relevance_score or 0) >= 0.5]
        
        # Generate quick catchup
        print("Generating quick catchup...")
        quick_catchup = await self.analyzer.generate_quick_catchup(relevant_items)
        
        # Build "What's Moving" stories (top 5-7 items with rich context)
        print("Generating story contexts...")
        whats_moving = []
        for item in relevant_items[:7]:
            context = await self.analyzer.generate_story_context(item)
            story = StoryItem(
                headline=item.title,
                context=context,
                source_url=item.url,
                source_name=item.source_name,
                source_item=item
            )
            whats_moving.append(story)
            await asyncio.sleep(0.3)  # Rate limit
        
        # "Worth a Click" - next tier of items
        worth_a_click = relevant_items[7:15]
        
        # Generate Claude's take
        print("Generating Claude's take...")
        claudes_take = await self.analyzer.generate_synthesis(relevant_items)
        
        # Build legacy categories for backwards compat
        categories = self._categorize_items(items)
        
        brief = DailyBrief(
            date=datetime.utcnow().strftime("%Y-%m-%d"),
            quick_catchup=quick_catchup,
            whats_moving=whats_moving,
            worth_a_click=worth_a_click,
            claudes_take=claudes_take,
            # Legacy fields
            top_signal=categories["top_signal"],
            builder_corner=categories["builder_corner"],
            paper_of_the_day=categories["paper_of_day"][0] if categories["paper_of_day"] else None,
            homelab_corner=categories["homelab"],
            honorable_mentions=categories["honorable_mentions"],
            synthesis=claudes_take,
            total_items_scanned=len(items),
            sources_checked=sources_checked,
        )
        
        return brief
    
    def _categorize_items(self, items: list[ContentItem]) -> dict[str, list[ContentItem]]:
        """Categorize items into brief sections (legacy)."""
        categories = {
            "top_signal": [],
            "builder_corner": [],
            "paper_of_day": [],
            "homelab": [],
            "honorable_mentions": [],
        }
        
        sorted_items = sorted(
            items, 
            key=lambda x: x.relevance_score or 0, 
            reverse=True
        )
        
        for item in sorted_items:
            relevance = item.relevance_score or 0
            if relevance < 0.3:
                continue
            
            if item.source_type == SourceType.ARXIV and relevance >= 0.7:
                if not categories["paper_of_day"]:
                    categories["paper_of_day"].append(item)
                    continue
            
            if item.source_type == SourceType.GITHUB:
                if len(categories["builder_corner"]) < 5:
                    categories["builder_corner"].append(item)
                    continue
            
            homelab_tags = ['homelab', 'home-assistant', 'selfhosted', 'raspberry-pi', 'r/homelab', 'r/selfhosted']
            if any(tag in (item.tags or []) for tag in homelab_tags):
                if len(categories["homelab"]) < 3:
                    categories["homelab"].append(item)
                    continue
            
            if relevance >= 0.7 and item.actionable_ideas:
                if len(categories["top_signal"]) < 5:
                    categories["top_signal"].append(item)
                    continue
            
            if len(categories["honorable_mentions"]) < 10:
                categories["honorable_mentions"].append(item)
        
        return categories
    
    def format_brief_text(self, brief: DailyBrief) -> str:
        """Format brief as readable text."""
        lines = []
        
        lines.append(f"🧠 Intelligence Brief - {brief.date}")
        lines.append("=" * 50)
        lines.append("")
        
        # Quick Catchup
        lines.append("THE QUICK CATCH-UP")
        lines.append("-" * 30)
        lines.append(brief.quick_catchup)
        lines.append("")
        
        # What's Moving
        if brief.whats_moving:
            lines.append("WHAT'S MOVING")
            lines.append("-" * 30)
            for story in brief.whats_moving:
                lines.append(f"▸ {story.headline}")
                lines.append(f"  {story.context}")
                lines.append(f"  → {story.source_url}")
                lines.append("")
        
        # Worth a Click
        if brief.worth_a_click:
            lines.append("WORTH A CLICK")
            lines.append("-" * 30)
            for item in brief.worth_a_click:
                lines.append(f"• {item.title} ({item.source_name})")
                lines.append(f"  {item.url}")
            lines.append("")
        
        # Claude's Take
        if brief.claudes_take:
            lines.append("CLAUDE'S TAKE")
            lines.append("-" * 30)
            lines.append(brief.claudes_take)
            lines.append("")
        
        lines.append("-" * 50)
        lines.append(f"Scanned {brief.total_items_scanned} items from {len(brief.sources_checked)} sources")
        
        return "\n".join(lines)
