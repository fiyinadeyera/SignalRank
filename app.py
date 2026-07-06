from flask import Flask, render_template, request, jsonify
import os
import json
import hmac
import hashlib
import subprocess
from dotenv import dotenv_values
from datetime import datetime, timedelta
import requests
import anthropic
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# Cache system (in-memory with TTL)
_cache = {}
CACHE_TTL = 3600  # 1 hour

def _get_cache_key(source_name):
    return f"events_{source_name}"

def _get_cached(source_name):
    key = _get_cache_key(source_name)
    if key in _cache:
        data, timestamp = _cache[key]
        if time.time() - timestamp < CACHE_TTL:
            return data
    return None

def _set_cache(source_name, data):
    key = _get_cache_key(source_name)
    _cache[key] = (data, time.time())

# Per-source health, exposed at /api/status for debugging
_source_status = {}

def _record_status(name, count=None, error=None):
    _source_status[name] = {
        "ok": error is None,
        "count": count,
        "error": error,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

def _source(name):
    """Wrap a fetcher with caching and status recording; errors return []."""
    def deco(fn):
        def wrapper():
            cached = _get_cached(name)
            if cached is not None:
                return cached
            try:
                result = fn()
                if result:
                    _set_cache(name, result)
                _record_status(name, count=len(result))
                return result
            except Exception as e:
                _record_status(name, error=f"{type(e).__name__}: {e}")
                return []
        return wrapper
    return deco


_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def _http_get(url, params=None, timeout=10):
    r = requests.get(url, params=params, headers=_HTTP_HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.text


def _extract_json_blocks(html):
    """Parse JSON embedded in ld+json and __NEXT_DATA__ script tags."""
    patterns = [
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    ]
    blocks = []
    for pat in patterns:
        for m in re.finditer(pat, html, re.DOTALL):
            try:
                blocks.append(json.loads(m.group(1)))
            except ValueError:
                continue
    return blocks


def _walk_event_dicts(node, found):
    """Recursively collect dicts that carry a name plus a start time."""
    if isinstance(node, dict):
        name = node.get("name") or node.get("title")
        start = node.get("startDate") or node.get("start_at") or node.get("dateTime")
        if isinstance(name, str) and isinstance(start, str) and len(name.strip()) > 3:
            found.append((node, name.strip(), start))
        for v in node.values():
            _walk_event_dicts(v, found)
    elif isinstance(node, list):
        for v in node:
            _walk_event_dicts(v, found)


def _normalize_start(raw):
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _looks_free(node):
    offers = node.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    if isinstance(offers, list):
        for o in offers:
            if isinstance(o, dict):
                price = o.get("price") or o.get("lowPrice")
                if price in (0, "0", "0.00", "0.0"):
                    return True
                if price:
                    return False
    return node.get("price") in (None, 0, "0")


def _fetch_events_from_page(url, description, base_url="", default_venue="New York", limit=10):
    """Fetch a page and pull events out of its embedded structured data."""
    html = _http_get(url)
    found = []
    for block in _extract_json_blocks(html):
        _walk_event_dicts(block, found)

    events, seen = [], set()
    for node, name, start_raw in found:
        if name in seen:
            continue
        start = _normalize_start(start_raw)
        if not start:
            continue
        seen.add(name)

        ev_url = node.get("url") or node.get("eventUrl") or ""
        if ev_url and not ev_url.startswith("http"):
            ev_url = base_url.rstrip("/") + "/" + ev_url.lstrip("/")

        venue = default_venue
        loc = node.get("location")
        if isinstance(loc, dict) and loc.get("name"):
            venue = loc["name"]
        elif isinstance(loc, str) and loc.strip():
            venue = loc.strip()

        events.append({
            "name": name[:100],
            "description": (node.get("description") or description)[:300],
            "start": start,
            "venue": venue[:100],
            "is_free": _looks_free(node),
            "url": ev_url,
        })
        if len(events) >= limit:
            break
    return events

_env = dotenv_values(os.path.join(os.path.dirname(__file__), ".env"))
MEETUP_KEY = os.environ.get("MEETUP_API_KEY") or _env.get("MEETUP_API_KEY")
TICKETMASTER_KEY = os.environ.get("TICKETMASTER_API_KEY") or _env.get("TICKETMASTER_API_KEY")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY") or _env.get("ANTHROPIC_API_KEY")
EVENTBRITE_KEY = os.environ.get("EVENTBRITE_API_KEY") or _env.get("EVENTBRITE_API_KEY")

def _sample_date(days_ahead, time_str):
    """Return a date string offset from today."""
    return (datetime.now() + timedelta(days=days_ahead)).strftime(f"%Y-%m-%d {time_str}")


def _build_sample_events():
    # Events spread across days 0-12 to cover all three date filters:
    #   today     = day 0
    #   this-week = days 0-7
    #   next-week = days 8-14
    return [
        # today + this-week
        {
            "name": "NYC Tech Happy Hour",
            "description": "Casual after-work drinks for tech founders, PMs, and engineers.",
            "start": _sample_date(0, "18:30"),
            "venue": "The Flatiron Room, Manhattan",
            "is_free": True,
            "url": "https://example.com",
        },
        {
            "name": "NYC Tech Founders Mixer",
            "description": "Monthly mixer for startup founders and early employees.",
            "start": _sample_date(1, "19:00"),
            "venue": "Soho House, Manhattan",
            "is_free": False,
            "url": "https://example.com",
        },
        {
            "name": "AI & Machine Learning Meetup NYC",
            "description": "Talks and networking for ML engineers and AI enthusiasts.",
            "start": _sample_date(2, "18:30"),
            "venue": "Google NYC Office, Chelsea",
            "is_free": True,
            "url": "https://example.com",
        },
        {
            "name": "Venture Capital Panel: Investing in 2026",
            "description": "VCs from a16z, Sequoia, and First Round discuss what they're investing in.",
            "start": _sample_date(4, "18:00"),
            "venue": "Columbia Business School",
            "is_free": True,
            "url": "https://example.com",
        },
        {
            "name": "Startup Pitch Night — Demo Day",
            "description": "10 early-stage startups pitch to investors and operators.",
            "start": _sample_date(5, "19:00"),
            "venue": "WeWork, Flatiron",
            "is_free": True,
            "url": "https://example.com",
        },
        {
            "name": "Product Management Summit NYC",
            "description": "Full-day event for PMs with talks on roadmapping and AI tools.",
            "start": _sample_date(7, "09:00"),
            "venue": "Javits Center",
            "is_free": False,
            "url": "https://example.com",
        },
        # next-week
        {
            "name": "Brooklyn Running Club — Weekly 5K",
            "description": "Casual weekly run followed by brunch.",
            "start": _sample_date(9, "08:00"),
            "venue": "Prospect Park, Brooklyn",
            "is_free": True,
            "url": "https://example.com",
        },
        {
            "name": "NYC Design & Product Workshop",
            "description": "Half-day workshop on user research, prototyping, and product thinking.",
            "start": _sample_date(11, "10:00"),
            "venue": "General Assembly, Manhattan",
            "is_free": False,
            "url": "https://example.com",
        },
    ]


@_source("meetup")
def fetch_meetup_events():
    """Meetup NYC tech events via structured data embedded in the search page."""
    return _fetch_events_from_page(
        "https://www.meetup.com/find/?location=us--ny--new%20york&source=EVENTS&keywords=tech",
        description="Tech meetup event on Meetup.com",
        base_url="https://www.meetup.com",
    )


@_source("ticketmaster")
def fetch_ticketmaster_events():
    if not TICKETMASTER_KEY or TICKETMASTER_KEY == "your_key_here":
        raise RuntimeError("TICKETMASTER_API_KEY not set")

    start = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    r = requests.get(
        "https://app.ticketmaster.com/discovery/v2/events.json",
        params={
            "apikey": TICKETMASTER_KEY,
            "city": "New York",
            "countryCode": "US",
            "startDateTime": start,
            "endDateTime": end,
            "size": 50,
        },
        timeout=5
    )
    r.raise_for_status()

    events = []
    for e in r.json().get("_embedded", {}).get("events", []):
        venue = e.get("_embedded", {}).get("venues", [{}])[0]
        events.append({
            "name": e.get("name", ""),
            "description": e.get("info", "")[:300],
            "start": e.get("dates", {}).get("start", {}).get("localDate", ""),
            "venue": venue.get("name", "TBD"),
            "is_free": False,
            "url": e.get("url", ""),
        })
    return events


@_source("eventbrite")
def fetch_eventbrite_events():
    """Eventbrite NYC events via JSON-LD embedded in the destination page."""
    return _fetch_events_from_page(
        "https://www.eventbrite.com/d/ny--new-york/all-events/",
        description="Event from Eventbrite",
        base_url="https://www.eventbrite.com",
    )


@_source("luma")
def fetch_luma_events():
    """Luma NYC events via structured data embedded in the city page."""
    return _fetch_events_from_page(
        "https://lu.ma/nyc",
        description="Tech community event on Luma",
        base_url="https://lu.ma",
    )


@_source("techweek")
def fetch_techweek_events():
    """NYC Tech Week events via structured data on the calendar page (seasonal)."""
    return _fetch_events_from_page(
        "https://www.tech-week.com/calendar/nyc",
        description="NYC Tech Week event",
        base_url="https://www.tech-week.com",
        limit=25,
    )


@_source("nyc_opendata")
def fetch_nyc_opendata_events():
    """Fetch NYC events from NYC Open Data (no API key required)"""
    # NYC Parks events — free public API
    today = datetime.now().strftime("%Y-%m-%dT00:00:00")
    end = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")

    r = requests.get(
        "https://data.cityofnewyork.us/resource/tvpp-9vvx.json",
        params={
            "$limit": 50,
            "$where": f"start_date_time >= '{today}' AND start_date_time <= '{end}'",
            "$order": "start_date_time ASC",
        },
        headers=_HTTP_HEADERS,
        timeout=10
    )
    r.raise_for_status()

    events = []
    seen = set()

    for e in r.json():
        name = e.get("event_name", "").strip()
        if not name or name in seen:
            continue
        seen.add(name)

        start_raw = e.get("start_date_time", "")
        try:
            dt = datetime.fromisoformat(start_raw)
            start = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            start = datetime.now().strftime("%Y-%m-%d 18:00")

        borough = e.get("event_borough", "New York")
        location = e.get("event_location", borough)
        event_type = e.get("event_type", "")

        events.append({
            "name": name[:100],
            "description": f"{event_type} event in {borough}" if event_type else f"NYC event in {borough}",
            "start": start,
            "venue": location[:100] if location else borough,
            "is_free": True,
            "url": "https://www.nycgovparks.org/events",
        })

    return events[:30]


def rank_events(events, user_goals):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    n = min(6, len(events))
    events_text = "\n\n".join([
        f"{i+1}. {e['name']}\n   When: {e['start']}\n   Venue: {e['venue']}\n   Free: {e['is_free']}\n   Info: {e['description']}"
        for i, e in enumerate(events)
    ])

    prompt = f"""Rank the top {n} events that best match these goals: {user_goals}

Available events ({len(events)} total):
{events_text}

Output ONLY a JSON array, no intro text, no commentary, no markdown code fences. Use this exact structure:

[{{"name": "EVENT NAME", "reason": "One sentence explaining why this matches their goals.", "score": 8}}]

The "score" field must be an integer from 1 to 10. Include all {n} events in the array."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    text = message.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()

    return json.loads(text)


WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def sync_file_from_github(repo_full_name, file_path):
    import base64
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    r = requests.get(
        f"https://api.github.com/repos/{repo_full_name}/contents/{file_path}",
        headers=headers,
        timeout=10
    )
    if r.status_code != 200:
        return False, r.status_code
    content = base64.b64decode(r.json()["content"])
    dest = os.path.join(BASE_DIR, file_path)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(content)
    return True, None


@app.route("/github-webhook", methods=["POST"])
def github_webhook():
    sig = request.headers.get("X-Hub-Signature-256", "")
    body = request.get_data()
    if WEBHOOK_SECRET:
        expected = "sha256=" + hmac.new(
            WEBHOOK_SECRET.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return jsonify({"error": "Invalid signature"}), 403

    event = request.headers.get("X-GitHub-Event", "")
    if event != "push":
        return jsonify({"status": "ignored"}), 200

    payload = request.get_json(force=True) or {}
    repo = payload.get("repository", {}).get("full_name", "")
    commits = payload.get("commits", [])

    changed = set()
    for commit in commits:
        for f in commit.get("added", []) + commit.get("modified", []):
            changed.add(f)

    synced, failed = [], []
    for file_path in changed:
        ok, err = sync_file_from_github(repo, file_path)
        (synced if ok else failed).append(file_path)

    return jsonify({"status": "synced", "synced": synced, "failed": failed}), 200


@app.route("/")
def index():
    return render_template("index.html", page="home")

@app.route("/signalrank")
def signalrank():
    return render_template("signalrank.html", page="signalrank")

@app.route("/agent")
def agent():
    return render_template("agent.html", page="agent")

@app.route("/risk")
def risk():
    return render_template("risk.html", page="risk")

@app.route("/events")
def events():
    return render_template("events.html", page="events")


def get_date_range(date_filter):
    """Get date range based on filter selection.

    Uses a rolling window so events always fall inside the chosen bucket
    regardless of which day of the week it is:
        today     = today only
        this-week = today through the next 7 days
        next-week = 8 through 14 days from today
    """
    today = datetime.now().date()

    if date_filter == "today":
        return today, today
    elif date_filter == "next-week":
        start = today + timedelta(days=8)
        end   = today + timedelta(days=14)
        return start, end
    else:  # "this-week" (default)
        return today, today + timedelta(days=7)


def filter_events_by_date(events, start_date, end_date):
    """Filter events to only include those within the date range."""
    filtered = []
    for event in events:
        try:
            event_date_str = event.get("start", "").split()[0]
            event_date = datetime.strptime(event_date_str, "%Y-%m-%d").date()
            if start_date <= event_date <= end_date:
                filtered.append(event)
        except:
            pass
    return filtered


@app.route("/api/status")
def api_status():
    """Health of each event source from its most recent fetch."""
    return jsonify(_source_status)


@app.route("/api/optimize", methods=["POST"])
def optimize():
    data = request.json
    goals = data.get("goals", "")
    date_filter = data.get("dateFilter", "this-week")

    if not goals:
        return jsonify({"error": "Please enter your goals"}), 400

    all_events = []
    # Fetch from all sources in parallel
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(fetch_ticketmaster_events): "ticketmaster",
            executor.submit(fetch_meetup_events): "meetup",
            executor.submit(fetch_eventbrite_events): "eventbrite",
            executor.submit(fetch_luma_events): "luma",
            executor.submit(fetch_techweek_events): "techweek",
            executor.submit(fetch_nyc_opendata_events): "nyc_opendata",
        }
        for future in as_completed(futures):
            try:
                events = future.result(timeout=30)
                all_events.extend(events)
            except Exception:
                pass

    if not all_events:
        # No live events — skip filters and use samples so the app always works
        all_events = _build_sample_events()
        is_live = False
    else:
        is_live = True
        # Only filter live events — samples are always shown as-is
        start_date, end_date = get_date_range(date_filter)
        all_events = filter_events_by_date(all_events, start_date, end_date)

        if not all_events:
            # Live events existed but all filtered out — fall back to samples
            all_events = _build_sample_events()
            is_live = False

    try:
        ranked = rank_events(all_events, goals)
        return jsonify({
            "success": True,
            "ranking": ranked,
            "events": all_events,
            "is_live": is_live,
            "event_count": len(all_events)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _warm_cache():
    """Fetch all sources in parallel and populate the cache."""
    sources = [
        fetch_ticketmaster_events,
        fetch_meetup_events,
        fetch_eventbrite_events,
        fetch_luma_events,
        fetch_techweek_events,
        fetch_nyc_opendata_events,
    ]
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(fn) for fn in sources]
        for f in as_completed(futures):
            try:
                f.result(timeout=40)
            except Exception:
                pass


def _cache_refresh_loop():
    """Warm cache on startup, then refresh every 55 minutes."""
    _warm_cache()
    while True:
        time.sleep(55 * 60)
        _warm_cache()


# Start background cache warming thread
_bg_thread = threading.Thread(target=_cache_refresh_loop, daemon=True)
_bg_thread.start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
