"""Publisher - saves briefs to Supabase and sends notifications."""

import os
from datetime import datetime
from typing import Optional

from supabase import create_client, Client

from .models import DailyBrief, ContentItem, StoryItem


class BriefPublisher:
    """Publishes briefs to Supabase."""
    
    def __init__(
        self, 
        supabase_url: Optional[str] = None,
        supabase_key: Optional[str] = None
    ):
        self.supabase_url = supabase_url or os.environ.get("SUPABASE_URL")
        self.supabase_key = supabase_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        
        if not self.supabase_url or not self.supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        
        self.client: Client = create_client(self.supabase_url, self.supabase_key)
    
    def _serialize_item(self, item: ContentItem) -> dict:
        """Serialize a ContentItem to JSON-compatible dict."""
        return {
            "id": item.id,
            "title": item.title,
            "url": str(item.url),
            "source_name": item.source_name,
            "source_type": item.source_type.value,
            "author": item.author,
            "summary": item.summary,
            "insight_summary": item.insight_summary,
            "actionable_ideas": item.actionable_ideas,
            "relevance_score": item.relevance_score,
            "engagement": item.engagement,
            "tags": item.tags,
        }
    
    def _serialize_story(self, story: StoryItem) -> dict:
        """Serialize a StoryItem to JSON-compatible dict."""
        return {
            "headline": story.headline,
            "context": story.context,
            "source_url": str(story.source_url),
            "source_name": story.source_name,
            "source_item": self._serialize_item(story.source_item),
        }
    
    def _serialize_brief(self, brief: DailyBrief) -> dict:
        """Serialize a DailyBrief for Supabase."""
        return {
            "date": brief.date,
            "generated_at": brief.generated_at.isoformat(),
            "total_items_scanned": brief.total_items_scanned,
            "sources_checked": brief.sources_checked,
            # New Skimm-style fields
            "quick_catchup": brief.quick_catchup,
            "whats_moving": [self._serialize_story(s) for s in brief.whats_moving],
            "worth_a_click": [self._serialize_item(i) for i in brief.worth_a_click],
            "claudes_take": brief.claudes_take,
            # Legacy fields
            "top_signal": [self._serialize_item(i) for i in brief.top_signal],
            "builder_corner": [self._serialize_item(i) for i in brief.builder_corner],
            "paper_of_the_day": self._serialize_item(brief.paper_of_the_day) if brief.paper_of_the_day else None,
            "homelab_corner": [self._serialize_item(i) for i in brief.homelab_corner],
            "honorable_mentions": [self._serialize_item(i) for i in brief.honorable_mentions],
            "new_voices": [v.model_dump() for v in brief.new_voices],
            "synthesis": brief.synthesis,
        }
    
    async def publish(self, brief: DailyBrief) -> str:
        """Publish brief to Supabase. Returns the URL."""
        data = self._serialize_brief(brief)
        
        result = self.client.table("briefs").upsert(
            data,
            on_conflict="date"
        ).execute()
        
        if not result.data:
            raise Exception("Failed to publish brief to Supabase")
        
        base_url = os.environ.get("SITE_URL", "https://adambell.ai")
        return f"{base_url}/briefs/{brief.date}"
    
    async def get_latest_brief_url(self) -> Optional[str]:
        """Get URL of the most recent brief."""
        result = self.client.table("briefs").select("date").order(
            "date", desc=True
        ).limit(1).execute()
        
        if result.data:
            date = result.data[0]["date"]
            base_url = os.environ.get("SITE_URL", "https://adambell.ai")
            return f"{base_url}/briefs/{date}"
        
        return None
