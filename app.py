from flask import Flask, render_template, request, jsonify
import os
from dotenv import dotenv_values
from datetime import datetime, timedelta
import requests
import anthropic

app = Flask(__name__)

_env = dotenv_values(os.path.join(os.path.dirname(__file__), ".env"))
MEETUP_KEY = _env.get("MEETUP_API_KEY")
TICKETMASTER_KEY = _env.get("TICKETMASTER_API_KEY")
ANTHROPIC_KEY = _env.get("ANTHROPIC_API_KEY")

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
    if not MEETUP_KEY or MEETUP_KEY == "your_key_here":
        return []

    try:
        r = requests.get(
            "https://api.meetup.com/find/events",
            params={
                "lat": 40.7128,
                "lon": -74.0060,
                "radius": 10,
                "days": 7,
                "key": MEETUP_KEY,
                "page": 50,
            },
            timeout=5
        )
        if r.status_code != 200:
            return []

        events = []
        for e in r.json():
            events.append({
                "name": e.get("name", ""),
                "description": e.get("description", "")[:300],
                "start": e.get("local_date", "") + " " + e.get("local_time", ""),
                "venue": e.get("venue", {}).get("name", "TBD"),
                "is_free": e.get("fee", {}).get("amount", 0) == 0,
                "url": e.get("link", ""),
            })
        return events
    except Exception:
        return []


def fetch_ticketmaster_events():
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

        return events
    except Exception:
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
Why it matches their goals (1 sentence)
Score: X/10 | FREE or PAID

EVENT NAME
Why it matches their goals (1 sentence)
Score: X/10 | FREE or PAID

[repeat for all 6 events]"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text


@app.route("/")
def index():
    return render_template("index.html")


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


@app.route("/api/optimize", methods=["POST"])
def optimize():
    data = request.json
    goals = data.get("goals", "")
    date_filter = data.get("dateFilter", "this-week")

    if not goals:
        return jsonify({"error": "Please enter your goals"}), 400

    all_events = []
    all_events.extend(fetch_meetup_events())
    all_events.extend(fetch_ticketmaster_events())

    if not all_events:
        all_events = SAMPLE_EVENTS
        is_live = False
    else:
        is_live = True

    # Filter by date
    start_date, end_date = get_date_range(date_filter)
    all_events = filter_events_by_date(all_events, start_date, end_date)

    if not all_events:
        return jsonify({"error": "No events found for the selected date range"}), 400

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
    app.run(debug=True, port=8000)
