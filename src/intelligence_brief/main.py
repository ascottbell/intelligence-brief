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
from .models import DailyBrief


async def run_aggregation(publish: bool = False, notify: bool = False, email: bool = False):
    """Run the full aggregation and analysis pipeline."""
    settings = get_settings()
    aggregator = Aggregator()
    generator = BriefGenerator()
    
    try:
        print(f"Starting aggregation at {datetime.now().isoformat()}")
        
        # Fetch and analyze
        items, sources = await aggregator.aggregate_and_analyze()
        
        # Generate brief
        brief = await generator.generate_brief(items, sources)
        
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
    if not resend_api_key:
        print("✗ Resend API key not configured, skipping email")
        return
    
    resend.api_key = resend_api_key
    
    # Build Whats Moving section
    whats_moving_html = ""
    if brief.whats_moving:
        stories_html = ""
        for story in brief.whats_moving:
            stories_html += f"""
            <div style="margin-bottom: 20px;">
                <p style="font-weight: 600; margin: 0 0 4px 0;">▸ {story.headline}</p>
                <p style="margin: 0 0 4px 0; color: #44403c;">{story.context}</p>
                <a href="{story.source_url}" style="font-size: 14px; color: #2563eb;">Read more →</a>
            </div>
            """
        whats_moving_html = f"""
        <div style="margin-bottom: 32px;">
            <p style="font-size: 12px; color: #78716c; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px;">Whats Moving</p>
            {stories_html}
        </div>
        """
    
    # Build Worth a Click section
    worth_a_click_html = ""
    if brief.worth_a_click:
        links_html = ""
        for item in brief.worth_a_click:
            links_html += f"""
            <li style="margin-bottom: 8px;">
                <a href="{item.url}" style="color: #2563eb; text-decoration: none;">{item.title}</a>
                <span style="color: #78716c;"> ({item.source_name})</span>
            </li>
            """
        worth_a_click_html = f"""
        <div style="margin-bottom: 32px;">
            <p style="font-size: 12px; color: #78716c; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px;">Worth a Click</p>
            <ul style="padding-left: 20px; margin: 0;">{links_html}</ul>
        </div>
        """
    
    # Build Claudes Take section
    claudes_take_html = ""
    if brief.claudes_take:
        take_text = brief.claudes_take.replace("\n", "<br>")
        claudes_take_html = f"""
        <div style="margin-bottom: 32px;">
            <p style="font-size: 12px; color: #78716c; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px;">Claudes Take</p>
            <p style="color: #44403c; font-style: italic;">{take_text}</p>
        </div>
        """
    
    # Quick catchup text
    catchup_text = brief.quick_catchup.replace("\n", "<br>")
    
    # Full HTML email
    html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Georgia, serif; line-height: 1.6; color: #1c1917; max-width: 600px; margin: 0 auto; padding: 20px; }}
    </style>
</head>
<body>
    <p style="font-size: 12px; color: #78716c; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px;">Intelligence Brief - {brief.date}</p>
    
    <div style="margin-bottom: 32px;">
        <p style="font-size: 12px; color: #78716c; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px;">The Quick Catch-Up</p>
        <p style="font-size: 18px; color: #1c1917; line-height: 1.5;">{catchup_text}</p>
    </div>
    
    {whats_moving_html}
    
    {worth_a_click_html}
    
    {claudes_take_html}
    
    <p style="font-size: 12px; color: #a8a29e; margin-top: 32px; padding-top: 16px; border-top: 1px solid #e7e5e4;">
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
