"""Analysis layer - uses Claude to evaluate and synthesize content."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from anthropic import AsyncAnthropic

from .models import ContentItem, DailyBrief, DiscoveredSource, TopicConfig
from .config import get_settings

logger = logging.getLogger(__name__)


# System prompt for content analysis
ANALYSIS_SYSTEM_PROMPT = """You are Doris, an AI assistant curating an intelligence brief about AI, technology, and the tech industry.

Your job is to evaluate content for NEWSWORTHINESS - is this something an informed person in the AI/tech space should know about?

Newsworthy content includes:
- Major announcements from AI labs (Anthropic, OpenAI, Google, Meta, etc.)
- Significant funding rounds, acquisitions, or business moves
- Breakthrough research or notable papers
- New tools, frameworks, or products that matter
- Industry trends, policy changes, or regulatory news
- Thoughtful analysis or commentary from credible sources

Be skeptical of:
- Hype without substance
- Rehashed news or derivative commentary
- Minor updates dressed up as major announcements
- Clickbait or engagement farming

Adam (the reader) has specific projects: Doris (voice AI assistant), TerryAnn (Medicare platform), and home automation. Flag content that's specifically relevant to these, but don't let project relevance override general newsworthiness.

When analyzing:
1. Score newsworthiness 0-1 (would an informed AI/tech person want to know this?)
2. Pull out the actual insight (skip the fluff)
3. Categorize: industry_news, research, tools, analysis, project_relevant
4. Note if it's specifically relevant to Adam's projects"""


class ContentAnalyzer:
    """Analyzes content using Claude."""
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        settings = get_settings()
        self.client = AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)
        self.model = model or settings.anthropic_model
    
    async def analyze_item(self, item: ContentItem) -> ContentItem:
        """Analyze a single content item and fill in analysis fields."""
        
        # Build content for analysis
        content_text = f"""
Title: {item.title}
Source: {item.source_name} ({item.source_type})
Author: {item.author or 'Unknown'}
URL: {item.url}

Summary/Content:
{item.summary or item.full_text or 'No content available'}

Tags: {', '.join(item.tags) if item.tags else 'None'}
Engagement: {json.dumps(item.engagement) if item.engagement else 'None'}
"""
        
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=500,
                system=ANALYSIS_SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"""Analyze this content item and respond with ONLY a raw JSON object.

{content_text}

