from flask import Flask, render_template, request, jsonify
import os
import hmac
import hashlib
import subprocess
from dotenv import dotenv_values
from datetime import datetime, timedelta
import requests
import anthropic
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
import time

import shutil

# Replit Nix paths — only used if they actually exist
_REPLIT_CHROMEDRIVER = "/nix/store/8zj50jw4w0hby47167kqqsaqw4mm5bkd-chromedriver-unwrapped-138.0.7204.100/bin/chromedriver"
_REPLIT_CHROMIUM    = "/nix/store/qa9cnw4v5xkxyip6mb9kxqfq1z4x2dx1-chromium-138.0.7204.100/bin/chromium"


def _find_binary(candidates):
    """Return the first path that exists on disk, or None."""
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return None


def get_chrome_driver():
    chromium_path = _find_binary([
        _REPLIT_CHROMIUM,
        shutil.which("chromium-browser"),
        shutil.which("chromium"),
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/usr/bin/google-chrome",
    ])
    chromedriver_path = _find_binary([
        _REPLIT_CHROMEDRIVER,
        shutil.which("chromedriver"),
        "/usr/bin/chromedriver",
        "/usr/local/bin/chromedriver",
    ])

    if not chromium_path or not chromedriver_path:
        raise RuntimeError("Chrome/Chromium not available in this environment")

    options = webdriver.ChromeOptions()
    options.binary_location = chromium_path
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')
    return webdriver.Chrome(service=Service(chromedriver_path), options=options)
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


