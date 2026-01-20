"""Configuration management."""

from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # Anthropic
    anthropic_api_key: str = Field(..., description="Anthropic API key")
    anthropic_model: str = Field("claude-sonnet-4-20250514", description="Model to use for analysis")
    
    # Substack
    substack_follows: str = Field(
        "ahead-of-ai,a16z,the-ai-architect,ai-supremacy,latent-space,simonwillison,bensbites,theaiopportunities,mattrobinsonaistreet",
        description="Comma-separated list of Substack handles"
    )
    
    # Reddit
    reddit_subs: str = Field(
        "LocalLLaMA,MachineLearning,selfhosted,homelab",
        description="Comma-separated list of subreddits"
    )
    
    # YouTube (optional - needs API key)
    youtube_api_key: Optional[str] = None
    youtube_channels: str = Field("", description="Comma-separated YouTube channel IDs")
    
    # Topics
    primary_topics: str = Field(
        "ai,llm,agents,mcp,voice-ai,claude,anthropic,openai,coding-tools,developer-tools",
        description="Primary topics to track"
    )
    secondary_topics: str = Field(
        "home-assistant,homelab,raspberry-pi,smart-home",
        description="Secondary topics (homelab, etc.)"
    )
    
    # Company blogs to watch (RSS feeds)
    company_blogs: str = Field(
        # Anthropic - use Olshansk scraped feeds (GitHub raw URLs)
        "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml,"
        "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_engineering.xml,"
        "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_research.xml,"
        # OpenAI - corrected URL
        "https://openai.com/news/rss.xml,"
        # Google AI Research
        "https://research.google/blog/rss,"
        # HuggingFace - keep but may be unreliable
        "https://huggingface.co/blog/feed.xml,"
        # The AI Furnace (Beehiiv)
        "https://theaifurnace.beehiiv.com/feed",
        description="Comma-separated RSS feed URLs"
    )

    # Mainstream news sources (AI/tech coverage)
    news_sources: str = Field(
        # NYT Technology
        "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml,"
        # Washington Post Technology
        "https://feeds.washingtonpost.com/rss/business/technology,"
        # The Verge AI
        "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml,"
        # Ars Technica AI
        "https://arstechnica.com/ai/feed/,"
        # TechCrunch AI
        "https://techcrunch.com/category/artificial-intelligence/feed/,"
        # Wired AI
        "https://www.wired.com/feed/tag/ai/latest/rss,"
        # MIT Technology Review AI
        "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
        description="Mainstream news RSS feeds for AI/tech coverage"
    )

    @property
    def news_source_list(self) -> list[str]:
        return [s.strip() for s in self.news_sources.split(",") if s.strip()]

    # Podcasts (transcribed via Groq)
    groq_api_key: Optional[str] = Field(None, description="Groq API key for podcast transcription")
    podcast_feeds: str = Field(
        "https://anchor.fm/s/d8bace4c/podcast/rss,"  # The AI Daily Brief
        "https://feeds.megaphone.fm/TPG7603691495,"   # Me, Myself, and AI (MIT)
        "https://feeds.acast.com/public/shows/ted-ai,"  # The TED AI Show
        "https://rss.buzzsprout.com/2502664.rss,"     # AI Today
        "https://feeds.simplecast.com/Sl5CSM3S",      # The Daily (NYT)
        description="Comma-separated podcast RSS feed URLs"
    )

    @property
    def podcast_feed_list(self) -> list[str]:
        return [f.strip() for f in self.podcast_feeds.split(",") if f.strip()]
    
    # Notification
    imessage_recipient: Optional[str] = Field(None, description="Phone number for iMessage")
    email_recipient: Optional[str] = Field(None, description="Email address for notifications")
    smtp_user: Optional[str] = Field(None, description="Gmail address for sending (deprecated)")
    smtp_password: Optional[str] = Field(None, description="Gmail app password (deprecated)")
    resend_api_key: Optional[str] = Field(None, description="Resend API key")
    brief_time: str = Field("09:00", description="Time to send brief (HH:MM)")
    timezone: str = Field("America/New_York", description="Timezone for scheduling")
    
    # Database
    db_path: str = Field("data/intelligence.db", description="SQLite database path")
    
    # Behavior
    max_items_per_source: int = Field(20, description="Max items to fetch per source")
    lookback_hours: int = Field(24, description="How far back to look for content")
    
    @property
    def substack_list(self) -> list[str]:
        return [s.strip() for s in self.substack_follows.split(",") if s.strip()]
    
    @property
    def reddit_list(self) -> list[str]:
        return [s.strip() for s in self.reddit_subs.split(",") if s.strip()]
    
    @property
    def primary_topic_list(self) -> list[str]:
        return [t.strip() for t in self.primary_topics.split(",") if t.strip()]
    
    @property
    def secondary_topic_list(self) -> list[str]:
        return [t.strip() for t in self.secondary_topics.split(",") if t.strip()]
    
    @property
    def company_blog_list(self) -> list[str]:
        return [b.strip() for b in self.company_blogs.split(",") if b.strip()]


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
