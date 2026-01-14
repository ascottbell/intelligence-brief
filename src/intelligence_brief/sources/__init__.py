"""Base protocol and utilities for content sources."""

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..models import ContentItem


@runtime_checkable
class ContentSource(Protocol):
    """Protocol for content sources."""
    
    @property
    def source_name(self) -> str:
        """Identifier for this source."""
        ...
    
    async def fetch(self) -> list[ContentItem]:
        """Fetch new content from this source."""
        ...


class BaseSource(ABC):
    """Base class for content sources with common utilities."""
    
    def __init__(self, timeout: float = 30.0):
        self._client: httpx.AsyncClient | None = None
        self._timeout = timeout
    
    async def get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                follow_redirects=True,
                headers={
                    "User-Agent": "IntelligenceBrief/1.0 (https://github.com/adambell)"
                }
            )
        return self._client
    
    async def close(self):
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def fetch_url(self, url: str) -> str:
        """Fetch URL with retry logic."""
        client = await self.get_client()
        response = await client.get(url)
        response.raise_for_status()
        return response.text
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def fetch_json(self, url: str, params: dict | None = None) -> dict:
        """Fetch JSON with retry logic."""
        client = await self.get_client()
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    
    @property
    @abstractmethod
    def source_name(self) -> str:
        """Identifier for this source."""
        ...
    
    @abstractmethod
    async def fetch(self) -> list[ContentItem]:
        """Fetch new content from this source."""
        ...
