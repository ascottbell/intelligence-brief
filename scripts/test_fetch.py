import asyncio
import sys
sys.path.insert(0, 'src')

from intelligence_brief.sources.hackernews import HackerNewsSource

async def main():
    source = HackerNewsSource(max_items=5)
    items = await source.fetch()

    print(f"Fetched {len(items)} items from HN:\n")
    for item in items:
        print(f"- {item.title}")
        print(f"  Score: {item.engagement.get('score', 0)} | Comments: {item.engagement.get('comments', 0)}")
        print(f"  URL: {item.url}")
        print()

    await source.close()

asyncio.run(main())
