"""Podcast source - fetches and transcribes podcast episodes via Groq Whisper."""

import asyncio
import hashlib
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

import feedparser
import httpx

from ..models import ContentItem, ContentType, SourceType
from . import BaseSource


class PodcastSource(BaseSource):
    """Fetch and transcribe podcast episodes using Groq Whisper API."""

    # Max file size for Groq API (25MB)
    MAX_FILE_SIZE = 25 * 1024 * 1024

    def __init__(
        self,
        feeds: list[str],
        groq_api_key: Optional[str] = None,
        max_items: int = 5,
        lookback_hours: int = 24,
    ):
        """
        Args:
            feeds: List of podcast RSS feed URLs
            groq_api_key: Groq API key (falls back to GROQ_API_KEY env var)
            max_items: Max episodes to process per feed
            lookback_hours: Only fetch episodes published within this window
        """
        super().__init__(timeout=120.0)  # Longer timeout for audio downloads
        self.feeds = feeds
        self.groq_api_key = groq_api_key or os.environ.get("GROQ_API_KEY")
        self.max_items = max_items
        self.lookback_hours = lookback_hours

    @property
    def source_name(self) -> str:
        return "podcast"

    def _parse_date(self, entry: dict) -> Optional[datetime]:
        """Parse date from feed entry."""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                dt = datetime(*entry.published_parsed[:6])
                return dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass
        if hasattr(entry, "updated_parsed") and entry.updated_parsed:
            try:
                dt = datetime(*entry.updated_parsed[:6])
                return dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass
        return None

    def _get_audio_url(self, entry: dict) -> Optional[str]:
        """Extract audio URL from enclosure or media content."""
        # Check enclosures first
        if hasattr(entry, "enclosures") and entry.enclosures:
            for enc in entry.enclosures:
                enc_type = enc.get("type", "")
                if "audio" in enc_type or enc.get("href", "").endswith((".mp3", ".m4a")):
                    return enc.get("href")

        # Check media:content
        if hasattr(entry, "media_content"):
            for media in entry.media_content:
                if "audio" in media.get("type", "") or media.get("url", "").endswith(
                    (".mp3", ".m4a")
                ):
                    return media.get("url")

        # Check links
        if hasattr(entry, "links"):
            for link in entry.links:
                if link.get("type", "").startswith("audio/") or link.get("href", "").endswith(
                    (".mp3", ".m4a")
                ):
                    return link.get("href")

        return None

    def _generate_id(self, feed_url: str, entry: dict) -> str:
        """Generate unique ID for podcast episode."""
        guid = entry.get("id", entry.get("link", ""))
        return hashlib.sha256(f"podcast:{feed_url}:{guid}".encode()).hexdigest()[:16]

    async def _download_audio(self, url: str, temp_dir: str) -> Optional[str]:
        """Download audio file to temp directory."""
        try:
            client = await self.get_client()
            async with client.stream("GET", url) as response:
                response.raise_for_status()

                # Determine extension from URL or content-type
                ext = ".mp3"
                if ".m4a" in url:
                    ext = ".m4a"
                elif "audio/mp4" in response.headers.get("content-type", ""):
                    ext = ".m4a"

                file_path = os.path.join(temp_dir, f"episode{ext}")

                with open(file_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        f.write(chunk)

                return file_path
        except Exception as e:
            print(f"Error downloading audio from {url}: {e}")
            return None

    def _preprocess_audio(self, input_path: str, temp_dir: str) -> str:
        """Downsample audio to 16kHz mono if file is too large."""
        file_size = os.path.getsize(input_path)

        if file_size <= self.MAX_FILE_SIZE:
            return input_path

        output_path = os.path.join(temp_dir, "processed.mp3")

        try:
            # Downsample to 16kHz mono MP3 to reduce file size
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    input_path,
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-b:a",
                    "64k",
                    output_path,
                ],
                check=True,
                capture_output=True,
            )
            return output_path
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg preprocessing failed: {e}")
            # If preprocessing fails and file is too large, we can't use it
            if file_size > self.MAX_FILE_SIZE:
                raise ValueError(f"Audio file too large ({file_size} bytes) and preprocessing failed")
            return input_path
        except FileNotFoundError:
            print("FFmpeg not found - cannot preprocess large audio files")
            if file_size > self.MAX_FILE_SIZE:
                raise ValueError(f"Audio file too large ({file_size} bytes) and ffmpeg not available")
            return input_path

    async def _transcribe_audio(self, file_path: str) -> Optional[str]:
        """Transcribe audio using Groq Whisper API."""
        if not self.groq_api_key:
            print("No Groq API key configured - skipping transcription")
            return None

        try:
            from groq import Groq

            client = Groq(api_key=self.groq_api_key)

            with open(file_path, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    file=audio_file,
                    model="whisper-large-v3-turbo",
                    response_format="text",
                )

            return transcription
        except ImportError:
            print("groq package not installed - run: pip install groq")
            return None
        except Exception as e:
            print(f"Transcription error: {e}")
            return None

    async def fetch_feed(self, feed_url: str) -> list[ContentItem]:
        """Fetch and transcribe episodes from a single podcast feed."""
        items = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.lookback_hours)

        try:
            xml = await self.fetch_url(feed_url)
            feed = feedparser.parse(xml)

            podcast_title = feed.feed.get("title", urlparse(feed_url).netloc)

            for entry in feed.entries[: self.max_items]:
                try:
                    # Check if episode is recent enough
                    pub_date = self._parse_date(entry)
                    if pub_date and pub_date < cutoff:
                        continue

                    # Get audio URL
                    audio_url = self._get_audio_url(entry)
                    if not audio_url:
                        continue

                    episode_title = entry.get("title", "Untitled Episode")
                    episode_link = entry.get("link", feed_url)

                    # Download and transcribe
                    transcript = None
                    with tempfile.TemporaryDirectory() as temp_dir:
                        audio_path = await self._download_audio(audio_url, temp_dir)
                        if audio_path:
                            try:
                                processed_path = self._preprocess_audio(audio_path, temp_dir)
                                transcript = await self._transcribe_audio(processed_path)
                            except ValueError as e:
                                print(f"Skipping episode due to size: {e}")
                                continue

                    # Create content item
                    summary = transcript[:2000] + "..." if transcript and len(transcript) > 2000 else transcript

                    item = ContentItem(
                        id=self._generate_id(feed_url, entry),
                        source_type=SourceType.PODCAST,
                        source_name=podcast_title,
                        content_type=ContentType.PODCAST,
                        title=episode_title,
                        url=episode_link,
                        author=entry.get("author"),
                        published_at=pub_date,
                        summary=summary,
                        full_text=transcript,
                        tags=["podcast"],
                    )
                    items.append(item)

                    # Rate limit between episodes
                    await asyncio.sleep(1)

                except Exception as e:
                    print(f"Error processing episode: {e}")
                    continue

        except Exception as e:
            print(f"Error fetching podcast feed {feed_url}: {e}")

        return items

    async def fetch(self) -> list[ContentItem]:
        """Fetch and transcribe from all configured podcast feeds."""
        all_items = []

        for feed_url in self.feeds:
            items = await self.fetch_feed(feed_url)
            all_items.extend(items)

        # Sort by date
        all_items.sort(key=lambda x: x.published_at or datetime.min, reverse=True)

        return all_items
