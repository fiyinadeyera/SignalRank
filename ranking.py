"""Event ranking via Claude."""

import json
import os
import re

import anthropic
from dotenv import dotenv_values

_env = dotenv_values(os.path.join(os.path.dirname(__file__), ".env"))
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY") or _env.get("ANTHROPIC_API_KEY")


def rank_events(events, user_goals):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    n = min(6, len(events))
    lines = []
    for i, e in enumerate(events):
        entry = (
            f"{i+1}. {e['name']}\n   When: {e['start']}\n   Venue: {e['venue']}"
            f"\n   Free: {e['is_free']}\n   Info: {e['description']}"
        )
        if e.get("host_info"):
            entry += f"\n   Hosts/Speakers: {e['host_info']}"
        lines.append(entry)
    events_text = "\n\n".join(lines)

    prompt = f"""Rank the top {n} events that best match these goals: {user_goals}

When hosts or speakers are listed, factor their professional background into the ranking.
Events led by credible, relevant professionals should score higher.

Available events ({len(events)} total):
{events_text}

Output ONLY a JSON array, no intro text, no commentary, no markdown code fences. Use this exact structure:

[{{"name": "EVENT NAME", "reason": "One sentence explaining why this matches their goals.", "score": 8}}]

The "score" field must be an integer from 1 to 10. Include all {n} events in the array."""

    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    text = ""
    for block in message.content:
        if block.type == "text":
            text = block.text.strip()
            break

    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    return json.loads(cleaned)
