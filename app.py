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

CHROMEDRIVER_PATH = "/nix/store/8zj50jw4w0hby47167kqqsaqw4mm5bkd-chromedriver-unwrapped-138.0.7204.100/bin/chromedriver"
CHROMIUM_PATH = "/nix/store/qa9cnw4v5xkxyip6mb9kxqfq1z4x2dx1-chromium-138.0.7204.100/bin/chromium"


def get_chrome_driver():
    options = webdriver.ChromeOptions()
    options.binary_location = CHROMIUM_PATH
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36')
    return webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=options)
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

SAMPLE_EVENTS = [
    {
        "name": "NYC Tech Founders Mixer",
        "description": "Monthly mixer for startup founders and early employees.",
        "start": "2026-05-21 19:00",
        "venue": "Soho House, Manhattan",
        "is_free": False,
        "url": "https://example.com",
    },
    {
        "name": "AI & Machine Learning Meetup NYC",
        "description": "Talks and networking for ML engineers and AI enthusiasts.",
        "start": "2026-05-22 18:30",
        "venue": "Google NYC Office, Chelsea",
        "is_free": True,
        "url": "https://example.com",
    },
    {
        "name": "Venture Capital Panel: Investing in 2026",
        "description": "VCs from a16z, Sequoia, and First Round discuss what they're investing in.",
        "start": "2026-05-20 18:00",
        "venue": "Columbia Business School",
        "is_free": True,
        "url": "https://example.com",
    },
    {
        "name": "Startup Pitch Night — Demo Day",
        "description": "10 early-stage startups pitch to investors and operators.",
        "start": "2026-05-22 19:00",
        "venue": "WeWork, Flatiron",
        "is_free": True,
        "url": "https://example.com",
    },
    {
        "name": "Product Management Summit NYC",
        "description": "Full-day event for PMs with talks on roadmapping and AI tools.",
        "start": "2026-05-21 09:00",
        "venue": "Javits Center",
        "is_free": False,
        "url": "https://example.com",
    },
    {
        "name": "Brooklyn Running Club — Weekly 5K",
        "description": "Casual weekly run followed by brunch.",
        "start": "2026-05-25 08:00",
        "venue": "Prospect Park, Brooklyn",
        "is_free": True,
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


def rank_events(events, user_goals):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    events_text = "\n\n".join([
        f"{i+1}. {e['name']}\n   When: {e['start']}\n   Venue: {e['venue']}\n   Free: {e['is_free']}\n   Info: {e['description']}"
        for i, e in enumerate(events)
    ])

    prompt = f"""Pick the TOP 6 events that best match these goals: {user_goals}

Available events:
{events_text}

Output ONLY the 6 events in this exact format. NO intro text, NO numbers, NO extra text:

EVENT NAME
REASON: Why it matches their goals (1 sentence)
Score: X/10 | FREE or PAID

EVENT NAME
REASON: Why it matches their goals (1 sentence)
Score: X/10 | FREE or PAID

[repeat for all 6 events]"""

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
    """Get date range based on filter selection."""
    today = datetime.now().date()

    if date_filter == "today":
        return today, today
    elif date_filter == "next-week":
        start = today + timedelta(days=7)
        end = start + timedelta(days=6)
        return start, end
    else:  # "this-week"
        # Get start of this week (Monday)
        start = today - timedelta(days=today.weekday())
        # Get end of this week (Sunday)
        end = start + timedelta(days=6)
        return start, end


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
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(fetch_ticketmaster_events): "ticketmaster",
            executor.submit(fetch_meetup_events): "meetup",
            executor.submit(fetch_eventbrite_events): "eventbrite",
            executor.submit(fetch_luma_events): "luma",
        }
        for future in as_completed(futures):
            try:
                events = future.result(timeout=30)
                all_events.extend(events)
            except Exception:
                pass

    if not all_events:
        all_events = SAMPLE_EVENTS
        is_live = False
    else:
        is_live = True

    # Filter by date
    start_date, end_date = get_date_range(date_filter)
    all_events = filter_events_by_date(all_events, start_date, end_date)
    all_events = filter_events_by_price(all_events, price_filter)

    if not all_events:
        return jsonify({"error": "No events found for the selected filters"}), 400

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
    app.run(host="0.0.0.0", port=5000, debug=True)
