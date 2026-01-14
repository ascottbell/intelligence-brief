import asyncio
import sys
sys.path.insert(0, 'src')

from intelligence_brief.sources.hackernews import HackerNewsSource
from intelligence_brief.sources.substack import SubstackSource
from intelligence_brief.sources.arxiv import ArxivSource
from intelligence_brief.sources.github import GitHubTrendingSource
from intelligence_brief.sources.reddit import RedditSource

async def test_source(name, source):
    print(f"\n{'='*50}")
    print(f"Testing: {name}")
    print('='*50)
    try:
        items = await source.fetch()
        print(f"✓ Fetched {len(items)} items")
        if items:
            print(f"  Sample: {items[0].title[:60]}...")
    except Exception as e:
        print(f"✗ Error: {e}")
    finally:
        await source.close()

async def main():
    sources = [
        ("Hacker News", HackerNewsSource(max_items=3)),
        ("Substack (ahead-of-ai)", SubstackSource(handles=["ahead-of-ai"], max_items=3)),
        ("arXiv", ArxivSource(max_items=3)),
        ("GitHub Trending", GitHubTrendingSource(since="daily")),
        ("Reddit (LocalLLaMA)", RedditSource(subreddits=["LocalLLaMA"], max_items=3)),
    ]

    for name, source in sources:
        await test_source(name, source)

asyncio.run(main())
