"""Interface for Doris to query intelligence briefs.

This module provides functions Doris can use to retrieve and search briefs.
Import this from Doris when she needs to reference brief content.

Usage in Doris:
    sys.path.insert(0, "/Users/macmini/Projects/intelligence-brief/src")
    from intelligence_brief.doris_interface import (
        get_todays_brief,
        get_brief_for_date,
        search_briefs,
        get_recent_brief_summaries,
    )
"""

from datetime import datetime, timedelta
from typing import Optional

from .brief_storage import (
    get_today_brief,
    get_brief_by_date,
    search_briefs as _search_briefs,
    get_recent_briefs,
)


def get_todays_brief() -> Optional[dict]:
    """
    Get today's intelligence brief.

    Returns dict with:
        - date: The brief date
        - narrative: Doris's full narrative (THE BRIEF section)
        - quick_catchup: Short teaser
        - items: List of items covered
        - sources_checked: List of sources scanned

    Returns None if no brief exists for today.
    """
    return get_today_brief()


def get_brief_for_date(date: str) -> Optional[dict]:
    """
    Get a brief for a specific date.

    Args:
        date: Date in YYYY-MM-DD format (e.g., "2026-01-20")

    Returns dict with brief content, or None if not found.
    """
    return get_brief_by_date(date)


def search_briefs(query: str, days: int = 14) -> list[dict]:
    """
    Search briefs for a specific topic or keyword.

    Args:
        query: Search term (searches narrative and item titles)
        days: How far back to search (default 14 days)

    Returns list of matching briefs with relevant content.
    """
    return _search_briefs(query, days)


def get_recent_brief_summaries(days: int = 7) -> list[dict]:
    """
    Get summaries of recent briefs for quick reference.

    Args:
        days: How many days of briefs to retrieve

    Returns list of briefs with date, quick_catchup, and item count.
    """
    briefs = get_recent_briefs(days)
    summaries = []
    for brief in briefs:
        summaries.append({
            "date": brief["date"],
            "quick_catchup": brief["quick_catchup"],
            "item_count": len(brief.get("items", [])),
            "sources": len(brief.get("sources_checked", [])),
        })
    return summaries


def get_brief_item_by_topic(topic: str) -> Optional[dict]:
    """
    Find a specific item from recent briefs by topic keyword.

    Useful when Adam says "that thing about X from the brief".

    Args:
        topic: Keyword to search for in item titles

    Returns the matching item dict with title, url, insight, etc.
    """
    results = _search_briefs(topic, days=14)
    for brief in results:
        for item in brief.get("items", []):
            if topic.lower() in item.get("title", "").lower():
                return {
                    "brief_date": brief["date"],
                    "title": item["title"],
                    "url": item["url"],
                    "source": item.get("source_name"),
                    "insight": item.get("insight_summary"),
                }
    return None


# Convenience function for natural language queries
def answer_brief_question(question: str) -> str:
    """
    Answer a question about recent briefs.

    This is a helper for Doris to respond to questions like:
    - "What was in this morning's brief?"
    - "Did you mention anything about OpenAI recently?"
    - "What did you say about that MCP thing?"

    Args:
        question: Natural language question about briefs

    Returns a formatted answer string.
    """
    question_lower = question.lower()

    # Check for "today" or "this morning"
    if any(w in question_lower for w in ["today", "this morning", "morning brief"]):
        brief = get_todays_brief()
        if brief:
            return f"In today's brief ({brief['date']}):\n\n{brief['narrative']}"
        else:
            return "I haven't sent a brief today yet."

    # Check for date references
    if "yesterday" in question_lower:
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        brief = get_brief_by_date(yesterday)
        if brief:
            return f"In yesterday's brief:\n\n{brief['narrative']}"
        return "I didn't send a brief yesterday."

    # Check for "monday", "wednesday", "friday"
    day_map = {"monday": 0, "wednesday": 2, "friday": 4}
    for day_name, day_num in day_map.items():
        if day_name in question_lower:
            # Find most recent occurrence of that day
            today = datetime.utcnow()
            days_back = (today.weekday() - day_num) % 7
            if days_back == 0:
                days_back = 7  # Last week's instance
            target_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
            brief = get_brief_by_date(target_date)
            if brief:
                return f"In {day_name.title()}'s brief ({brief['date']}):\n\n{brief['narrative']}"
            return f"I don't have a brief from last {day_name.title()}."

    # Search for topic keywords (extract key terms from question)
    # Simple approach: look for nouns/terms after common question words
    search_terms = []
    skip_words = {"what", "did", "you", "say", "about", "mention", "the", "that", "from", "brief", "in", "a", "an", "any", "anything", "something"}
    for word in question_lower.split():
        word_clean = word.strip("?.,!")
        if word_clean and word_clean not in skip_words and len(word_clean) > 2:
            search_terms.append(word_clean)

    if search_terms:
        query = " ".join(search_terms[:3])  # Use first 3 meaningful terms
        results = _search_briefs(query, days=14)
        if results:
            brief = results[0]
            return f"I mentioned that in the {brief['date']} brief:\n\n{brief['narrative'][:500]}..."

    return "I couldn't find anything matching that in recent briefs. Could you be more specific?"
