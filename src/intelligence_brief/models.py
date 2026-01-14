"""Core data models for intelligence brief."""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, HttpUrl


class ContentType(str, Enum):
    """Type of content item."""
    ARTICLE = "article"
    PAPER = "paper"
    REPOSITORY = "repository"
    DISCUSSION = "discussion"
    VIDEO = "video"
    ANNOUNCEMENT = "announcement"
    NOTE = "note"
    PODCAST = "podcast"


class SourceType(str, Enum):
    """Content source type."""
    SUBSTACK = "substack"
    ARXIV = "arxiv"
    HACKER_NEWS = "hacker_news"
    GITHUB = "github"
    REDDIT = "reddit"
    YOUTUBE = "youtube"
    COMPANY_BLOG = "company_blog"
    TWITTER = "twitter"
    MEDIUM = "medium"
    HUGGINGFACE = "huggingface"
    NYT = "nyt"
    RSS = "rss"
    PODCAST = "podcast"


class ContentItem(BaseModel):
    """A single piece of content from any source."""
    
    id: str = Field(..., description="Unique identifier (source-specific)")
    source_type: SourceType
    source_name: str = Field(..., description="Specific source (e.g., 'ahead-of-ai' for Substack)")
    content_type: ContentType
    
    title: str
    url: HttpUrl
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Content
    summary: Optional[str] = Field(None, description="Original summary/abstract if available")
    full_text: Optional[str] = Field(None, description="Full content if fetched")
    
    # Metadata
    tags: list[str] = Field(default_factory=list)
    engagement: Optional[dict] = Field(None, description="Likes, comments, stars, etc.")
    
    # Analysis (filled in by Claude)
    relevance_score: Optional[float] = Field(None, ge=0, le=1, description="How relevant to Adam's interests")
    insight_summary: Optional[str] = Field(None, description="Claude's extracted insight")
    actionable_ideas: list[str] = Field(default_factory=list, description="What we might build/use")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class FollowedSource(BaseModel):
    """A source Adam explicitly follows."""
    
    source_type: SourceType
    handle: str
    display_name: Optional[str] = None
    added_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True


class DiscoveredSource(BaseModel):
    """A source discovered through cross-references or trending."""
    
    source_type: SourceType
    handle: str
    display_name: Optional[str] = None
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    discovered_via: str
    
    relevance_score: float = Field(..., ge=0, le=1)
    sample_content: list[str] = Field(default_factory=list)
    recommendation_reason: Optional[str] = None
    
    is_recommended: bool = False
    was_followed: bool = False
    was_dismissed: bool = False


class StoryItem(BaseModel):
    """A story for the 'What's Moving' section - richer context than raw ContentItem."""
    
    headline: str = Field(..., description="Punchy headline we write")
    context: str = Field(..., description="2-3 sentences of why this matters")
    source_url: HttpUrl
    source_name: str
    source_item: ContentItem


class DailyBrief(BaseModel):
    """The daily intelligence brief - newsletter style."""
    
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    date: str = Field(..., description="Brief date in YYYY-MM-DD format")
    
    # The Skimm-style sections
    quick_catchup: str = Field(..., description="3-4 sentence 'if you read nothing else' summary")
    whats_moving: list[StoryItem] = Field(default_factory=list, description="5-7 main stories with context")
    worth_a_click: list[ContentItem] = Field(default_factory=list, description="Quick links that didn't make main")
    claudes_take: Optional[str] = Field(None, description="Editorial perspective and recommendations")
    
    # Legacy fields for backwards compat (can remove later)
    top_signal: list[ContentItem] = Field(default_factory=list)
    builder_corner: list[ContentItem] = Field(default_factory=list)
    paper_of_the_day: Optional[ContentItem] = None
    homelab_corner: list[ContentItem] = Field(default_factory=list)
    honorable_mentions: list[ContentItem] = Field(default_factory=list)
    new_voices: list[DiscoveredSource] = Field(default_factory=list)
    synthesis: Optional[str] = None
    
    # Stats
    total_items_scanned: int = 0
    sources_checked: list[str] = Field(default_factory=list)


class TopicConfig(BaseModel):
    """Configuration for a topic of interest."""
    
    name: str
    keywords: list[str]
    weight: float = Field(1.0, ge=0, le=2)
    is_primary: bool = True