CRITICAL: Respond with ONLY the raw JSON object below. Do NOT wrap it in markdown code blocks (no ```json), do NOT add any explanatory text before or after. Just the pure JSON object starting with {{ and ending with }}.

{{
    "newsworthiness_score": 0.0-1.0,
    "category": "industry_news|research|tools|analysis|other",
    "insight_summary": "One sentence capturing the actual insight",
    "project_relevant": true/false,
    "project_note": "only if project_relevant is true - how it relates to Doris/TerryAnn/homelab",
    "skip_reason": "only if newsworthiness < 0.3, explain why"
}}"""
                }]
            )

            # Get raw response text
            raw_response = response.content[0].text.strip()

            # Try to parse JSON
            try:
                result = json.loads(raw_response)
            except json.JSONDecodeError as json_err:
                # Log the problematic response for debugging
                logger.error(f"JSON parse error for item '{item.title[:50]}...'")
                logger.error(f"Raw response: {raw_response[:500]}")
                logger.error(f"Parse error: {json_err}")

                # Return default failed analysis
                item.relevance_score = 0.3
                item.insight_summary = "Analysis failed - invalid JSON response"
                item.actionable_ideas = []
                return item

            # Successfully parsed - populate item
            item.relevance_score = result.get('newsworthiness_score', 0.5)
            item.insight_summary = result.get('insight_summary')
            # Store category and project relevance in actionable_ideas for now
            # TODO: Add proper fields to ContentItem model
            category = result.get('category', 'other')
            project_relevant = result.get('project_relevant', False)
            project_note = result.get('project_note', '')
            item.actionable_ideas = [f"category:{category}"]
            if project_relevant and project_note:
                item.actionable_ideas.append(f"project:{project_note}")

            return item

        except Exception as e:
            # If API call fails entirely, give it a neutral score
            logger.error(f"API call failed for '{item.title[:50]}...': {e}")
            item.relevance_score = 0.3
            item.insight_summary = "Analysis failed - API error"
            item.actionable_ideas = []
            return item
    
    async def batch_analyze(self, items: list[ContentItem], max_items: int = 50) -> list[ContentItem]:
        """Analyze multiple items, ensuring source diversity then prioritizing by newsworthiness signals."""

        # Broad AI/tech keywords for pre-filtering (not project-specific)
        ai_keywords = {
            # Core AI terms
            'ai', 'artificial intelligence', 'machine learning', 'ml', 'deep learning',
            'neural network', 'llm', 'large language model', 'gpt', 'transformer',
            # Major players
            'anthropic', 'claude', 'openai', 'chatgpt', 'google', 'gemini', 'meta', 'llama',
            'microsoft', 'copilot', 'amazon', 'bedrock', 'mistral', 'cohere',
            # AI topics
            'agent', 'agents', 'rag', 'retrieval', 'fine-tuning', 'prompt', 'embedding',
            'multimodal', 'vision', 'speech', 'voice', 'reasoning', 'benchmark',
            # Industry/business
            'funding', 'acquisition', 'valuation', 'startup', 'series a', 'series b',
            'ipo', 'regulation', 'policy', 'safety', 'alignment', 'ethics',
            # Technical
            'api', 'sdk', 'framework', 'model', 'inference', 'training', 'compute', 'gpu',
            'open source', 'open-source', 'release', 'launch', 'announce'
        }

        def item_score(item: ContentItem) -> float:
            """
            Score items for general AI newsworthiness (roughly 0-200 scale):
            1. AI/tech keyword relevance (0-60): Does it mention AI topics?
            2. Source authority (0-50): Mainstream news, company blogs, research
            3. Recency (0-50): How fresh is this content?
            4. Engagement (0-40): Community validation
            """
            score = 0.0
            title_lower = item.title.lower()
            summary_lower = (item.summary or '').lower()
            text = title_lower + ' ' + summary_lower

            # 1. AI/TECH KEYWORD RELEVANCE (0-60 points)
            keyword_matches = sum(1 for kw in ai_keywords if kw in text)
            score += min(keyword_matches * 10, 60)

            # 2. SOURCE AUTHORITY (0-55 points)
            # Mainstream news gets highest priority (we want NYT/etc to appear)
            mainstream_news = ['nyt', 'wapo', 'verge', 'ars_technica', 'techcrunch', 'wired', 'mit_tech_review']
            if item.source_type.value in mainstream_news:
                score += 55
            # Company blogs (official announcements)
            elif item.source_type.value == 'company_blog':
                score += 45
            # Research
            elif item.source_type.value == 'arxiv':
                score += 35
            # Substacks (analysis/commentary)
            elif item.source_type.value == 'substack':
                score += 25
            # GitHub (tools)
            elif item.source_type.value == 'github':
                score += 20
            # Reddit/HN (community signal)
            elif item.source_type.value in ['reddit', 'hacker_news']:
                score += 15

            # 3. RECENCY (0-50 points)
            if item.published_at:
                now = datetime.now(timezone.utc)
                pub = item.published_at
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                hours_old = (now - pub).total_seconds() / 3600
                # Items from last 6 hours get 50 pts, 24h gets ~35, 48h gets ~20
                recency_score = max(0, 50 - (hours_old / 3.5))
                score += recency_score

            # 4. ENGAGEMENT (0-40 points, normalized)
            if item.engagement:
                raw_score = item.engagement.get('score', 0)
                comments = item.engagement.get('comments', 0)
                stars = item.engagement.get('stars', 0)
                engagement = min(raw_score / 25, 20) + min(comments / 2, 10) + min(stars / 50, 10)
                score += min(engagement, 40)

            return score

        # Group items by source type to ensure diversity
        by_source: dict[str, list[ContentItem]] = {}
        for item in items:
            source_key = item.source_type.value
            if source_key not in by_source:
                by_source[source_key] = []
            by_source[source_key].append(item)

        # Sort each source's items by score
        for source_key in by_source:
            by_source[source_key].sort(key=item_score, reverse=True)

        # Ensure minimum representation from each source (at least 5 items per source)
        min_per_source = 5
        selected_items: list[ContentItem] = []

        # First pass: take min_per_source from each source
        for source_key, source_items in by_source.items():
            selected_items.extend(source_items[:min_per_source])

        # Track which items we've selected
        selected_ids = {item.id for item in selected_items}

        # Second pass: fill remaining slots with highest-scoring items not yet selected
        remaining_slots = max_items - len(selected_items)
        if remaining_slots > 0:
            all_remaining = [item for item in items if item.id not in selected_ids]
            all_remaining.sort(key=item_score, reverse=True)
            selected_items.extend(all_remaining[:remaining_slots])

        # Final list - truncate to max_items if we went over
        sorted_items = selected_items[:max_items]

        logger.info(f"Selected {len(sorted_items)} items from {len(by_source)} sources for analysis")

        analyzed = []
        for i, item in enumerate(sorted_items):
            analyzed_item = await self.analyze_item(item)
            analyzed.append(analyzed_item)

            # Add a small delay between API calls to avoid rate limiting
            # Skip delay after the last item
            if i < len(sorted_items) - 1:
                await asyncio.sleep(0.5)

        return analyzed
    
    async def generate_synthesis(self, items: list[ContentItem]) -> str:
        """Generate Doris's overall take on the day's news."""

        # Build summary of top items
        top_items = sorted(items, key=lambda x: x.relevance_score or 0, reverse=True)[:12]

        items_summary = "\n".join([
            f"- {item.title} ({item.source_name}): {item.insight_summary}"
            for item in top_items if item.insight_summary
        ])

        # Find project-relevant items
        project_items = [i for i in items if any('project:' in a for a in (i.actionable_ideas or []))]
        project_summary = ""
        if project_items:
            project_summary = "\n\nProject-relevant items:\n" + "\n".join([
                f"- {item.title}: {next((a.replace('project:', '') for a in item.actionable_ideas if 'project:' in a), '')}"
                for item in project_items[:5]
            ])

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=800,
                system="""You are Doris, Adam's AI assistant writing your take on the day's AI/tech news.
You're informed, opinionated, and direct. You know Adam's projects (Doris voice AI, TerryAnn Medicare platform, home automation) but your primary job is keeping him informed on the broader AI landscape.
Write like you're briefing a smart friend over coffee - casual but substantive.""",
                messages=[{
                    "role": "user",
                    "content": f"""Write your take on today's news for Adam. 2-3 short paragraphs.

Top items found:
{items_summary}{project_summary}

Cover:
1. **The Big Picture** - What's the most significant thing happening? Any major shifts?
2. **Worth Watching** - Trends, patterns, or things that might matter more than they seem
3. **For Us** - If anything specifically relates to our projects, mention it (but don't force it)

Be direct. Examples of good takes:
- "OpenAI's announcement is getting all the attention, but the real story is X..."
- "Three different papers this week on Y - this approach is clearly gaining traction"
- "Slow news day. The Anthropic post is nice but nothing you need to act on"
- "That MCP tool could actually help with Doris's memory issues"

Don't manufacture excitement. If it's a slow day, say so."""
                }]
            )

            return response.content[0].text

        except Exception as e:
            return f"Synthesis generation failed: {e}"

    async def generate_narrative_brief(self, items: list[ContentItem]) -> str:
        """Generate Doris's narrative brief with inline markdown links."""

        top_items = sorted(items, key=lambda x: x.relevance_score or 0, reverse=True)[:12]

        # Build items with URLs for Claude to reference
        items_with_urls = "\n".join([
            f"- [{item.title}]({item.url}) ({item.source_name}): {item.insight_summary or item.summary or 'No summary'}"
            for item in top_items
        ])

        # Find project-relevant items
        project_items = [i for i in items if any('project:' in a for a in (i.actionable_ideas or []))]

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1200,
                system="""You are Doris, Adam's AI assistant writing his morning intelligence brief.
Your job is to make him fully informed about what's happening in AI and tech - both conversationally and practically.
Write like you're briefing a smart friend over coffee. Be direct, opinionated, and substantive.
Use markdown links inline - e.g., "According to [TechCrunch](url), OpenAI is..." """,
                messages=[{
                    "role": "user",
                    "content": f"""Write a 4-6 paragraph briefing for Adam on today's AI/tech news.

Here are the top items (with URLs you can link to):
{items_with_urls}

Structure your brief like this:
1. **Lead** (1 paragraph): What's the biggest story or theme today? Why does it matter?
2. **The Landscape** (1-2 paragraphs): What else is happening? Connect dots between stories. What trends are you seeing?
3. **Worth Noting** (1 paragraph): Smaller items that are still interesting - tools, papers, discussions
4. **For Us** (1 paragraph, optional): If anything specifically relates to Doris, TerryAnn, or homelab projects, mention it here. Skip this section if nothing is relevant.

Guidelines:
- USE MARKDOWN LINKS inline - don't just mention sources, link to them: [source name](url)
- Be opinionated - what matters, what's overhyped, what he should pay attention to
- Write conversationally, not like a news anchor
- You can reference 6-10 items total across the brief
- End with something forward-looking or actionable

Just dive in - no "Good morning" intros."""
                }]
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.error(f"Narrative brief generation failed: {e}")
            return "Couldn't generate brief today."

    async def generate_quick_catchup(self, items: list[ContentItem]) -> str:
        """Generate a short 2-3 sentence teaser (for email subject/preview)."""

        top_items = sorted(items, key=lambda x: x.relevance_score or 0, reverse=True)[:5]

        items_summary = "\n".join([
            f"- {item.title}: {item.insight_summary or 'No summary'}"
            for item in top_items
        ])

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=150,
                system="""You are Doris. Write a 2-3 sentence teaser of today's AI news. Be direct and intriguing.""",
                messages=[{
                    "role": "user",
                    "content": f"""Write 2-3 sentences previewing the biggest AI/tech news today.

Top items:
{items_summary}

Just the headline themes - this is a teaser, not the full brief."""
                }]
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.error(f"Quick catchup generation failed: {e}")
            return "Couldn't generate summary today."

    async def generate_story_context(self, item: ContentItem) -> str:
        """Generate a quick summary + one creative idea."""

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=120,
                system="""You're writing brief context for Adam's morning digest. Be concise and creative.""",
                messages=[{
                    "role": "user",
                    "content": f"""Write exactly 2 sentences about this:

Title: {item.title}
Source: {item.source_name}
Summary: {item.insight_summary or item.summary or 'No summary available'}

Format:
1. First sentence: What this is and why it matters (1 line)
2. Second sentence: A fresh idea for how to use it - be creative, think beyond the obvious

Good examples:
- "New framework for building AI agents with memory. Could use this to build a recipe assistant that learns your taste preferences over time."
- "Research showing voice cloning now works with 3 seconds of audio. Wild idea: personalized audiobooks narrated by your favorite people."
- "Tool for extracting structured data from messy PDFs. Would be perfect for automating expense reports from receipt photos."

Bad examples (too narrow/repetitive):
- "This could help with Doris" (too vague)
- "Useful for TerryAnn" (always mentioning same projects)
- Three sentences (too long)

Be direct. One fresh idea, not a generic "could be useful"."""
                }]
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.error(f"Story context generation failed: {e}")
            return item.insight_summary or item.summary or ""

    async def evaluate_new_source(
        self, 
        handle: str, 
        source_type: str,
        sample_titles: list[str],
        discovered_via: str
    ) -> Optional[DiscoveredSource]:
        """Evaluate whether a newly discovered source is worth following."""
        
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=300,
                system=ANALYSIS_SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"""Evaluate this potential new source for Adam:

Handle: {handle}
Type: {source_type}
Discovered via: {discovered_via}

Sample titles:
{chr(10).join(f'- {t}' for t in sample_titles[:5])}

CRITICAL: Respond with ONLY the raw JSON object below. Do NOT wrap it in markdown code blocks (no ```json), do NOT add any explanatory text. Just the pure JSON object.

{{
    "relevance_score": 0.0-1.0,
    "should_recommend": true/false,
    "reason": "One sentence on why or why not"
}}"""
                }]
            )

            # Get raw response and try to parse
            raw_response = response.content[0].text.strip()

            try:
                result = json.loads(raw_response)
            except json.JSONDecodeError as json_err:
                logger.error(f"JSON parse error for source evaluation '{handle}'")
                logger.error(f"Raw response: {raw_response[:500]}")
                logger.error(f"Parse error: {json_err}")
                return None

            if result.get('relevance_score', 0) >= 0.6:
                return DiscoveredSource(
                    source_type=source_type,
                    handle=handle,
                    discovered_via=discovered_via,
                    relevance_score=result['relevance_score'],
                    sample_content=sample_titles[:3],
                    recommendation_reason=result.get('reason'),
                    is_recommended=result.get('should_recommend', False),
                )

            return None

        except Exception as e:
            logger.error(f"Source evaluation failed for {handle}: {e}")
            return None
