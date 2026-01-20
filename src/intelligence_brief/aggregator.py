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
        
        # Reddit (configured + discovered)
        from .source_discovery import get_discovered_reddit_subs

        reddit_subs = list(self.settings.reddit_list) if self.settings.reddit_list else []

        # Add discovered subreddits
        discovered_subs = get_discovered_reddit_subs()
        for sub in discovered_subs:
            if sub not in reddit_subs:
                reddit_subs.append(sub)

        if reddit_subs:
            self.sources.append(
                RedditSource(
                    subreddits=reddit_subs,
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

        # Mainstream news sources (RSS)
        if self.settings.news_source_list:
            self.sources.append(
                RSSSource(
                    feeds=self.settings.news_source_list,
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
    """Generates the daily intelligence brief - narrative + sections style."""

    def __init__(self):
        self.settings = get_settings()
        self.analyzer = ContentAnalyzer()

    async def generate_brief(
        self,
        items: list[ContentItem],
        sources_checked: list[str]
    ) -> DailyBrief:
        """Generate the daily brief from analyzed items."""

        # Sort by relevance (newsworthiness)
        sorted_items = sorted(
            items,
            key=lambda x: x.relevance_score or 0,
            reverse=True
        )

        # Lower threshold - we want more content now (0.35 instead of 0.5)
        relevant_items = [i for i in sorted_items if (i.relevance_score or 0) >= 0.35]

        # Generate THE BRIEF - Doris's narrative with inline links
        print("Generating Doris's narrative brief...")
        narrative_brief = await self.analyzer.generate_narrative_brief(relevant_items)

        # Generate quick catchup (short teaser for email preview)
        print("Generating quick catchup...")
        quick_catchup = await self.analyzer.generate_quick_catchup(relevant_items[:8])

        # Categorize items for DEEPER DIVES sections
        sections = self._categorize_for_sections(relevant_items)

        # Build "What's Moving" from top items for backwards compat
        whats_moving_items = self._select_diverse_items(relevant_items, target_count=7)
        whats_moving = []
        for item in whats_moving_items:
            story = StoryItem(
                headline=item.title,
                context=item.insight_summary or item.summary or "",
                source_url=item.url,
                source_name=item.source_name,
                source_item=item
            )
            whats_moving.append(story)

        # "Worth a Click" - everything not in the main narrative
        used_ids = {item.id for item in whats_moving_items}
        remaining = [i for i in relevant_items if i.id not in used_ids]
        worth_a_click = remaining[:15]  # More items now

        brief = DailyBrief(
            date=datetime.utcnow().strftime("%Y-%m-%d"),
            quick_catchup=quick_catchup,
            whats_moving=whats_moving,
            worth_a_click=worth_a_click,
            claudes_take=narrative_brief,  # This is now the main narrative
            # Sections for deeper dives
            top_signal=sections["industry_news"],
            builder_corner=sections["tools"],
            paper_of_the_day=sections["research"][0] if sections["research"] else None,
            homelab_corner=sections["research"][1:4] if len(sections["research"]) > 1 else [],
            honorable_mentions=sections["other"],
            synthesis=narrative_brief,
            total_items_scanned=len(items),
            sources_checked=sources_checked,
        )

        return brief

    def _categorize_for_sections(self, items: list[ContentItem]) -> dict[str, list[ContentItem]]:
        """Categorize items into DEEPER DIVES sections based on source and category."""
        sections = {
            "industry_news": [],  # Mainstream news, company blogs
            "research": [],       # arXiv papers
            "tools": [],          # GitHub, dev tools
            "other": [],          # Everything else
        }

        # Source types that map to sections
        industry_sources = {'nyt', 'wapo', 'verge', 'ars_technica', 'techcrunch', 'wired', 'mit_tech_review', 'company_blog'}
        research_sources = {'arxiv'}
        tool_sources = {'github'}

        for item in items:
            source = item.source_type.value

            # Check category tag from analysis
            category = None
            for idea in (item.actionable_ideas or []):
                if idea.startswith('category:'):
                    category = idea.replace('category:', '')
                    break

            if source in research_sources or category == 'research':
                if len(sections["research"]) < 5:
                    sections["research"].append(item)
            elif source in tool_sources or category == 'tools':
                if len(sections["tools"]) < 6:
                    sections["tools"].append(item)
            elif source in industry_sources or category == 'industry_news':
                if len(sections["industry_news"]) < 6:
                    sections["industry_news"].append(item)
            else:
                if len(sections["other"]) < 8:
                    sections["other"].append(item)

        return sections

    def _select_diverse_items(self, items: list[ContentItem], target_count: int) -> list[ContentItem]:
        """
        Select items ensuring source type diversity.
        Takes the best item from each source type first, then fills with top remaining.
        """
        if not items:
            return []

        # Group by source type
        by_source: dict[str, list[ContentItem]] = {}
        for item in items:
            source_key = item.source_type.value
            if source_key not in by_source:
                by_source[source_key] = []
            by_source[source_key].append(item)

        selected = []
        used_ids = set()

        # First pass: take best item from each source type
        for source_key in by_source:
            if by_source[source_key] and len(selected) < target_count:
                best = by_source[source_key][0]  # Already sorted by relevance
                selected.append(best)
                used_ids.add(best.id)

        # Second pass: fill remaining slots with highest relevance items
        for item in items:
            if len(selected) >= target_count:
                break
            if item.id not in used_ids:
                selected.append(item)
                used_ids.add(item.id)

        return selected

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

        # THE BRIEF - Doris's narrative (main content)
        lines.append("THE BRIEF")
        lines.append("-" * 30)
        lines.append(brief.claudes_take or brief.quick_catchup)
        lines.append("")

        # DEEPER DIVES
        lines.append("DEEPER DIVES")
        lines.append("=" * 50)
        lines.append("")

        # Research Radar (papers)
        if brief.paper_of_the_day or brief.homelab_corner:
            lines.append("📚 RESEARCH RADAR")
            lines.append("-" * 30)
            if brief.paper_of_the_day:
                lines.append(f"▸ {brief.paper_of_the_day.title}")
                lines.append(f"  {brief.paper_of_the_day.insight_summary or ''}")
                lines.append(f"  → {brief.paper_of_the_day.url}")
                lines.append("")
            for item in (brief.homelab_corner or []):
                lines.append(f"• {item.title}")
                lines.append(f"  → {item.url}")
            lines.append("")

        # Builder's Bench (tools/repos)
        if brief.builder_corner:
            lines.append("🛠️ BUILDER'S BENCH")
            lines.append("-" * 30)
            for item in brief.builder_corner:
                lines.append(f"▸ {item.title} ({item.source_name})")
                if item.insight_summary:
                    lines.append(f"  {item.insight_summary}")
                lines.append(f"  → {item.url}")
                lines.append("")

        # Industry Watch (news)
        if brief.top_signal:
            lines.append("📰 INDUSTRY WATCH")
            lines.append("-" * 30)
            for item in brief.top_signal:
                lines.append(f"▸ {item.title} ({item.source_name})")
                if item.insight_summary:
                    lines.append(f"  {item.insight_summary}")
                lines.append(f"  → {item.url}")
                lines.append("")

        # Quick Links (everything else)
        if brief.worth_a_click:
            lines.append("🔗 QUICK LINKS")
            lines.append("-" * 30)
            for item in brief.worth_a_click[:10]:
                lines.append(f"• {item.title} ({item.source_name})")
                lines.append(f"  {item.url}")
            lines.append("")

        lines.append("-" * 50)
        lines.append(f"Scanned {brief.total_items_scanned} items from {len(brief.sources_checked)} sources")

        return "\n".join(lines)
