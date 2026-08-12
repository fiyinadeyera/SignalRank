"""Enrich events with host/speaker profiles via Sieve."""

import urllib.parse

import sieve


PROFILE_INSTRUCTION = (
    "For each search results page, extract the person's name, current job title, "
    "current company, and a one-line professional summary from whatever profile "
    "or bio you find (LinkedIn, personal website, company page, etc.). "
    "If no relevant result is found, return just their name with empty fields."
)


def _build_search_urls(names):
    urls = []
    for name in names:
        q = urllib.parse.quote_plus(f"{name} linkedin OR bio OR about")
        urls.append(f"https://www.google.com/search?q={q}")
    return urls


def lookup_profiles(names):
    if not names or not sieve.API_KEY:
        return {}

    urls = _build_search_urls(names)

    try:
        session_id = sieve.start_extraction(
            urls=urls,
            instruction=PROFILE_INSTRUCTION,
        )
        result = sieve.poll_result(session_id)
    except Exception:
        return {}

    if not result:
        return {}

    profiles = {}
    raw = result.get("result", [])
    if not isinstance(raw, list):
        return {}

    for profile in raw:
        if not profile or not profile.get("name"):
            continue
        name = profile["name"]
        title = profile.get("title", "")
        company = profile.get("company", "")
        summary = profile.get("summary", "")
        bio = ""
        if title and company:
            bio = f"{title} at {company}"
        elif title:
            bio = title
        if summary:
            bio = f"{bio}. {summary}" if bio else summary
        if bio:
            profiles[name.lower()] = bio

    return profiles


def enrich_events(events):
    all_hosts = set()
    for ev in events:
        for name in ev.get("hosts", []):
            if name and len(name) > 2:
                all_hosts.add(name)

    if not all_hosts:
        return events

    profiles = lookup_profiles(list(all_hosts)[:15])

    for ev in events:
        host_bios = []
        for name in ev.get("hosts", []):
            bio = profiles.get(name.lower())
            if bio:
                host_bios.append(f"{name}: {bio}")
            elif name:
                host_bios.append(name)
        if host_bios:
            ev["host_info"] = "; ".join(host_bios)

    return events
