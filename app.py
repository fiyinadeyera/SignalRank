"""Flask app. Routes and orchestration only."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, render_template, request, jsonify

import cache
import sources
import ranking
import filters
import webhook
import enrichment

app = Flask(__name__)


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


@app.route("/api/status")
def api_status():
    return jsonify(cache.get_all_status())


@app.route("/api/optimize", methods=["POST"])
def optimize():
    data = request.json
    goals = data.get("goals", "")
    date_filter = data.get("dateFilter", "this-week")

    if not goals:
        return jsonify({"error": "Please enter your goals"}), 400

    all_events = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fn): fn.__name__ for fn in sources.ALL_FETCHERS}
        for future in as_completed(futures):
            name = futures[future]
            try:
                timeout = 120 if "sieve" in name else 30
                result = future.result(timeout=timeout)
                all_events.extend(result)
            except Exception:
                pass

    if not all_events:
        all_events = sources.build_sample_events()
        is_live = False
    else:
        is_live = True
        start_date, end_date = filters.get_date_range(date_filter)
        all_events = filters.filter_by_date(all_events, start_date, end_date)

        if not all_events:
            all_events = sources.build_sample_events()
            is_live = False

    all_events = enrichment.enrich_events(all_events)

    try:
        ranked = ranking.rank_events(all_events, goals)
        return jsonify({
            "success": True,
            "ranking": ranked,
            "events": all_events,
            "is_live": is_live,
            "event_count": len(all_events),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/github-webhook", methods=["POST"])
def github_webhook():
    return webhook.handle_webhook()


def _warm_cache():
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(fn) for fn in sources.ALL_FETCHERS]
        for f in as_completed(futures):
            try:
                f.result(timeout=120)
            except Exception:
                pass


def _cache_refresh_loop():
    _warm_cache()
    while True:
        time.sleep(55 * 60)
        _warm_cache()


_bg_thread = threading.Thread(target=_cache_refresh_loop, daemon=True)
_bg_thread.start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
