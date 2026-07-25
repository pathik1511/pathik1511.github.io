#!/usr/bin/env python3
"""
fetch_kaggle.py
================
Pulls Kaggle competition standings for a single user and writes
`kaggle_stats.json` at the repo root. Designed to run from a GitHub
Action on a daily schedule.

WHAT IT CAN AND CANNOT DO  (read this before trusting the numbers)
------------------------------------------------------------------
The Kaggle public API does NOT expose "my rank in competition X"
directly. There is no userRank field. What it DOES expose:

  * competitions_list(...)          -> which comps you have entered
                                       (the `user_has_entered` flag)
  * competition_leaderboard_view    -> the leaderboard rows
                                       (team name + score + date)

So this script derives your rank by downloading each entered
competition's PUBLIC leaderboard and finding your team name in it.

Consequences you must accept:
  * ONGOING comps often hide or partially show the public leaderboard.
    If your team isn't found, the comp is emitted with status="pending"
    ("Entered - rank pending") instead of a fake number.
  * The rank is your PUBLIC-leaderboard rank, which for active comps is
    not your final/private standing.
  * Matching depends on TEAM_NAMES below. If your Kaggle team name isn't
    listed, you won't be found. Fill it in.

Tier + medal COUNTS: the API has no clean per-user medal endpoint either.
Those are read from PROFILE_OVERRIDES below (you maintain them - they
change rarely). Everything else is automatic.

ENV / SECRETS required (set as GitHub repo secrets):
  KAGGLE_USERNAME   your kaggle username  (e.g. pathik1511)
  KAGGLE_KEY        your kaggle API key   (from kaggle.com -> Account -> Create New Token)
"""

import json
import os
import sys
import datetime

# ------------------------------------------------------------------
# CONFIG - EDIT THESE
# ------------------------------------------------------------------

KAGGLE_USERNAME = os.environ.get("KAGGLE_USERNAME", "pathik1511")

# Every team name you have EVER competed under, lowercased match is used.
# Solo competitors: this is usually just your username / display name.
# Add each team name you've used so the rank-finder can locate you.
TEAM_NAMES = [
    "pathik1511",
    "Pathik Patel",
]

# The API cannot reliably return your tier or lifetime medal counts.
# Maintain them here (they rarely change). These feed the four summary
# cards at the top of the Kaggle section.
PROFILE_OVERRIDES = {
    "competitions": {"tier": "Contributor", "rank": None, "gold": 0, "silver": 0, "bronze": 0},
    "notebooks":    {"tier": "Contributor", "gold": 0, "silver": 0, "bronze": 0},
    "datasets":     {"tier": "Novice",      "gold": 0, "silver": 0, "bronze": 0},
    "discussion":   {"tier": "Novice",      "gold": 0, "silver": 0, "bronze": 0},
}

# Manually curated past finishes you want featured. The API can verify /
# refresh these if the leaderboard is downloadable, but listing them here
# guarantees they always appear even for older comps.
# Set "auto": True to let the script try to re-derive rank/percentile.
PAST_OVERRIDES = [
    # {"title": "Titanic - Machine Learning from Disaster", "slug": "titanic",
    #  "rank": 1200, "totalTeams": 15000, "medal": "none", "type": "Getting Started", "auto": True},
]

OUTPUT_PATH = os.environ.get("KAGGLE_OUTPUT", "kaggle_stats.json")

# ------------------------------------------------------------------
# IMPLEMENTATION
# ------------------------------------------------------------------

def log(msg):
    print(f"[fetch_kaggle] {msg}", flush=True)


def get_api():
    """Authenticate. Relies on KAGGLE_USERNAME / KAGGLE_KEY env vars."""
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except Exception as e:
        log(f"kaggle package not importable: {e}")
        raise
    api = KaggleApi()
    api.authenticate()
    return api


def team_matches(name):
    n = (name or "").strip().lower()
    return any(n == t.strip().lower() for t in TEAM_NAMES)


