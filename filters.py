"""Date range and event filtering."""

from datetime import datetime, timedelta


def get_date_range(date_filter):
    today = datetime.now().date()

    if date_filter == "today":
        return today, today
    elif date_filter == "next-week":
        start = today + timedelta(days=8)
        end = today + timedelta(days=14)
        return start, end
    else:
        return today, today + timedelta(days=7)


def filter_by_date(events, start_date, end_date):
    filtered = []
    for event in events:
        try:
            event_date_str = event.get("start", "").split()[0]
            event_date = datetime.strptime(event_date_str, "%Y-%m-%d").date()
            if start_date <= event_date <= end_date:
                filtered.append(event)
        except Exception:
            pass
    return filtered
