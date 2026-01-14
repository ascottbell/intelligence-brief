"""arXiv source - fetch recent AI/ML papers."""

import hashlib
from datetime import datetime
from typing import Optional
from xml.etree import ElementTree

from ..models import ContentItem, ContentType, SourceType
from . import BaseSource


class ArxivSource(BaseSource):
    """Fetch recent papers from arXiv API."""
    
    BASE_URL = "http://export.arxiv.org/api/query"
    
    # Categories relevant to AI/ML
    CATEGORIES = [
        "cs.AI",   # Artificial Intelligence
        "cs.LG",   # Machine Learning
        "cs.CL",   # Computation and Language (NLP)
        "cs.CV",   # Computer Vision
        "cs.NE",   # Neural and Evolutionary Computing
        "stat.ML", # Machine Learning (Stats)
    ]
    
    NAMESPACES = {
        'atom': 'http://www.w3.org/2005/Atom',
        'arxiv': 'http://arxiv.org/schemas/atom',
    }
    
    def __init__(self, max_items: int = 50, categories: list[str] | None = None):
        super().__init__(timeout=60.0)  # arXiv can be slow
        self.max_items = max_items
        self.categories = categories or self.CATEGORIES
    
    @property
    def source_name(self) -> str:
        return "arxiv"
    
    def _build_query(self) -> str:
        """Build arXiv API query string."""
        # Query for papers in our categories, sorted by submission date
        cat_query = " OR ".join([f"cat:{cat}" for cat in self.categories])
        return f"({cat_query})"
    
    async def fetch(self) -> list[ContentItem]:
        """Fetch recent papers from arXiv."""
        query = self._build_query()
        
        params = {
            "search_query": query,
            "start": 0,
            "max_results": self.max_items,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        
        try:
            # Build URL with params
            param_str = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{self.BASE_URL}?{param_str}"
            
            xml = await self.fetch_url(url)
            return self._parse_response(xml)
            
        except Exception as e:
            print(f"Error fetching arXiv: {e}")
            return []
    
    def _parse_response(self, xml: str) -> list[ContentItem]:
        """Parse arXiv API response."""
        items = []
        
        try:
            root = ElementTree.fromstring(xml)
            
            for entry in root.findall('atom:entry', self.NAMESPACES):
                try:
                    item = self._parse_entry(entry)
                    if item:
                        items.append(item)
                except Exception:
                    continue
                    
        except ElementTree.ParseError as e:
            print(f"XML parse error: {e}")
        
        return items
    
    def _parse_entry(self, entry: ElementTree.Element) -> Optional[ContentItem]:
        """Parse a single entry."""
        ns = self.NAMESPACES
        
        # Extract ID (arxiv ID from the full URL)
        id_elem = entry.find('atom:id', ns)
        if id_elem is None or id_elem.text is None:
            return None
        
        arxiv_id = id_elem.text.split('/')[-1]  # e.g., "2401.12345"
        
        # Title
        title_elem = entry.find('atom:title', ns)
        title = title_elem.text.strip().replace('\n', ' ') if title_elem is not None and title_elem.text else "Untitled"
        
        # Abstract
        summary_elem = entry.find('atom:summary', ns)
        summary = summary_elem.text.strip().replace('\n', ' ') if summary_elem is not None and summary_elem.text else None
        
        # Authors
        authors = []
        for author in entry.findall('atom:author', ns):
            name = author.find('atom:name', ns)
            if name is not None and name.text:
                authors.append(name.text)
        
        # Published date
        published_elem = entry.find('atom:published', ns)
        published_at = None
        if published_elem is not None and published_elem.text:
            try:
                published_at = datetime.fromisoformat(published_elem.text.replace('Z', '+00:00'))
            except ValueError:
                pass
        
        # Categories
        categories = []
        for cat in entry.findall('atom:category', ns):
            term = cat.get('term')
            if term:
                categories.append(term)
        
        # Link to abstract page
        link = f"https://arxiv.org/abs/{arxiv_id}"
        
        return ContentItem(
            id=f"arxiv_{arxiv_id}",
            source_type=SourceType.ARXIV,
            source_name="arxiv",
            content_type=ContentType.PAPER,
            title=title,
            url=link,
            author=", ".join(authors[:3]) + ("..." if len(authors) > 3 else ""),
            published_at=published_at,
            summary=summary[:1000] + "..." if summary and len(summary) > 1000 else summary,
            tags=categories,
        )
