# Portfolio update — Kaggle stats + interactivity

This bundle upgrades your GitHub Pages portfolio (`pathik1511.github.io`).
Everything is drop-in. The site works the moment you commit it (showing
**sample** Kaggle data); the live auto-updating data turns on after you do
the two-minute secrets step below.

---

## What's in this bundle

```
index.html                       your site + new Kaggle & Projects sections
kaggle_stats.json                data the site reads (starts as placeholder)
scripts/fetch_kaggle.py          pulls your real Kaggle standings
.github/workflows/kaggle.yml     runs the script daily, commits the JSON
README_KAGGLE_SETUP.md           this file
```

## What changed on the site

- **New Kaggle section** — tier + medal cards, ongoing-competition cards
  with live rank + percentile, and a past-top-finishes table.
- **New Projects section** — filterable cards (click a tag to filter).
  Edit these in `index.html` (search for `projects:` inside the `DATA`
  object). SVG icons, not emoji.
- **Theme toggle now remembers** your light/dark choice (localStorage).
- Nav, mobile menu, and scroll-spy updated to include both new sections.

---

## Step 1 — Commit the files

Copy all four files into the root of your `pathik1511.github.io` repo,
keeping the folder structure (`scripts/` and `.github/workflows/` matter).
Commit and push. GitHub Pages redeploys in ~1 minute. The Kaggle section
will show **sample** data with a "Sample data — connect the GitHub Action
to go live" note. That's expected until Step 2.

## Step 2 — Add your Kaggle API credentials as repo secrets

1. Get a Kaggle API token: kaggle.com → your avatar → **Settings** →
   **API** → **Create New Token**. This downloads `kaggle.json` containing
   your `username` and `key`.
2. In your GitHub repo: **Settings → Secrets and variables → Actions →
   New repository secret**. Add two secrets:
   - `KAGGLE_USERNAME`  → your username (`pathik1511`)
   - `KAGGLE_KEY`       → the `key` value from `kaggle.json`

   > Do **not** commit `kaggle.json` to the repo. Secrets only.

## Step 3 — Tell the script who "you" are on leaderboards

Open `scripts/fetch_kaggle.py` and edit:

- `TEAM_NAMES` — every team name you've competed under (solo players:
  usually just your username and display name). The script finds your rank
  by locating this name in each leaderboard, so if it's wrong you won't be
  found.
- `PROFILE_OVERRIDES` — your tier and lifetime medal counts per category.
  The API can't return these cleanly, so you set them here. They change
  rarely.
- `PAST_OVERRIDES` — the past competitions you want featured in the table.
  There's a commented example. Set `"auto": True` to let the script
  re-derive rank/percentile from the (final) leaderboard.

## Step 4 — Run it

**Actions** tab → **Update Kaggle Stats** → **Run workflow**. It fetches,
writes `kaggle_stats.json`, and commits it. Your site picks it up on the
next Pages deploy. After that it runs automatically every day at ~02:15
America/New_York.

---

## Honest limitations (so the numbers don't surprise you)

- **Kaggle has no "my rank" API.** Rank is derived by downloading each
  competition's public leaderboard and finding your team. This is reliable
  for **finished** competitions and best-effort for **ongoing** ones.
- **Ongoing comps** frequently hide or truncate the public leaderboard.
  When your team can't be found, that competition shows
  **"Entered — rank pending"** instead of a made-up number. This is by
  design — it's honest.
- **Public vs. private leaderboard.** For an active competition the derived
  rank is your *public* standing, which can differ from the final result.
- **Medal counts / tier** are maintained by you in `PROFILE_OVERRIDES`
  because no clean per-user endpoint exists.

## Editing content later

- **Projects:** `index.html`, `DATA.projects` array. Each entry has
  `title`, `desc`, `tags` (drive the filter bar), `icon` (one of:
  network, chart, tag, pulse, flow, cloud), and optional `github` / `demo`
  URLs.
- **Kaggle sample fallback:** `index.html`, `KAGGLE_FALLBACK` — only shown
  before the first real fetch or when opened as a local `file://`. The live
  JSON always wins when the site is hosted.

## Troubleshooting

- **Section shows sample data on the live site** → the workflow hasn't run
  successfully yet, or `kaggle_stats.json` still has `"_sample": true`. Run
  the workflow and check its log.
- **Workflow is red** → almost always the secrets. Confirm
  `KAGGLE_USERNAME` / `KAGGLE_KEY` are set exactly.
- **Ongoing comp missing** → you may not be flagged as entered yet, or its
  leaderboard is fully private. It'll appear once Kaggle exposes it.
- **Opening index.html by double-click shows sample data** → normal.
  Browsers block `fetch()` on `file://`. It works once hosted (http/https).
