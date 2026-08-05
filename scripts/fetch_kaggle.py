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
  KAGGLE_KEY        your kaggle API key   (from kaggle.com -> Settings -> Create New Token)
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
# NOTE: ongoing + past ranks below are now authoritative MANUAL overrides
# (auto=False), so leaderboard matching is OPTIONAL. It only runs for an entry
# explicitly marked auto=True. TEAM_NAMES is kept for that opt-in case.
TEAM_NAMES = [
    "pathik1511",
    "Pathik Patel",
]

# The API cannot reliably return your tier or lifetime medal counts.
# Verified from your Kaggle Progression dashboard (2026-07-25): 0 medals in
# every category, Contributor tier ("on path to Expert") across the board.
PROFILE_OVERRIDES = {
    "competitions": {"tier": "Contributor", "rank": None, "gold": 0, "silver": 0, "bronze": 0},
    "notebooks":    {"tier": "Contributor", "gold": 0, "silver": 0, "bronze": 0},
    "datasets":     {"tier": "Contributor", "gold": 0, "silver": 0, "bronze": 0},
    "discussion":   {"tier": "Contributor", "gold": 0, "silver": 0, "bronze": 0},
}

# Your ACTIVE competitions. The Kaggle API cannot reliably return your live
# rank on ongoing comps (leaderboards are often hidden/partial), so these are
# authoritative MANUAL overrides (auto=False) verified from each leaderboard.
# The daily Action must NOT overwrite them with "pending" — build() below
# only re-derives a rank when an entry is explicitly marked auto=True.
# `score` is the competition's own metric (scales differ per comp); the site
# shows it in the card meta line. Order here is preserved, but the site also
# sorts ongoing best-percentile-first so the strongest result always leads.
ONGOING_OVERRIDES = [
    {"title": "ARC Prize 2026 - ARC-AGI-3", "slug": "arc-prize-2026",
     "rank": 30, "totalTeams": 2072, "score": "1.46", "deadline": "2026-10-25", "auto": False},
    {"title": "AI Agent Security - Multi-Step Tool Attacks", "slug": "ai-agent-security",
     "rank": 338, "totalTeams": 2796, "score": "89.190", "deadline": "2026-08-25", "auto": False},
    {"title": "Biohub - Cell Tracking During Development", "slug": "biohub-cell-tracking",
     "rank": 48, "totalTeams": 2004, "score": "0.916", "deadline": "2026-09-25", "auto": False},
]

# Your completed competitions, read directly from your public profile
# (rank / total teams). Hardcoded (auto=False) because the final ranks are
# known and stable - no leaderboard matching needed. Trimmed to the two
# genuinely competitive finishes (top ~26-28%); the weaker bottom-half
# entries were removed so the section reads as achievement, not padding.
# The site sorts these best-percentile-first automatically.
PAST_OVERRIDES = [
    {"title": "LLM Prompt Recovery", "slug": "llm-prompt-recovery",
     "rank": 567, "totalTeams": 2175, "medal": "none", "type": "Featured", "auto": False},
    {"title": "CommonLit - Evaluate Student Summaries", "slug": "commonlit-evaluate-student-summaries",
     "rank": 573, "totalTeams": 2064, "medal": "none", "type": "Featured", "auto": False},
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
    for idx, row in enumerate(rows):
        team = getattr(row, "teamName", None) or getattr(row, "team_name", None) or ""
        if team_matches(team):
            return idx + 1, total
    return None, total


def percentile(rank, total):
    if not rank or not total or total <= 0:
        return None
    return round((1 - (rank - 1) / total) * 100, 1)


def medal_from_percentile(pct, total):
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

    # ---- ONGOING: curated MANUAL overrides (auto=False). The Kaggle API has
    #      no per-user rank endpoint and ongoing leaderboards are often hidden,
    #      so these are the source of truth and are NEVER wiped to "pending".
    #      An entry is only re-derived from the public leaderboard if it opts
    #      in with auto=True (leaves the number alone if the match fails).
    for o in ONGOING_OVERRIDES:
        entry = {
            "title": o["title"], "slug": o.get("slug"),
            "rank": o.get("rank"), "totalTeams": o.get("totalTeams"),
        }
        if o.get("auto") and o.get("slug"):
            rank, total = find_rank_in_leaderboard(api, o["slug"])
            if rank:
                entry["rank"] = rank
                entry["totalTeams"] = total or entry.get("totalTeams")
        entry["percentile"] = percentile(entry.get("rank"), entry.get("totalTeams"))
        if o.get("score") is not None:
            entry["score"] = o["score"]
        entry["deadline"] = o.get("deadline", "")
        entry["status"] = "ranked" if entry.get("rank") else "pending"
        result["ongoing"].append(entry)

    log(f"ongoing competitions emitted: {len(result['ongoing'])}")

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