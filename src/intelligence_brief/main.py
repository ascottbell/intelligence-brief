"""Main entry point for Intelligence Brief."""

import asyncio
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import resend

from dotenv import load_dotenv

# Load .env file from project root
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

from .aggregator import Aggregator, BriefGenerator
from .config import get_settings
from .models import DailyBrief, DiscoveredSource, SourceType


def log_brief_to_doris_memory(brief: DailyBrief):
    """
    Log key brief contents to Doris memory so she can reference them later.

    Stores:
    - Each story from "What's Moving" as a brief_topic
    - Key recommendations from Doris's Take as brief_recommendation
    """
    try:
        # Import Doris memory store
        sys.path.insert(0, "/Users/macmini/Projects/doris")
        from memory.store import store_memory

        brief_date = brief.date
        stored_count = 0

        # Store each "What's Moving" story
        for story in brief.whats_moving:
            content = f"{story.headline}: {story.context}"
            store_memory(
                content=content,
                category="brief_topic",
                subject=brief_date,
                source=f"intelligence_brief:{brief_date}",
                confidence=0.9,
                metadata={
                    "url": str(story.source_url),  # Convert HttpUrl to string
                    "source_name": story.source_name,
                    "brief_date": brief_date,
                }
            )
            stored_count += 1

        # Store Doris's Take as recommendations
        if brief.claudes_take:
            store_memory(
                content=f"Brief recommendations ({brief_date}): {brief.claudes_take}",
                category="brief_recommendation",
                subject=brief_date,
                source=f"intelligence_brief:{brief_date}",
                confidence=0.9,
                metadata={"brief_date": brief_date}
            )
            stored_count += 1

        # Store the quick catchup as a summary
        if brief.quick_catchup:
            store_memory(
                content=f"Brief summary ({brief_date}): {brief.quick_catchup}",
                category="brief_summary",
                subject=brief_date,
                source=f"intelligence_brief:{brief_date}",
                confidence=0.9,
                metadata={"brief_date": brief_date}
            )
            stored_count += 1

        print(f"✓ Logged {stored_count} items to Doris memory")
        return stored_count

    except Exception as e:
        print(f"⚠ Could not log to Doris memory: {e}")
        return 0


async def run_aggregation(publish: bool = False, notify: bool = False, email: bool = False):
    """Run the full aggregation and analysis pipeline."""
    from .memory_integration import get_dynamic_topics, get_hours_since_last_brief
    from .source_discovery import discover_sources_for_topics, get_all_discovered_sources

    settings = get_settings()
    aggregator = Aggregator()
    generator = BriefGenerator()

    try:
        print(f"Starting aggregation at {datetime.now().isoformat()}")

        # Step 1: Get dynamic topics from Doris memory
        print("Fetching dynamic topics from Doris memory...")
        hours_back = get_hours_since_last_brief()
        dynamic_topics = get_dynamic_topics(
            anthropic_api_key=settings.anthropic_api_key,
            hours_since_last_brief=hours_back,
            model=settings.anthropic_model
        )
        print(f"  Found {len(dynamic_topics)} dynamic topics: {dynamic_topics[:5]}...")

        # Step 2: Discover new sources for gap topics
        print("Checking for source gaps and discovering new sources...")
        newly_discovered = await discover_sources_for_topics(
            dynamic_topics=dynamic_topics,
            settings=settings,
            max_new_sources=3
        )
        if newly_discovered:
            print(f"  Discovered {len(newly_discovered)} new sources:")
            for src in newly_discovered:
                print(f"    - {src['name']} ({src['type']}) for topic '{src['topic']}'")

        # Step 3: Fetch and analyze (aggregator now includes discovered sources)
        items, sources = await aggregator.aggregate_and_analyze()

        # Step 4: Generate brief
        brief = await generator.generate_brief(items, sources)

        # Convert discovered sources to DiscoveredSource objects for the brief
        if newly_discovered:
            brief.new_voices = [
                DiscoveredSource(
                    source_type=SourceType.REDDIT if src.get('type') == 'reddit' else SourceType.RSS,
                    handle=src.get('name', ''),
                    display_name=src.get('name'),
                    discovered_via=f"topic:{src.get('topic', 'unknown')}",
                    relevance_score=src.get('quality_score', 0.5),
                    sample_content=src.get('topics_covered', []),
                    recommendation_reason=src.get('reason'),
                    is_recommended=True,
                )
                for src in newly_discovered
            ]

        # Step 5: Store brief in searchable database
        print("Storing brief in database...")
        from .brief_storage import store_brief
        brief_id = store_brief(brief)
        print(f"  Stored brief with ID: {brief_id}")

        # Step 6: Log brief contents to Doris memory for future reference
        print("Logging brief to Doris memory...")
        log_brief_to_doris_memory(brief)

        # Format for display
        text = generator.format_brief_text(brief)
        print(text)
        
        # Send email notification with full brief content
        if email and settings.email_recipient:
            send_email_resend(
                recipient=settings.email_recipient,
                brief=brief,
                resend_api_key=settings.resend_api_key,
            )
        
        # Send iMessage notification (only works on Mac)
        if notify and settings.imessage_recipient:
            message = text[:2000] + "\n\n[Truncated]" if len(text) > 2000 else text
            send_imessage(message, settings.imessage_recipient)
        
        return brief, text, None
        
    finally:
        await aggregator.close()


