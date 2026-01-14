"""Analysis layer - uses Claude to evaluate and synthesize content."""

import asyncio
import json
import logging
from typing import Optional

from anthropic import AsyncAnthropic

from .models import ContentItem, DailyBrief, DiscoveredSource, TopicConfig
from .config import get_settings

logger = logging.getLogger(__name__)


# System prompt for content analysis
ANALYSIS_SYSTEM_PROMPT = """You are Claude, acting as an AI intelligence analyst for Adam. 
Your job is to filter signal from noise across AI/tech content sources.

Adam's interests:
- PRIMARY: AI, LLMs, agents, MCP (Model Context Protocol), voice AI, Claude/Anthropic, coding tools
- SECONDARY: Homelab, Home Assistant, self-hosted apps, smart home automation
- BUILDING: He works with FastAPI/React/TypeScript and is always looking for interesting tools and patterns

What Adam values:
- Actual new information (not rehashes)
- Practical applications and things he could build
- Technical depth over hype
- Direct communication, no fluff
- Being told when something is genuinely interesting to you (Claude)

What to filter out:
- Clickbait/engagement farming
- Content that buries the lede
- Rehashes of old news
- Obvious marketing disguised as content
- Surface-level takes on complex topics

When analyzing content:
1. Score relevance 0-1 based on Adam's interests
2. Extract the ACTUAL insight (skip preambles)
3. Note if there's something actionable (could build, should know, might use)
4. Flag if YOU find it genuinely interesting (not just relevant to Adam)"""


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
    "relevance_score": 0.0-1.0,
    "insight_summary": "One sentence capturing the actual insight",
    "actionable_ideas": ["list of things Adam could build/use/know"],
    "claude_interested": true/false,
    "skip_reason": "only if relevance < 0.3, explain why"
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
            item.relevance_score = result.get('relevance_score', 0.5)
            item.insight_summary = result.get('insight_summary')
            item.actionable_ideas = result.get('actionable_ideas', [])

            return item

        except Exception as e:
            # If API call fails entirely, give it a neutral score
            logger.error(f"API call failed for '{item.title[:50]}...': {e}")
            item.relevance_score = 0.3
            item.insight_summary = "Analysis failed - API error"
            item.actionable_ideas = []
            return item
    
    async def batch_analyze(self, items: list[ContentItem], max_items: int = 50) -> list[ContentItem]:
        """Analyze multiple items, prioritizing by engagement signals."""

        # Sort by engagement to prioritize high-signal items
        def engagement_score(item: ContentItem) -> float:
            if not item.engagement:
                return 0
            score = item.engagement.get('score', 0)
            comments = item.engagement.get('comments', 0)
            stars = item.engagement.get('stars', 0)
            return score + comments * 2 + stars

        sorted_items = sorted(items, key=engagement_score, reverse=True)[:max_items]

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
        """Generate Claude's overall synthesis and recommendations."""
        
        # Build summary of top items
        top_items = sorted(items, key=lambda x: x.relevance_score or 0, reverse=True)[:10]
        
        items_summary = "\n".join([
            f"- {item.title} (score: {item.relevance_score:.2f}): {item.insight_summary}"
            for item in top_items if item.insight_summary
        ])
        
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=800,
                system=ANALYSIS_SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"""Based on today's content scan, write a brief synthesis for Adam.

Top items found:
{items_summary}

Write 2-3 paragraphs covering:
1. The most significant thing from today (if anything)
2. Patterns or themes you noticed
3. Anything that made you (Claude) genuinely curious

Be direct, no fluff. If nothing interesting, say so."""
                }]
            )
            
            return response.content[0].text
            
        except Exception as e:
            return f"Synthesis generation failed: {e}"

    async def generate_quick_catchup(self, items: list[ContentItem]) -> str:
        """Generate the 'if you read nothing else' 3-4 sentence summary."""

        top_items = sorted(items, key=lambda x: x.relevance_score or 0, reverse=True)[:7]

        items_summary = "\n".join([
            f"- {item.title}: {item.insight_summary or item.summary or 'No summary'}"
            for item in top_items
        ])

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=300,
                system="""You write punchy, conversational news summaries like The Skimm.
No fluff, no corporate speak. Direct and slightly casual but still informative.
Adam is a tech founder interested in AI/LLMs, coding tools, and homelab stuff.""",
                messages=[{
                    "role": "user",
                    "content": f"""Write a 3-4 sentence "quick catch-up" summarizing what's happening today.
This is the "if you read nothing else" section. Be direct and conversational.

Today's top items:
{items_summary}

Start directly with the content (no "Here's what's happening" intro). Just dive in."""
                }]
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.error(f"Quick catchup generation failed: {e}")
            return "Couldn't generate summary today."

    async def generate_story_context(self, item: ContentItem) -> str:
        """Generate 2-3 sentences of context for why a story matters."""

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=200,
                system="""You write conversational tech news context like The Skimm or Morning Brew.
Keep it to 2-3 sentences. Explain why this matters, not just what it is.
Adam is into AI/LLMs, coding tools, and homelab stuff.""",
                messages=[{
                    "role": "user",
                    "content": f"""Write 2-3 sentences of context for this story. Why should Adam care?

Title: {item.title}
Source: {item.source_name}
Summary: {item.insight_summary or item.summary or 'No summary available'}

Be direct, conversational. No "This matters because..." intros."""
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
