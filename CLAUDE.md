# SignalRank

## Product

A live event discovery and ranking engine for NYC. Users enter their goals in free text, select a date range, and get a ranked list of real events scored 1-10 with reasoning. Events are enriched with host/speaker professional backgrounds before ranking.

### Requirements

- Pull events from multiple sources: Meetup, Eventbrite, Luma (via Sieve), Ticketmaster, NYC Open Data
- Extract host/speaker/panelist names from events
- Enrich events by searching for host backgrounds online (Google search via Sieve). Source can be LinkedIn, personal websites, or anything relevant.
- Rank events against user goals using Claude, factoring in host credibility
- Return JSON with event name, reason, and score (1-10)
- Date filters: today, this-week (0-7 days), next-week (8-14 days)
- Fall back to sample events when no live events are available (labeled as sample, not fake live)

### What this is not

- Not a calendar or booking tool. Discovery and ranking only.
- Not a scraper. Uses Sieve API for web extraction, not custom Selenium scrapers.

## Architecture

Single-responsibility modules:

| File | Responsibility |
|---|---|
| `app.py` | Flask routes and orchestration only. No business logic. |
| `sieve.py` | Sieve API client. Starts extraction jobs, polls for results, normalizes events. Extracts host names. |
| `sources.py` | All event fetchers (Sieve, Ticketmaster, NYC Open Data, sample events). Exports `ALL_FETCHERS`. |
| `cache.py` | In-memory cache with 1-hour TTL. `@source()` decorator wraps fetchers. |
| `enrichment.py` | Collects host names across events, searches Google via Sieve for profiles, attaches host_info to events. |
| `ranking.py` | Claude prompt building and event ranking. Returns JSON array of scored events. |
| `filters.py` | Date range calculation and event filtering. |
| `webhook.py` | GitHub webhook handler for auto-deploying file changes from pushes. |

### Key technical decisions

- Claude model: Haiku 4.5. Event ranking does not need a stronger model.
- Sieve API for all web extraction (events and host profiles). Replaces previous Selenium scrapers.
- Enrichment caps at 15 host lookups per request to control Sieve costs.
- Background thread warms cache every 55 minutes.
- Events fetched in parallel with ThreadPoolExecutor (max_workers=3).
- Sieve gets 120s timeout, other sources get 30s.
- Must iterate `response.content` blocks to skip ThinkingBlock and find type=="text".
- Code fences stripped from Claude response before JSON parsing.

## Design system

- Extends fiyin-os base template (Tailwind + Satoshi font, dark slate theme)
- Part of fiyin.org, not a standalone site

## Deployment

- Render (fiyin.org), auto-deploys on push to main
- `render.yaml` defines the service (gunicorn)
- Environment variables set in Render dashboard

## Coding conventions

- No God modules. Each file has one responsibility.
- No unused code.
- Always pick the cheapest Claude model that handles the task.
- Sieve API key set via `SIEVE_API_KEY` env var. Sieve is a friend's startup.

## Secrets (never commit)

- `.env` contains API keys (Anthropic, Sieve, Ticketmaster, GitHub webhook secret)