def send_email_resend(
    recipient: str,
    brief: DailyBrief,
    resend_api_key: str | None = None,
):
    """Send brief notification via Resend with full brief content."""
    import markdown

    if not resend_api_key:
        print("✗ Resend API key not configured, skipping email")
        return

    resend.api_key = resend_api_key

    # Convert Doris's narrative (markdown with links) to HTML
    narrative_html = ""
    if brief.claudes_take:
        # Convert markdown to HTML (handles [link](url) syntax)
        narrative_html = markdown.markdown(brief.claudes_take)

    # Build Research Radar section
    research_html = ""
    research_items = [brief.paper_of_the_day] if brief.paper_of_the_day else []
    research_items.extend(brief.homelab_corner or [])
    if research_items:
        items_html = ""
        for item in research_items[:4]:
            items_html += f"""
            <div style="margin-bottom: 12px;">
                <a href="{item.url}" style="color: #2563eb; text-decoration: none; font-weight: 500;">{item.title}</a>
                <p style="margin: 4px 0 0 0; font-size: 14px; color: #57534e;">{item.insight_summary or ''}</p>
            </div>
            """
        research_html = f"""
        <div style="margin-bottom: 28px;">
            <p style="font-size: 11px; color: #78716c; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 12px; font-weight: 600;">📚 Research Radar</p>
            {items_html}
        </div>
        """

    # Build Builder's Bench section
    tools_html = ""
    if brief.builder_corner:
        items_html = ""
        for item in brief.builder_corner[:5]:
            items_html += f"""
            <div style="margin-bottom: 12px;">
                <a href="{item.url}" style="color: #2563eb; text-decoration: none; font-weight: 500;">{item.title}</a>
                <span style="color: #78716c; font-size: 13px;"> ({item.source_name})</span>
                <p style="margin: 4px 0 0 0; font-size: 14px; color: #57534e;">{item.insight_summary or ''}</p>
            </div>
            """
        tools_html = f"""
        <div style="margin-bottom: 28px;">
            <p style="font-size: 11px; color: #78716c; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 12px; font-weight: 600;">🛠️ Builder's Bench</p>
            {items_html}
        </div>
        """

    # Build Industry Watch section
    industry_html = ""
    if brief.top_signal:
        items_html = ""
        for item in brief.top_signal[:5]:
            items_html += f"""
            <div style="margin-bottom: 12px;">
                <a href="{item.url}" style="color: #2563eb; text-decoration: none; font-weight: 500;">{item.title}</a>
                <span style="color: #78716c; font-size: 13px;"> ({item.source_name})</span>
            </div>
            """
        industry_html = f"""
        <div style="margin-bottom: 28px;">
            <p style="font-size: 11px; color: #78716c; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 12px; font-weight: 600;">📰 Industry Watch</p>
            {items_html}
        </div>
        """

    # Build Quick Links section
    links_html = ""
    if brief.worth_a_click:
        items_html = ""
        for item in brief.worth_a_click[:8]:
            items_html += f"""
            <li style="margin-bottom: 6px;">
                <a href="{item.url}" style="color: #2563eb; text-decoration: none;">{item.title}</a>
                <span style="color: #a8a29e; font-size: 12px;"> ({item.source_name})</span>
            </li>
            """
        links_html = f"""
        <div style="margin-bottom: 28px;">
            <p style="font-size: 11px; color: #78716c; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 12px; font-weight: 600;">🔗 Quick Links</p>
            <ul style="padding-left: 18px; margin: 0; font-size: 14px;">{items_html}</ul>
        </div>
        """

    # Full HTML email - new format
    html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #1c1917; max-width: 640px; margin: 0 auto; padding: 24px; }}
        a {{ color: #2563eb; }}
    </style>
</head>
<body>
    <p style="font-size: 11px; color: #a8a29e; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 4px;">Intelligence Brief</p>
    <p style="font-size: 13px; color: #78716c; margin-bottom: 24px;">{brief.date}</p>

    <!-- THE BRIEF - Doris's Narrative -->
    <div style="margin-bottom: 40px; font-size: 16px; line-height: 1.7;">
        {narrative_html}
    </div>

    <!-- DEEPER DIVES -->
    <div style="border-top: 1px solid #e7e5e4; padding-top: 24px;">
        <p style="font-size: 11px; color: #a8a29e; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 20px;">Deeper Dives</p>

        {research_html}
        {tools_html}
        {industry_html}
        {links_html}
    </div>

    <p style="font-size: 11px; color: #a8a29e; margin-top: 32px; padding-top: 16px; border-top: 1px solid #e7e5e4;">
        Scanned {brief.total_items_scanned} items from {len(brief.sources_checked)} sources
    </p>
</body>
</html>
"""
    
    try:
        params: resend.Emails.SendParams = {
            "from": "Intelligence Brief <onboarding@resend.dev>",
            "to": [recipient],
            "subject": f"🧠 Intelligence Brief - {brief.date}",
            "html": html_body,
        }
        result = resend.Emails.send(params)
        print(f"✓ Email sent to {recipient} (id: {result['id']})")
    except Exception as e:
        print(f"✗ Failed to send email: {e}")


def send_imessage(message: str, recipient: str):
    """Send message via iMessage using AppleScript."""
    escaped = message.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    script = f'''
    tell application "Messages"
        set targetService to 1st account whose service type = iMessage
        set targetBuddy to participant "{recipient}" of targetService
        send "{escaped}" to targetBuddy
    end tell
    '''

    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
        print(f"✓ Sent iMessage to {recipient}")
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to send iMessage: {e}")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Intelligence Brief - AI news aggregator")
    parser.add_argument(
        "command",
        choices=["aggregate", "run", "test"],
        default="run",
        nargs="?",
        help="Command to run"
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Send iMessage notification (Mac only)"
    )
    parser.add_argument(
        "--email",
        action="store_true",
        help="Send email notification"
    )
    
    args = parser.parse_args()
    
    if args.command == "test":
        settings = get_settings()
        print("Configuration loaded:")
        print(f"  Substacks: {settings.substack_list}")
        print(f"  Subreddits: {settings.reddit_list}")
        print(f"  Primary topics: {settings.primary_topic_list}")
        print(f"  Secondary topics: {settings.secondary_topic_list}")
        print(f"  Company blogs: {len(settings.company_blog_list)} feeds")
        print(f"  iMessage recipient: {settings.imessage_recipient or 'Not set'}")
        print(f"  Email recipient: {settings.email_recipient or 'Not set'}")
        print(f"  Resend configured: {'Yes' if settings.resend_api_key else 'No'}")
        return
    
    if args.command == "aggregate":
        asyncio.run(run_aggregation(publish=False, notify=args.notify, email=args.email))
    
    elif args.command == "run":
        # Full pipeline: aggregate and email (no Supabase)
        asyncio.run(run_aggregation(
            publish=False,
            notify=False,  # iMessage wont work from Railway
            email=True,    # Email with full brief content
        ))


if __name__ == "__main__":
    main()
