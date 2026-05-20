import os
import requests
import anthropic
from dotenv import dotenv_values
from datetime import datetime, timedelta

_env = dotenv_values(os.path.join(os.path.dirname(__file__), ".env"))

TICKETMASTER_KEY = _env.get("TICKETMASTER_API_KEY")
MEETUP_KEY = _env.get("MEETUP_API_KEY")
ANTHROPIC_KEY = _env.get("ANTHROPIC_API_KEY")


SAMPLE_EVENTS = [
    {
        "name": "NYC Tech Founders Mixer",
        "description": "Monthly mixer for startup founders and early employees. Great for meeting people building companies in NYC.",
        "start": "2026-05-21 19:00",
        "venue": "Soho House, Manhattan",
        "is_free": False,
        "url": "https://example.com",
    },
    {
        "name": "AI & Machine Learning Meetup NYC",
        "description": "Talks and networking for ML engineers, data scientists, and AI enthusiasts. Usually 100-200 attendees.",
        "start": "2026-05-22 18:30",
        "venue": "Google NYC Office, Chelsea",
        "is_free": True,
        "url": "https://example.com",
    },
    {
        "name": "Speed Friending NYC",
        "description": "Make new friends in NYC through structured speed-friending rounds. Great for people new to the city.",
        "start": "2026-05-23 19:00",
        "venue": "The Williamsburg Hotel, Brooklyn",
        "is_free": False,
        "url": "https://example.com",
    },
    {
        "name": "Venture Capital Panel: Investing in 2026",
        "description": "VCs from a16z, Sequoia, and First Round discuss what they're investing in and what founders should know.",
        "start": "2026-05-20 18:00",
        "venue": "Columbia Business School",
        "is_free": True,
        "url": "https://example.com",
    },
    {
        "name": "NYC Dating & Social Skills Workshop",
        "description": "Practical workshop on conversation skills, confidence, and meeting people in NYC.",
        "start": "2026-05-24 14:00",
        "venue": "Midtown Manhattan",
        "is_free": False,
        "url": "https://example.com",
    },
    {
        "name": "Brooklyn Running Club — Weekly 5K",
        "description": "Casual weekly run followed by brunch. Mixed ages and paces. Great community.",
        "start": "2026-05-25 08:00",
        "venue": "Prospect Park, Brooklyn",
        "is_free": True,
        "url": "https://example.com",
    },
    {
        "name": "Product Management Summit NYC",
        "description": "Full-day event for PMs with talks on roadmapping, stakeholder management, and AI tools.",
        "start": "2026-05-21 09:00",
        "venue": "Javits Center",
        "is_free": False,
        "url": "https://example.com",
    },
    {
        "name": "Startup Pitch Night — Demo Day",
        "description": "10 early-stage startups pitch to a room of investors and operators. Networking after.",
        "start": "2026-05-22 19:00",
        "venue": "WeWork, Flatiron",
        "is_free": True,
        "url": "https://example.com",
    },
]


def fetch_meetup_events():
    """Pull upcoming events in NYC from Meetup."""
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
    except Exception as e:
        print(f"Meetup error: {e}")
        return []


def fetch_ticketmaster_events():
    """Pull upcoming events in NYC from Ticketmaster."""
    if not TICKETMASTER_KEY or TICKETMASTER_KEY == "your_key_here":
        return []

    try:
        start = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        end = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

        params = {
            "apikey": TICKETMASTER_KEY,
            "city": "New York",
            "countryCode": "US",
            "startDateTime": start,
            "endDateTime": end,
            "size": 50,
        }

        r = requests.get("https://app.ticketmaster.com/discovery/v2/events.json", params=params, timeout=5)

        if r.status_code != 200:
            return []

        raw = r.json().get("_embedded", {}).get("events", [])

        events = []
        for e in raw:
            venue = e.get("_embedded", {}).get("venues", [{}])[0]
            events.append({
                "name": e.get("name", ""),
                "description": e.get("info", "") or e.get("pleaseNote", "") or "",
                "start": e.get("dates", {}).get("start", {}).get("localDate", ""),
                "venue": venue.get("name", "TBD"),
                "is_free": False,
                "url": e.get("url", ""),
            })

        return events
    except Exception as e:
        print(f"Ticketmaster error: {e}")
        return []


def rank_events(events, user_goals):
    """Use Claude to rank events based on user goals."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    events_text = "\n\n".join([
        f"{i+1}. {e['name']}\n   When: {e['start']}\n   Venue: {e['venue']}\n   Free: {e['is_free']}\n   Info: {e['description']}"
        for i, e in enumerate(events)
    ])

    prompt = f"""You are helping someone in New York City decide which events to attend this week.

Their goals are:
{user_goals}

Here are the available events:

{events_text}

Pick the TOP 6 events that best match their goals. For each one provide:
- Event name and number
- Date and venue
- Why it's a strong match for their goals (1-2 sentences)
- Score: X/10

End with a one-paragraph "Your Week" summary of how to think about the schedule."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text


def get_user_goals():
    print("\n=== Event Optimizer for NYC ===\n")
    print("What are you optimizing for this week? Be specific.")
    print("Examples: career networking in tech, meeting new friends, learning about startups, dating\n")
    goals = input("Your goals: ")
    return goals


def main():
    goals = get_user_goals()

    print("\nFetching events from Meetup and Ticketmaster...")

    all_events = []
    all_events.extend(fetch_meetup_events())
    all_events.extend(fetch_ticketmaster_events())

    if not all_events:
        print("\n[No live events found — using sample events]\n")
        print("[TIP: Add MEETUP_API_KEY and TICKETMASTER_API_KEY to .env for live events]\n")
        all_events = SAMPLE_EVENTS
    else:
        print(f"Found {len(all_events)} events this week.")

    print("Ranking them for you with AI...\n")
    ranked = rank_events(all_events, goals)

    print("\n=== Your Optimized Week ===\n")
    print(ranked)


if __name__ == "__main__":
    main()
