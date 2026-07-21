#!/usr/bin/env python3
"""Accumulate GitHub traffic data past the API's rolling 14-day window.

The traffic API only ever returns the last 14 days. We merge each run into a
per-repo store keyed by date, so totals keep growing. Re-running on the same
day overwrites that day's bucket rather than double-counting it.
"""

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

OWNER = "Wolfi-OwO"
REPOS = [
    "lattice",
    "portfolio-webpage",
    "network-visualizer",
    "cli-image-upscaler",
    "Wolfi-OwO",
    "learnsphere",
]

ROOT = pathlib.Path(__file__).parent
DATA = ROOT / "data"
BADGES = ROOT / "badges"

TOKEN = os.environ.get("TRAFFIC_TOKEN")
if not TOKEN:
    sys.exit("TRAFFIC_TOKEN is not set")


def fetch(repo):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{OWNER}/{repo}/traffic/views",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "traffic-collector",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def color(views):
    if views >= 1000:
        return "brightgreen"
    if views >= 100:
        return "green"
    if views >= 10:
        return "blue"
    return "lightgrey"


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    BADGES.mkdir(parents=True, exist_ok=True)
    failed = []

    for repo in REPOS:
        store_path = DATA / f"{repo}.json"
        store = (
            json.loads(store_path.read_text())
            if store_path.exists()
            else {"days": {}}
        )

        try:
            payload = fetch(repo)
        except urllib.error.HTTPError as e:
            # Don't let one repo wipe out the run; keep the old badge in place.
            print(f"::warning::{repo}: HTTP {e.code} {e.reason}")
            failed.append(repo)
            continue

        for day in payload.get("views", []):
            date = day["timestamp"][:10]
            store["days"][date] = {
                "count": day["count"],
                "uniques": day["uniques"],
            }

        total_views = sum(d["count"] for d in store["days"].values())
        total_uniques = sum(d["uniques"] for d in store["days"].values())
        store["totals"] = {"views": total_views, "uniques": total_uniques}
        store["tracking_since"] = min(store["days"]) if store["days"] else None

        store_path.write_text(json.dumps(store, indent=2, sort_keys=True) + "\n")
        (BADGES / f"{repo}.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "label": "views",
                    "message": f"{total_views:,}",
                    "color": color(total_views),
                },
                indent=2,
            )
            + "\n"
        )
        print(f"{repo}: {total_views} views / {total_uniques} uniques")

    if len(failed) == len(REPOS):
        sys.exit(f"every repo failed: {failed}")


if __name__ == "__main__":
    main()
