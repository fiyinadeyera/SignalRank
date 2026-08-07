"""Event source fetchers. Each function returns a list of event dicts."""

import os
from datetime import datetime, timedelta

import requests
from dotenv import dotenv_values

import cache
import sieve

_env = dotenv_values(os.path.join(os.path.dirname(__file__), ".env"))
TICKETMASTER_KEY = os.environ.get("TICKETMASTER_API_KEY") or _env.get("TICKETMASTER_API_KEY")
sieve.API_KEY = os.environ.get("SIEVE_API_KEY") or _env.get("SIEVE_API_KEY", "")


@cache.source("sieve")
def fetch_sieve_events():
    return sieve.fetch_events()


@cache.source("ticketmaster")
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
        timeout=5,
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


@cache.source("nyc_opendata")
def fetch_nyc_opendata_events():
    today = datetime.now().strftime("%Y-%m-%dT00:00:00")
    end = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")

    r = requests.get(
        "https://data.cityofnewyork.us/resource/tvpp-9vvx.json",
        params={
            "$limit": 50,
            "$where": f"start_date_time >= '{today}' AND start_date_time <= '{end}'",
            "$order": "start_date_time ASC",
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
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


def _sample_date(days_ahead, time_str):
    return (datetime.now() + timedelta(days=days_ahead)).strftime(f"%Y-%m-%d {time_str}")


def build_sample_events():
    return [
        {"name": "NYC Tech Happy Hour", "description": "Casual after-work drinks for tech founders, PMs, and engineers.", "start": _sample_date(0, "18:30"), "venue": "The Flatiron Room, Manhattan", "is_free": True, "url": "https://example.com"},
        {"name": "NYC Tech Founders Mixer", "description": "Monthly mixer for startup founders and early employees.", "start": _sample_date(1, "19:00"), "venue": "Soho House, Manhattan", "is_free": False, "url": "https://example.com"},
        {"name": "AI & Machine Learning Meetup NYC", "description": "Talks and networking for ML engineers and AI enthusiasts.", "start": _sample_date(2, "18:30"), "venue": "Google NYC Office, Chelsea", "is_free": True, "url": "https://example.com"},
        {"name": "Venture Capital Panel: Investing in 2026", "description": "VCs from a16z, Sequoia, and First Round discuss what they're investing in.", "start": _sample_date(4, "18:00"), "venue": "Columbia Business School", "is_free": True, "url": "https://example.com"},
        {"name": "Startup Pitch Night - Demo Day", "description": "10 early-stage startups pitch to investors and operators.", "start": _sample_date(5, "19:00"), "venue": "WeWork, Flatiron", "is_free": True, "url": "https://example.com"},
        {"name": "Product Management Summit NYC", "description": "Full-day event for PMs with talks on roadmapping and AI tools.", "start": _sample_date(7, "09:00"), "venue": "Javits Center", "is_free": False, "url": "https://example.com"},
        {"name": "Brooklyn Running Club - Weekly 5K", "description": "Casual weekly run followed by brunch.", "start": _sample_date(9, "08:00"), "venue": "Prospect Park, Brooklyn", "is_free": True, "url": "https://example.com"},
        {"name": "NYC Design & Product Workshop", "description": "Half-day workshop on user research, prototyping, and product thinking.", "start": _sample_date(11, "10:00"), "venue": "General Assembly, Manhattan", "is_free": False, "url": "https://example.com"},
    ]


ALL_FETCHERS = [
    fetch_sieve_events,
    fetch_ticketmaster_events,
    fetch_nyc_opendata_events,
]
