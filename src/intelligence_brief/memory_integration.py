"""
Doris Memory Integration

Pulls recent memories from Doris to generate dynamic topics for the brief.
This allows the brief to surface content relevant to recent conversations.
"""

import sys
import logging
from datetime import datetime

# Add Doris to path for direct import
sys.path.insert(0, "/Users/macmini/Projects/doris")

logger = logging.getLogger(__name__)


def get_dynamic_topics(hours_since_last_brief: int = 48, **kwargs) -> list[str]:
    """
    Get dynamic topics based on recent Doris memories.

    Just pulls the subjects directly from recent memories - no need
    for Claude to re-extract topics when they're already tagged.

    Args:
        hours_since_last_brief: How far back to look for memories
        **kwargs: Ignored (for backwards compat with old signature)

    Returns:
        List of topic keywords to boost in scoring
    """
    try:
        from memory.store import get_recent_memories

        memories = get_recent_memories(
            hours=hours_since_last_brief,
            categories=['decision', 'learning', 'project', 'thought'],
            limit=50
        )

        if not memories:
            logger.info("No recent memories found, using baseline topics only")
            return []

        # Pull subjects directly - they're already the topics
        subjects = {m['subject'].lower() for m in memories if m.get('subject')}
        topics = list(subjects)

        logger.info(f"Found {len(topics)} topics from {len(memories)} recent memories: {topics[:10]}")
        return topics

    except ImportError as e:
        logger.warning(f"Could not import Doris memory: {e}")
        return []
    except Exception as e:
        logger.error(f"Error getting memories: {e}")
        return []


def get_hours_since_last_brief() -> int:
    """
    Calculate hours since last brief based on M/W/F schedule.

    Returns appropriate lookback:
    - Monday: 72 hours (covers Sat, Sun, Mon)
    - Wednesday: 48 hours (covers Mon, Tue, Wed)
    - Friday: 48 hours (covers Wed, Thu, Fri)
    """
    today = datetime.now().weekday()  # 0=Mon, 4=Fri

    if today == 0:  # Monday
        return 72
    else:  # Wednesday or Friday
        return 48
