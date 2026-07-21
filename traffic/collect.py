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


PROFILE_QUERY = """
{
  viewer {
    repositories(ownerAffiliations: OWNER, privacy: PUBLIC) { totalCount }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      contributionCalendar { totalContributions }
    }
  }
}
"""


def graphql(query):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "traffic-collector",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.load(resp)
    if "errors" in body:
        raise RuntimeError(body["errors"])
    return body["data"]


def write_badge(name, label, message, badge_color):
    (BADGES / f"{name}.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "label": label,
                "message": message,
                "color": badge_color,
            },
            indent=2,
        )
        + "\n"
    )


def collect_profile():
    """Profile-level stats. Deliberately omits stars/forks/followers: badging a
    zero draws the eye to the weakest number on the page."""
    v = graphql(PROFILE_QUERY)["viewer"]
    c = v["contributionsCollection"]

    stats = {
        "contributions": ("contributions (1y)", c["contributionCalendar"]["totalContributions"], "brightgreen"),
        "commits": ("commits (1y)", c["totalCommitContributions"], "blue"),
        "pullrequests": ("pull requests (1y)", c["totalPullRequestContributions"], "blueviolet"),
        "projects": ("public projects", v["repositories"]["totalCount"], "orange"),
    }
    for name, (label, value, badge_color) in stats.items():
        write_badge(name, label, f"{value:,}", badge_color)
    print("profile: " + ", ".join(f"{k}={v[1]}" for k, v in stats.items()))


def color(visitors):
    if visitors >= 100:
        return "brightgreen"
    if visitors >= 25:
        return "green"
    if visitors >= 5:
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

        # `uniques` is deduplicated per day, so summing it across days re-adds
        # the owner roughly once per day. Drop one visitor from every day that
        # saw any traffic, on the assumption it was us. Undercounts by 1 on days
        # we genuinely didn't visit; over months that beats inflating by ~365.
        visitors = sum(max(0, d["uniques"] - 1) for d in store["days"].values())

        store["totals"] = {
            "views": total_views,
            "uniques": total_uniques,
            "visitors_excluding_owner": visitors,
        }
        store["tracking_since"] = min(store["days"]) if store["days"] else None

        store_path.write_text(json.dumps(store, indent=2, sort_keys=True) + "\n")
        write_badge(repo, "visitors", f"{visitors:,}", color(visitors))
        print(f"{repo}: {visitors} visitors (raw: {total_views} views / {total_uniques} uniques)")

    try:
        collect_profile()
    except Exception as e:
        # Traffic data is the time-sensitive part; don't fail the run over stats.
        print(f"::warning::profile stats failed: {e}")

    if len(failed) == len(REPOS):
        sys.exit(f"every repo failed: {failed}")


if __name__ == "__main__":
    main()
