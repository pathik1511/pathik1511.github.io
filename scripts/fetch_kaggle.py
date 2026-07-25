#!/usr/bin/env python3
"""
fetch_kaggle.py
================
Writes `kaggle_stats.json` at the repo root for the portfolio Kaggle
section. Designed to run from a GitHub Action on a daily schedule.

WHY SO MUCH IS MANUAL (read before trusting / editing)
------------------------------------------------------
The Kaggle public API does NOT expose "my rank in competition X". There is
no userRank field. It only exposes which comps you've entered and the raw
leaderboard rows (team name + score). Deriving your rank means downloading
a leaderboard and finding your team in it - which fails whenever a comp
hides its leaderboard (common for ONGOING and code competitions) or your
team name doesn't match.

Because that derivation is unreliable, this script treats YOUR reported
numbers as authoritative:
  * ONGOING_OVERRIDES and PAST_OVERRIDES below are the source of truth.
  * Entries with auto=False are never touched by the API - they display
    exactly as written here. Use this for anything the API can't see.
  * Entries with auto=True are refreshed from the leaderboard IF (and only
    if) the script can find your team; otherwise the manual value stays.
  * Newly entered comps not listed below are auto-discovered and appended
    as "pending" so you notice them and can add real numbers.

Tier + medal counts (PROFILE_OVERRIDES) are manual too - no clean per-user
endpoint exists. Verified from your Progression dashboard on 2026-07-25.

ENV / SECRETS required (GitHub repo secrets):
  KAGGLE_USERNAME   e.g. pathik1511
  KAGGLE_KEY        from kaggle.com -> Settings -> Create New Token
Note: with no secrets set, the script exits without overwriting the file,
so a failed auth never wipes your good data.
"""

import json
import os
import sys
import datetime

# ------------------------------------------------------------------
# CONFIG - EDIT THESE
# ------------------------------------------------------------------

KAGGLE_USERNAME = os.environ.get("KAGGLE_USERNAME", "pathik1511")

# Team names you've competed under (lowercased match). Only used to derive
# rank for entries marked auto=True. Solo = your username / display name;
# add any custom team name so the finder can locate you.
TEAM_NAMES = [
    "pathik1511",
    "Pathik Patel",
]

# Tier + lifetime medal counts. Verified from your Kaggle Progression
# dashboard (2026-07-25): 0 medals everywhere, Contributor across the board.
PROFILE_OVERRIDES = {
    "competitions": {"tier": "Contributor", "rank": None, "gold": 0, "silver": 0, "bronze": 0},
    "notebooks":    {"tier": "Contributor", "gold": 0, "silver": 0, "bronze": 0},
    "datasets":     {"tier": "Contributor", "gold": 0, "silver": 0, "bronze": 0},
    "discussion":   {"tier": "Contributor", "gold": 0, "silver": 0, "bronze": 0},
}

# ONGOING competitions. Your live ranks, reported 2026-07-25. auto=False
# keeps them fixed (the API can't reliably read these leaderboards). When a
# competition ends or your rank changes, update the number here - or flip
# auto=True if you want the script to try refreshing it automatically.
ONGOING_OVERRIDES = [
    {"title": "ARC Prize 2026 - ARC-AGI-3", "slug": "arc-prize-2026",
     "rank": 97,  "totalTeams": 1907, "score": "1.25",   "deadline": "2026-10-25", "auto": False},
    {"title": "AI Agent Security - Multi-Step Tool Attacks", "slug": "ai-agent-security",
     "rank": 543, "totalTeams": 2335, "score": "82.620", "deadline": "2026-08-25", "auto": False},
    {"title": "Biohub - Cell Tracking During Development", "slug": "biohub-cell-tracking",
     "rank": 486, "totalTeams": 1615, "score": "0.900",  "deadline": "2026-09-25", "auto": False},
]

