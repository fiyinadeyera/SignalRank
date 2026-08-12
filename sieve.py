"""Sieve API client for event extraction."""

import os
import time

import requests

BASE_URL = "https://scrape.usesieve.com"
API_KEY = os.environ.get("SIEVE_API_KEY") or ""

EVENT_SOURCES = [
    "https://www.meetup.com/find/?location=us--ny--new%20york&source=EVENTS&keywords=tech",
    "https://www.eventbrite.com/d/ny--new-york/all-events/",
    "https://lu.ma/nyc",
]

EVENT_INSTRUCTION = (
    "Extract upcoming events from these pages. For each event, extract: "
    "event name, a one-line description, start date and time (ISO 8601), "
    "venue name, whether it is free, the event URL, and the names of "
    "hosts, speakers, or panelists (as a list of strings). "
    "Only include events happening in the next 14 days."
)

EVENT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "start": {"type": "string"},
            "venue": {"type": "string"},
            "is_free": {"type": "boolean"},
            "url": {"type": "string"},
            "hosts": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name", "start"],
    },
}

POLL_INTERVAL = 5
MAX_POLL_TIME = 120


def _headers():
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }


def start_extraction(urls=None, instruction=None):
    resp = requests.post(
        f"{BASE_URL}/api/scrapes",
        headers=_headers(),
        json={
            "instruction": instruction or EVENT_INSTRUCTION,
            "target_urls": urls or EVENT_SOURCES,
            "output_schema": EVENT_SCHEMA,
            "compliance_mode": "regular",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["session_id"]


def poll_result(session_id):
    elapsed = 0
    while elapsed < MAX_POLL_TIME:
        resp = requests.get(
            f"{BASE_URL}/api/scrapes/{session_id}",
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data["status"] == "done":
            return data
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
    return None


def fetch_events():
    if not API_KEY:
        raise RuntimeError("SIEVE_API_KEY not set")

    session_id = start_extraction()
    result = poll_result(session_id)

    if not result:
        return []

    raw_events = result.get("result", [])
    if not isinstance(raw_events, list):
        return []

    events = []
    for ev in raw_events:
        hosts = ev.get("hosts") or []
        if isinstance(hosts, str):
            hosts = [hosts]
        events.append({
            "name": (ev.get("name") or "")[:100],
            "description": (ev.get("description") or "")[:300],
            "start": _normalize_start(ev.get("start", "")),
            "venue": (ev.get("venue") or "New York")[:100],
            "is_free": bool(ev.get("is_free", False)),
            "url": ev.get("url", ""),
            "hosts": [h.strip() for h in hosts if h and len(h.strip()) > 2],
        })
    return events


def _normalize_start(raw):
    if not raw:
        return ""
    from datetime import datetime
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
    try:
        dt = datetime.strptime(raw[:16], "%Y-%m-%dT%H:%M")
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return raw[:16]