def fetch_meetup_events():
    """Scrape Meetup.com for NYC events"""
    # Check cache first
    cached = _get_cached("meetup")
    if cached is not None:
        return cached

    try:
        driver = get_chrome_driver()

        driver.get("https://www.meetup.com/en-US/find/?location=New+York&keywords=tech")
        time.sleep(4)

        events = []
        seen_names = set()

        try:
            # Wait for event results to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.XPATH, "//a[contains(@href, '/events/')]"))
            )

            # Look for event links
            all_links = driver.find_elements(By.XPATH, "//a[contains(@href, '/events/')]")

            for link in all_links[:20]:
                try:
                    href = link.get_attribute("href")
                    text = link.text.strip()

                    if text and len(text) > 3 and text not in seen_names and href:
                        seen_names.add(text)
                        events.append({
                            "name": text[:100],
                            "description": "Tech meetup event on Meetup.com",
                            "start": (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d 18:30"),
                            "venue": "New York",
                            "is_free": True,
                            "url": href if href.startswith("http") else f"https://www.meetup.com{href}",
                        })
                except:
                    continue

        except:
            pass

        driver.quit()
        result = events[:10]
        _set_cache("meetup", result)
        return result

    except Exception as e:
        return []


def fetch_ticketmaster_events():
    # Check cache first
    cached = _get_cached("ticketmaster")
    if cached is not None:
        return cached

    if not TICKETMASTER_KEY or TICKETMASTER_KEY == "your_key_here":
        return []

    try:
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

        if r.status_code != 200:
            return []

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

        _set_cache("ticketmaster", events)
        return events
    except Exception:
        return []


def fetch_eventbrite_events():
    """Scrape Eventbrite for NYC events (Eventbrite API doesn't support public search)"""
    # Check cache first
    cached = _get_cached("eventbrite")
    if cached is not None:
        return cached

    try:
        driver = get_chrome_driver()

        driver.get("https://www.eventbrite.com/d/ny--new-york/")
        time.sleep(3)

        events = []

        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "[data-testid='event-card']"))
            )

            event_cards = driver.find_elements(By.CSS_SELECTOR, "[data-testid='event-card']")

            for card in event_cards[:15]:
                try:
                    # Get event link and name
                    link = card.find_element(By.TAG_NAME, "a")
                    url = link.get_attribute("href")
                    name = link.get_attribute("aria-label") or link.text

                    if name and url:
                        events.append({
                            "name": name[:100],
                            "description": "Event from Eventbrite",
                            "start": (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d 18:00"),
                            "venue": "New York",
                            "is_free": False,
                            "url": url,
                        })
                except:
                    continue

        except:
            pass

        driver.quit()
        result = events[:10]
        _set_cache("eventbrite", result)
        return result

    except Exception:
        return []


def fetch_luma_events():
    """Scrape Luma.com for NYC tech events"""
    # Check cache first
    cached = _get_cached("luma")
    if cached is not None:
        return cached

    try:
        driver = get_chrome_driver()

        # Try NYC events page
        driver.get("https://lu.ma/new-york")
        time.sleep(4)

        events = []
        seen_names = set()

        try:
            # Wait for content
            WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.TAG_NAME, "div"))
            )

            # Look for event links with /event/ path
            all_elements = driver.find_elements(By.XPATH, "//*[contains(@href, '/event/')]")

            for elem in all_elements[:15]:
                try:
                    href = elem.get_attribute("href")
                    # Try to get text from the element or nearby
                    text = elem.text.strip()

                    # Also try to get from aria-label or title
                    if not text:
                        text = elem.get_attribute("aria-label") or elem.get_attribute("title")

                    # Clean up text
                    text = (text or "").strip()

                    if text and len(text) > 3 and text not in seen_names:
                        seen_names.add(text)
                        events.append({
                            "name": text[:100],
                            "description": "Tech community event on Luma",
                            "start": (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d 19:00"),
                            "venue": "New York",
                            "is_free": True,
                            "url": href if href.startswith("http") else f"https://lu.ma{href}",
                        })
                except:
                    continue

        except:
            pass

        driver.quit()
        result = events[:10]
        _set_cache("luma", result)
        return result

    except Exception as e:
        return []


def fetch_techweek_events():
    """Scrape tech-week.com for NYC Tech Week events"""
    cached = _get_cached("techweek")
    if cached is not None:
        return cached

    try:
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')
        options.add_argument('--disable-blink-features=AutomationControlled')

        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )

        driver.get("https://www.tech-week.com/calendar/nyc")
        time.sleep(5)

        events = []

        try:
            # Wait for any content to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.TAG_NAME, "body"))
            )

            # Try multiple parsing strategies
            # Strategy 1: Look for table rows
            event_rows = driver.find_elements(By.TAG_NAME, "tr")

            if len(event_rows) > 0:
                for row in event_rows:
                    try:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        if len(cells) >= 2:
                            # Try to find link with event name
                            all_links = row.find_elements(By.TAG_NAME, "a")
                            if all_links:
                                # Usually event name is in one of the first 2-3 links
                                for link in all_links[:3]:
                                    event_name = link.text.strip()
                                    if event_name and len(event_name) > 3:
                                        event_url = link.get_attribute("href")

                                        # Extract cell text for metadata
                                        cell_texts = [c.text.strip() for c in cells]
                                        location = "New York"
                                        time_str = ""

                                        if cell_texts and cell_texts[0]:
                                            time_str = cell_texts[0]
                                        if len(cell_texts) > 2:
                                            location = cell_texts[-1]

                                        # Filter out virtual
                                        if location.lower() != "virtual (nyc)":
                                            today = datetime.now().date()
                                            start_date = today.strftime("%Y-%m-%d")

                                            events.append({
                                                "name": event_name[:100],
                                                "description": "NYC Tech Week event",
                                                "start": f"{start_date} {time_str}" if time_str else f"{start_date} 18:00",
                                                "venue": location,
                                                "is_free": True,
                                                "url": event_url if event_url and event_url.startswith("http") else f"https://www.tech-week.com{event_url}",
                                            })
                                        break
                    except:
                        continue

            # Strategy 2: Look for divs with event-like content
            if len(events) == 0:
                divs = driver.find_elements(By.CSS_SELECTOR, "div[data-event], div[class*='event']")
                for div in divs[:30]:
                    try:
                        text_content = div.text.strip()
                        links = div.find_elements(By.TAG_NAME, "a")
                        if text_content and links:
                            event_name = links[0].text.strip() if links else text_content[:50]
                            event_url = links[0].get_attribute("href") if links else ""

                            if event_name:
                                today = datetime.now().date()
                                events.append({
                                    "name": event_name[:100],
                                    "description": "NYC Tech Week event",
                                    "start": f"{today.strftime('%Y-%m-%d')} 18:00",
                                    "venue": "New York",
                                    "is_free": True,
                                    "url": event_url if event_url and event_url.startswith("http") else f"https://www.tech-week.com{event_url}",
                                })
                    except:
                        continue

        except:
            pass

        driver.quit()
        result = list(set([e["name"] for e in events]))  # Remove duplicates
        result = [e for e in events if e["name"] in result[:25]]  # Keep first 25 unique
        _set_cache("techweek", result)
        return result

    except Exception as e:
        return []


def fetch_nyc_opendata_events():
    """Fetch NYC events from NYC Open Data (no API key required)"""
    cached = _get_cached("nyc_opendata")
    if cached is not None:
        return cached

    try:
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
            timeout=10
        )

        if r.status_code != 200:
            return []

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
            except:
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

        result = events[:30]
        _set_cache("nyc_opendata", result)
        return result

    except Exception:
        return []


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

Output ONLY the ranked events — no intro text, no commentary, no numbers. Use this exact format for every event:

EVENT NAME
REASON: One sentence explaining why this matches their goals.
Score: X/10 | FREE or PAID

Repeat the block for all {n} events."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text


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


def filter_events_by_price(events, price_filter):
    """Filter events by price preference."""
    if price_filter == "free":
        return [event for event in events if event.get("is_free") is True]
    if price_filter == "paid":
        return [event for event in events if event.get("is_free") is False]
    return events


@app.route("/api/optimize", methods=["POST"])
def optimize():
    data = request.json
    goals = data.get("goals", "")
    date_filter = data.get("dateFilter", "this-week")
    price_filter = data.get("priceFilter", "free")

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
        all_events = filter_events_by_price(all_events, price_filter)

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