# COMPLETED competitions, read from your public profile (rank / total).
# auto=False because final ranks are stable and known.
PAST_OVERRIDES = [
    {"title": "LLM Prompt Recovery", "slug": "llm-prompt-recovery",
     "rank": 567, "totalTeams": 2175, "medal": "none", "type": "Featured", "auto": False},
    {"title": "CommonLit - Evaluate Student Summaries", "slug": "commonlit-evaluate-student-summaries",
     "rank": 573, "totalTeams": 2064, "medal": "none", "type": "Featured", "auto": False},
    {"title": "Linking Writing Processes to Writing Quality", "slug": "linking-writing-processes-to-writing-quality",
     "rank": 1073, "totalTeams": 1876, "medal": "none", "type": "Featured", "auto": False},
    {"title": "Global Wheat Detection", "slug": "global-wheat-detection",
     "rank": 1335, "totalTeams": 2245, "medal": "none", "type": "Research", "auto": False},
    {"title": "OSIC Pulmonary Fibrosis Progression", "slug": "osic-pulmonary-fibrosis-progression",
     "rank": 1719, "totalTeams": 2097, "medal": "none", "type": "Featured", "auto": False},
    {"title": "Cassava Leaf Disease Classification", "slug": "cassava-leaf-disease-classification",
     "rank": 2747, "totalTeams": 3900, "medal": "none", "type": "Research", "auto": False},
]

OUTPUT_PATH = os.environ.get("KAGGLE_OUTPUT", "kaggle_stats.json")

# ------------------------------------------------------------------
# IMPLEMENTATION
# ------------------------------------------------------------------

def log(msg):
    print(f"[fetch_kaggle] {msg}", flush=True)


def get_api():
    from kaggle.api.kaggle_api_extended import KaggleApi
    api = KaggleApi()
    api.authenticate()
    return api


def team_matches(name):
    n = (name or "").strip().lower()
    return any(n == t.strip().lower() for t in TEAM_NAMES)


def find_rank_in_leaderboard(api, slug):
    """Return (rank, total) or (None, total) if not found, (None, None) if
    the leaderboard can't be read."""
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


def medal_from_percentile(pct):
    if pct is None:
        return "none"
    if pct >= 99:
        return "gold"
    if pct >= 95:
        return "silver"
    if pct >= 90:
        return "bronze"
    return "none"


def resolve_override(api, o, is_past):
    """Apply auto-refresh if requested, then compute derived fields."""
    entry = dict(o)
    if o.get("auto") and o.get("slug"):
        rank, total = find_rank_in_leaderboard(api, o["slug"])
        if rank:
            entry["rank"] = rank
            entry["totalTeams"] = total or entry.get("totalTeams")
    entry["percentile"] = percentile(entry.get("rank"), entry.get("totalTeams"))
    if is_past:
        if not entry.get("medal") or entry.get("medal") == "auto":
            entry["medal"] = medal_from_percentile(entry["percentile"])
    else:
        entry["status"] = "ranked" if entry.get("rank") else "pending"
    entry.pop("auto", None)
    return entry


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

    # ---- ONGOING: manual overrides are authoritative ----
    covered = set()
    for o in ONGOING_OVERRIDES:
        result["ongoing"].append(resolve_override(api, o, is_past=False))
        if o.get("slug"):
            covered.add(o["slug"].lower())

    # Auto-discover NEW entered comps not already listed, append as pending
    # so you notice them (never overwrites the ones above).
    try:
        page = 1
        while True:
            comps = api.competitions_list(page=page)
            if not comps:
                break
            for c in comps:
                entered = getattr(c, "userHasEntered", False) or getattr(c, "user_has_entered", False)
                if not entered:
                    continue
                slug = (getattr(c, "ref", None) or getattr(c, "id", "") or "")
                if str(slug).lower() in covered:
                    continue
                covered.add(str(slug).lower())
                deadline = getattr(c, "deadline", None)
                try:
                    dstr = deadline.strftime("%Y-%m-%d") if deadline else ""
                except Exception:
                    dstr = str(deadline) if deadline else ""
                result["ongoing"].append({
                    "title": getattr(c, "title", slug), "slug": slug,
                    "rank": None, "totalTeams": None, "percentile": None,
                    "deadline": dstr, "status": "pending",
                })
            if len(comps) < 20:
                break
            page += 1
            if page > 10:
                break
    except Exception as e:
        log(f"competitions_list failed (kept manual ongoing only): {e}")

    # ---- PAST ----
    for p in PAST_OVERRIDES:
        result["past"].append(resolve_override(api, p, is_past=True))

    return result


def main():
    try:
        api = get_api()
    except Exception as e:
        log(f"Auth failed ({e}). Not overwriting {OUTPUT_PATH} so the site "
            f"keeps its last-known-good data. Check KAGGLE_USERNAME/KAGGLE_KEY.")
        sys.exit(1)

    data = build(api)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(data, f, indent=2)
    log(f"wrote {OUTPUT_PATH}: {len(data['ongoing'])} ongoing, {len(data['past'])} past")


if __name__ == "__main__":
    main()
