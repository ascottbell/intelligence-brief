"""Storage layer for briefs - SQLite with 2-week retention."""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .config import get_settings
from .models import DailyBrief, ContentItem


def get_db_path() -> Path:
    """Get the database path from settings."""
    settings = get_settings()
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def init_db():
    """Initialize the briefs database."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS briefs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            narrative TEXT,
            quick_catchup TEXT,
            items_json TEXT,
            sources_checked TEXT,
            total_items_scanned INTEGER
        )
    """)

    # Index for date lookups and search
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_briefs_date ON briefs(date)
    """)

    conn.commit()
    conn.close()


def store_brief(brief: DailyBrief) -> int:
    """Store a brief in the database. Returns the brief ID."""
    init_db()
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Serialize items to JSON (handle HttpUrl serialization)
    items_data = []
    all_items = list(brief.worth_a_click or [])
    if brief.paper_of_the_day:
        all_items.append(brief.paper_of_the_day)
    all_items.extend(brief.builder_corner or [])
    all_items.extend(brief.top_signal or [])
    all_items.extend(brief.homelab_corner or [])

    for item in all_items:
        items_data.append({
            "id": item.id,
            "title": item.title,
            "url": str(item.url),  # Convert HttpUrl to string
            "source_name": item.source_name,
            "source_type": item.source_type.value,
            "insight_summary": item.insight_summary,
            "relevance_score": item.relevance_score,
        })

    try:
        cursor.execute("""
            INSERT OR REPLACE INTO briefs
            (date, created_at, narrative, quick_catchup, items_json, sources_checked, total_items_scanned)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            brief.date,
            datetime.utcnow().isoformat(),
            brief.claudes_take,  # This is the narrative now
            brief.quick_catchup,
            json.dumps(items_data),
            json.dumps(brief.sources_checked),
            brief.total_items_scanned,
        ))
        conn.commit()
        brief_id = cursor.lastrowid
    finally:
        conn.close()

    # Clean up old briefs (2-week retention)
    cleanup_old_briefs()

    return brief_id


def get_brief_by_date(date: str) -> Optional[dict]:
    """Get a brief by date (YYYY-MM-DD format)."""
    init_db()
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM briefs WHERE date = ?", (date,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "id": row["id"],
            "date": row["date"],
            "created_at": row["created_at"],
            "narrative": row["narrative"],
            "quick_catchup": row["quick_catchup"],
            "items": json.loads(row["items_json"]) if row["items_json"] else [],
            "sources_checked": json.loads(row["sources_checked"]) if row["sources_checked"] else [],
            "total_items_scanned": row["total_items_scanned"],
        }
    return None


def get_today_brief() -> Optional[dict]:
    """Get today's brief."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return get_brief_by_date(today)


def get_recent_briefs(days: int = 14) -> list[dict]:
    """Get briefs from the last N days."""
    init_db()
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    cursor.execute(
        "SELECT * FROM briefs WHERE date >= ? ORDER BY date DESC",
        (cutoff,)
    )
    rows = cursor.fetchall()
    conn.close()

    briefs = []
    for row in rows:
        briefs.append({
            "id": row["id"],
            "date": row["date"],
            "created_at": row["created_at"],
            "narrative": row["narrative"],
            "quick_catchup": row["quick_catchup"],
            "items": json.loads(row["items_json"]) if row["items_json"] else [],
            "sources_checked": json.loads(row["sources_checked"]) if row["sources_checked"] else [],
            "total_items_scanned": row["total_items_scanned"],
        })
    return briefs


def search_briefs(query: str, days: int = 14) -> list[dict]:
    """Search briefs by content (narrative and item titles)."""
    init_db()
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    search_pattern = f"%{query}%"

    cursor.execute("""
        SELECT * FROM briefs
        WHERE date >= ?
        AND (narrative LIKE ? OR quick_catchup LIKE ? OR items_json LIKE ?)
        ORDER BY date DESC
    """, (cutoff, search_pattern, search_pattern, search_pattern))

    rows = cursor.fetchall()
    conn.close()

    results = []
    for row in rows:
        results.append({
            "id": row["id"],
            "date": row["date"],
            "narrative": row["narrative"],
            "quick_catchup": row["quick_catchup"],
            "items": json.loads(row["items_json"]) if row["items_json"] else [],
        })
    return results


def cleanup_old_briefs(retention_days: int = 14):
    """Delete briefs older than retention period."""
    db_path = get_db_path()
    if not db_path.exists():
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cutoff = (datetime.utcnow() - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    cursor.execute("DELETE FROM briefs WHERE date < ?", (cutoff,))
    deleted = cursor.rowcount

    conn.commit()
    conn.close()

    if deleted > 0:
        print(f"Cleaned up {deleted} briefs older than {retention_days} days")