def find_rank_in_leaderboard(api, slug):
    """
    Download the public leaderboard and locate our team.
    Returns (rank, total_teams) or (None, total_teams) if not found,
    or (None, None) if the leaderboard is unavailable.
    """
    try:
        rows = api.competition_leaderboard_view(slug)
    except Exception as e:
        log(f"  leaderboard unavailable for {slug}: {e}")
        return None, None

    if not rows:
        return None, None

    total = len(rows)
    # rows come back sorted by rank; index+1 is the position
    for idx, row in enumerate(rows):
        team = getattr(row, "teamName", None) or getattr(row, "team_name", None) or ""
        if team_matches(team):
            return idx + 1, total
    return None, total


def percentile(rank, total):
    if not rank or not total or total <= 0:
        return None
    # higher = better; top of leaderboard -> ~100
    return round((1 - (rank - 1) / total) * 100, 1)


def medal_from_percentile(pct, total):
    """
    Rough Kaggle medal zones (real thresholds vary by comp size and are
    only awarded on FINAL private leaderboard). Used only as a hint when
    an override doesn't specify a medal.
    """
    if pct is None:
        return "none"
    if pct >= 99:
        return "gold"
    if pct >= 95:
        return "silver"
    if pct >= 90:
        return "bronze"
    return "none"


def build(api):
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    result = {
        "username": KAGGLE_USERNAME,
        "_sample": False,
        "updated": now,
        "profile": PROFILE_OVERRIDES,
        "ongoing": [],
        "past": [],
    }

    # ---- ONGOING: comps we've entered, still open ----
    entered = []
    try:
        page = 1
        while True:
            comps = api.competitions_list(page=page)
            if not comps:
                break
            for c in comps:
                if getattr(c, "userHasEntered", False) or getattr(c, "user_has_entered", False):
                    entered.append(c)
            if len(comps) < 20:
                break
            page += 1
            if page > 10:  # safety
                break
    except Exception as e:
        log(f"competitions_list failed: {e}")

    log(f"entered competitions found: {len(entered)}")

    for c in entered:
        slug = getattr(c, "ref", None) or getattr(c, "id", None)
        title = getattr(c, "title", slug)
        deadline = getattr(c, "deadline", None)
        deadline_str = ""
        try:
            deadline_str = deadline.strftime("%Y-%m-%d") if deadline else ""
        except Exception:
            deadline_str = str(deadline) if deadline else ""

        rank, total = find_rank_in_leaderboard(api, slug)
        if rank:
            result["ongoing"].append({
                "title": title, "slug": slug,
                "rank": rank, "totalTeams": total,
                "percentile": percentile(rank, total),
                "deadline": deadline_str, "status": "ranked",
            })
        else:
            result["ongoing"].append({
                "title": title, "slug": slug,
                "rank": None, "totalTeams": total,
                "percentile": None,
                "deadline": deadline_str, "status": "pending",
            })

    # ---- PAST: curated overrides, optionally auto-refreshed ----
    for p in PAST_OVERRIDES:
        entry = dict(p)
        if p.get("auto") and p.get("slug"):
            rank, total = find_rank_in_leaderboard(api, p["slug"])
            if rank:
                entry["rank"] = rank
                entry["totalTeams"] = total or entry.get("totalTeams")
        entry["percentile"] = percentile(entry.get("rank"), entry.get("totalTeams"))
        if not entry.get("medal") or entry.get("medal") == "auto":
            entry["medal"] = medal_from_percentile(entry["percentile"], entry.get("totalTeams"))
        entry.pop("auto", None)
        result["past"].append(entry)

    return result


def main():
    try:
        api = get_api()
    except Exception:
        log("Authentication failed - writing nothing so the site keeps its "
            "last-known-good JSON. Check KAGGLE_USERNAME / KAGGLE_KEY secrets.")
        sys.exit(1)

    data = build(api)

    with open(OUTPUT_PATH, "w") as f:
        json.dump(data, f, indent=2)
    log(f"wrote {OUTPUT_PATH}: {len(data['ongoing'])} ongoing, {len(data['past'])} past")


if __name__ == "__main__":
    main()
