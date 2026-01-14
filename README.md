# Intelligence Brief

A daily news aggregator that uses Claude to find, analyze, and summarize the most relevant content for your industry. Get a personalized "Skimm-style" brief delivered to your inbox every morning.

## How It Works

1. **Aggregates** content from multiple sources (Substack, Reddit, Hacker News, arXiv, RSS feeds, podcasts)
2. **Analyzes** each item with Claude to score relevance to your configured topics
3. **Generates** a digestible brief with:
   - Quick Catch-Up (3-4 sentence TL;DR)
   - What's Moving (top stories with context)
   - Worth a Click (quick links)
   - Claude's Take (AI editorial perspective)
4. **Emails** the full brief to you

## Customizing for Your Industry

The brief is configured via environment variables. To adapt it for cybersecurity, healthcare, finance, or any other domain:

### 1. Set Your Topics

```bash
# Primary topics - what you care most about
PRIMARY_TOPICS=cybersecurity,threat-intelligence,zero-day,ransomware,apt,vulnerability

# Secondary topics - adjacent interests
SECONDARY_TOPICS=privacy,compliance,devsecops,cloud-security
```

### 2. Configure Your Sources

```bash
# Substack newsletters (comma-separated handles)
SUBSTACK_FOLLOWS=risky-biz,krebsonsecurity,schneier

# Reddit communities
REDDIT_SUBS=netsec,cybersecurity,ReverseEngineering,blueteamsec

# RSS/Blog feeds
COMPANY_BLOGS=https://blog.cloudflare.com/rss/,https://www.cisa.gov/news.xml,https://krebsonsecurity.com/feed/
```

### 3. Set Up Email

```bash
# Resend.com API (free tier: 100 emails/day)
RESEND_API_KEY=re_xxxxx
EMAIL_RECIPIENT=you@example.com
```

## Setup

### Prerequisites

- Python 3.11+
- [Anthropic API key](https://console.anthropic.com/)
- [Resend API key](https://resend.com/) (for email delivery)

### Installation

```bash
# Clone the repo
git clone https://github.com/yourusername/intelligence-brief.git
cd intelligence-brief

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your API keys and topics
```

### Running Locally

```bash
# Test your configuration
python -m intelligence_brief.main test

# Generate and email a brief
python -m intelligence_brief.main run

# Just aggregate (no email)
python -m intelligence_brief.main aggregate --email
```

## Deployment (Railway)

This project includes a `railway.toml` for easy deployment as a cron job:

1. Push to GitHub
2. Connect repo to [Railway](https://railway.app)
3. Add environment variables in Railway dashboard
4. The cron runs daily at the configured time

```toml
# railway.toml
[deploy]
startCommand = "cd src && python -m intelligence_brief.main run"
cronSchedule = "0 13 * * *"  # 9 AM ET
```

## Sources Supported

| Source | What It Fetches |
|--------|-----------------|
| Substack | Newsletter posts from followed publications |
| Reddit | Top posts from configured subreddits |
| Hacker News | Top stories and Show HN posts |
| arXiv | Recent papers matching your topics |
| RSS/Blogs | Any RSS feed (company blogs, news sites) |
| Podcasts | Episode descriptions from RSS feeds |

## Cost Estimate

- **Anthropic API**: ~$0.35-0.50 per run (Claude Sonnet analyzing ~50 items)
- **Railway**: ~$5/month for cron job
- **Resend**: Free tier covers 100 emails/day

**Monthly total**: ~$15-20 for daily briefs

## License

MIT
