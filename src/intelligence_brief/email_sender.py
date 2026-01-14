"""Email sender - sends brief notifications via Gmail."""

import os
from typing import Optional


async def send_brief_email(
    brief_url: str,
    quick_catchup: str,
    recipient: Optional[str] = None
) -> bool:
    """
    Send brief notification email.
    
    Note: This is a placeholder. In production, this would use:
    - Gmail API via MCP
    - Or SMTP directly
    - Or a service like SendGrid/Postmark
    
    For now, we'll print what would be sent.
    """
    recipient = recipient or os.environ.get("EMAIL_RECIPIENT")
    
    if not recipient:
        print("No email recipient configured")
        return False
    
    subject = "🧠 Your Intelligence Brief is Ready"
    
    body = f"""Your daily intelligence brief is ready.

THE QUICK CATCH-UP
{quick_catchup}

Read the full brief: {brief_url}

---
Intelligence Brief by Claude
"""
    
    print(f"Would send email to: {recipient}")
    print(f"Subject: {subject}")
    print(f"Body preview: {body[:200]}...")
    
    # TODO: Implement actual email sending
    # Options:
    # 1. Gmail MCP (if running from Claude Desktop)
    # 2. SMTP with app password
    # 3. SendGrid/Postmark API
    
    return True
