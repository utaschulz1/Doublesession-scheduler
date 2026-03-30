# Doublesession Worker — Cloudflare Setup Guide

## Prerequisites

- Cloudflare account with R2 subscription (free tier is sufficient)
- Node.js installed via nvm (not system apt)
- Miniconda with a `doublesession` environment
- `uv` installed (`pip install uv` inside the conda env)

## First-time Setup

### 1. Install wrangler

From the project root (`Cloudflare_app/`):

```bash
npm install wrangler --save-dev
npx wrangler login   # opens browser to authorize with your Cloudflare account
```

### 2. Create the R2 bucket

```bash
npx wrangler r2 bucket create doublesession-data
```

### 3. Scaffold the Worker

```bash
npx wrangler init doublesession-worker
```

Choices during setup:
- **Hello World example**
- **SSR / full-stack app**
- Deploy when prompted: **yes**

This creates the `doublesession-worker/` directory with `src/entry.py` and `wrangler.jsonc`.

### 4. Configure the R2 binding

In `wrangler.jsonc`, add after the `observability` block:

```json
"r2_buckets": [
    {
        "binding": "MOVIE_DATA",
        "bucket_name": "doublesession-data"
    }
]
```

Also remove the `assets` block (the static file serving) — the Worker serves all HTML dynamically:

```json
// Remove this:
"assets": {
    "directory": "./public"
},
```

### 5. Upload the movie data

```bash
npx wrangler r2 object put doublesession-data/movies_by_title.json \
  --file ../input/movies_by_title.json \
  --remote
```

The `--remote` flag is required — without it wrangler uploads to a local dev simulation only.

### 6. Deploy

```bash
cd doublesession-worker
npm run deploy
```

Your Worker is live at `https://doublesession-worker.<your-subdomain>.workers.dev`.

---

## Weekly Data Refresh

Run `refresh_data.sh` from `Cloudflare_app/` to scrape, process, and upload fresh data:

```bash
./refresh_data.sh
```

This runs the full local pipeline in sequence:

1. `dataAllCinemas.py` — scrapes current sessions for all configured cinemas (filmspot.pt)
2. `rearrangeToMoviesByTitle.py` — transforms to movie-centric JSON
3. `estreiasScraper.py` — scrapes filmspot.pt upcoming releases for the next 8 weeks
4. `appendUpcoming.py` — injects the upcoming data as `"upcoming"` into `movies_by_title.json`
5. Uploads `movies_by_title.json` to R2

`dataNimas.py` is a separate scraper for Cinema Medeia Nimas (medeiafilmes.com) — run manually when needed, not part of the automated pipeline.

The upcoming scraper automatically determines which calendar months to fetch based on today's date — no manual month argument needed.

---

## Project Structure

```
Cloudflare_app/
├── dataAllCinemas.py           # Scraper — current cinema sessions (filmspot.pt)
├── dataNimas.py                # Scraper — Cinema Medeia Nimas (medeiafilmes.com), run manually
├── rearrangeToMoviesByTitle.py # Transforms raw scrape into movie-centric JSON
├── estreiasScraper.py          # Scraper — upcoming releases from filmspot.pt
├── appendUpcoming.py           # Injects upcoming data into movies_by_title.json
├── refresh_data.sh             # Weekly scrape + upload script
├── input/
│   ├── all_cinemas_data.json   # Intermediate file, local only
│   ├── global_data_nimas.json  # Output of dataNimas.py, local only
│   ├── upcoming_movies.json    # Intermediate file from estreiasScraper, local only
│   └── movies_by_title.json   # Uploaded to R2, the only file the Worker needs
├── utils/
│   ├── formatTimestamp.py      # Shared time formatting helpers
│   ├── loadInputFile.py        # Shared JSON file loader
│   ├── rel2absFilepath.py      # Path resolution helper
│   └── slugs2names.py          # Cinema slug → display name mapping
├── package.json                # wrangler dependency
└── doublesession-worker/       # Cloudflare Worker project
    ├── src/
    │   ├── entry.py            # FastAPI app, all routes, Jinja2 setup, R2 cache
    │   ├── filters.py          # Movie filtering logic (by cinema and day settings)
    │   ├── calculator.py       # Double session calculation (permutations, gap logic)
    │   └── templates/          # Jinja2 HTML templates
    │       ├── base.html       # Nav, footer, flash message area
    │       ├── home.html
    │       ├── movies.html
    │       ├── upcoming.html   # Upcoming releases page with Share Selected
    │       └── double_sessions.html
    ├── public/css/             # Static CSS files (served by Cloudflare Assets)
    ├── pyproject.toml          # Python dependencies (fastapi, jinja2, etc.)
    └── wrangler.jsonc          # Wrangler config (bindings, compat flags, etc.)
```

---

## How the App Works

### Request flow

Every request hits the Workers runtime, which calls `Default.fetch()` in `entry.py`.
`asgi.fetch()` bridges the Workers request into FastAPI, which routes it to the right function.
`import asgi` is inside `fetch()` (not at module level) to avoid a Pyodide snapshot serialization error at deploy time.

```
Browser → Cloudflare Edge → Workers runtime → Default.fetch() → asgi.fetch() → FastAPI route
```

### FastAPI routes (`entry.py`)

| Route | Method | What it does |
|---|---|---|
| `/` | GET | Home page with last scraped date |
| `/movies` | GET | Filtered movie list, reads cookie for current filters |
| `/movies` | POST | Saves filter changes to cookie, redirects back to GET |
| `/selected_for_double_sessions` | POST | Saves selected movie titles to cookie, redirects to `/double_sessions` |
| `/double_sessions` | GET | Shows planner, auto-calculates if titles in cookie |
| `/double_sessions` | POST | Validates gap settings, saves to cookie, redirects to GET |
| `/upcoming` | GET | Upcoming releases for the next 8 weeks, grouped by release date |

All POST routes follow the **Post/Redirect/Get pattern**: update the cookie, redirect to GET, GET re-renders from cookie. This means results are always calculated fresh on GET — nothing large is stored in the cookie.

### Business logic files

- **`filters.py`** — reads `movies_by_title.json`, filters by excluded cinemas and day settings, returns three lists: approved movies, movies only on excluded days, movies only in excluded cinemas.
- **`calculator.py`** — takes the approved movies, applies per-day start time filters, generates all session permutations, filters by gap constraints, groups by same-cinema / preferred-cinema / other, sorts by day starting from today.

### Upcoming releases pipeline (`estreiasScraper.py` + `appendUpcoming.py`)

`estreiasScraper.py` scrapes `filmspot.pt/estreias/YYYYMM/` — a deterministic, old-school HTML page structured as alternating `h2.estreiasH2` date headers and `div.filmeLista` film cards. The scraper:

1. Calculates which calendar months cover the next 8 weeks from today
2. Fetches each month's listing page (one request per month)
3. Filters week-blocks to only those within the 8-week window
4. Fetches each film's detail page for duration, full poster URL, and description — reusing the exact same selectors as `dataAllCinemas.py`

`appendUpcoming.py` normalises the field names to match the existing `movies` structure (`title_pt`/`title_original` → `title`, `detail_url` → `detail_link`, adds `duration_minutes`) and injects the result as `"upcoming"` into `movies_by_title.json`.

### Advertisement buffer (known limitation)

Session end times in `movies_by_title.json` are calculated at pre-processing time as:

```
end_time = start_time + duration + ADVERTISEMENT_BUFFER_MINUTES (hardcoded to 15)
```

This buffer is applied **uniformly to all cinemas**. Cinemas that run no ads or shorter ad reels (e.g. Ideal) will have artificially late end times, which can cause the planner to reject valid double session combinations. As a workaround, set the minimum gap for same-cinema or different-cinema to a negative value in the planner settings — this effectively cancels out the extra buffer. To permanently change the buffer, edit `ADVERTISEMENT_BUFFER_MINUTES` in `rearrangeToMoviesByTitle.py` and re-run the pre-processing pipeline.

---

### `movies_by_title.json` structure

```json
{
    "_metadata": { ... },
    "movies": [ ... ],               // current week's sessions
    "cinema_slug_to_name_map": { },
    "upcoming": [                    // next 8 weeks of releases
        {
            "release_date": "2026-04-02",
            "movies": [
                {
                    "film_id": "1294698",
                    "title": "Caso 137 / Dossier 137",
                    "duration": "102",
                    "duration_minutes": 102,
                    "detail_link": "https://filmspot.pt/filme/...",
                    "poster_url": "https://filmspot.com.pt/images/...",
                    "description": "..."
                }
            ]
        }
    ]
}
```

### Share features

**Upcoming page** — each movie has a checkbox. A sticky "Share Selected" button collects all checked movies (title + filmspot URL) and calls `navigator.share()` (native share sheet on Android/iOS). Falls back to clipboard copy on desktop.

**Double Sessions results** — each individual combination (Option 1, Option 2…) has a "Share" button. The share text is pre-rendered by Jinja2 (so time formatting is correct) and stored in a `data-share` attribute. Example:

```
🎬 Double Feature — Friday
1. Caso 137
   UCI Cinemas El Corte Inglés • 14:00 → 16:05
——— Gap: 20 min ———
2. A Criada
   UCI Cinemas El Corte Inglés • 16:25 → 18:36
```

### R2 data cache

`movies_by_title.json` is read from R2 once and cached in a module-level variable (`_movie_data_cache`). It persists for the lifetime of the Worker isolate — typically many requests. This avoids hitting R2 on every request. The cache is naturally invalidated when a new version is deployed or the isolate is recycled.

### Session state (cookie)

All user state lives in a single `session` cookie as a plain JSON string (no signing — it's just UI preferences). Cookie is set for 30 days.

```json
{
    "excluded_cinemas": ["Cinemas NOS Almada Forum", "..."],
    "day_settings": {
        "Monday":    {"excluded": false, "start": "18:00"},
        "Tuesday":   {"excluded": false, "start": "18:00"},
        "Wednesday": {"excluded": false, "start": "18:00"},
        "Thursday":  {"excluded": false, "start": "18:00"},
        "Friday":    {"excluded": false, "start": "14:00"},
        "Saturday":  {"excluded": false, "start": "10:00"},
        "Sunday":    {"excluded": false, "start": "10:00"}
    },
    "selected_titles": ["Film A (2025)", "Film B (2025)"],
    "min_gap_same_cinema": -15,
    "max_gap_same_cinema": 45,
    "min_gap_different_cinema": 5,
    "max_gap_different_cinema": 45,
    "preferred_cinema": "UCI Cinemas El Corte Inglés - Lisboa"
}
```

`day_settings` replaces the old two-list approach (preferred weekdays + weekdays-for-time-filter). Each day now has a single earliest start time and an exclude flag. This covers the holiday use case: change Tuesday from 18:00 to 13:00 for a public holiday without touching any other setting.

---

## Key Concepts

- **Binding** (`MOVIE_DATA`): the internal alias your Worker code uses to access the R2 bucket. Set in `wrangler.jsonc`, accessed in Python as `env.MOVIE_DATA`.
- **`--remote` flag**: tells wrangler to talk to the real Cloudflare infrastructure, not the local dev simulation.
- **`python_workers` compatibility flag**: already set in `wrangler.jsonc` by the scaffold — required for Python Workers (still in open beta).
- **Pyodide**: the WebAssembly Python runtime that Workers uses. Supports most pure-Python packages including FastAPI and Jinja2. Bundle size (~8MB) and startup time (~2.5s) are the main trade-offs vs JavaScript Workers.

---

## Development

```bash
cd doublesession-worker
npx wrangler dev --remote   # local dev server using real R2 data
npm run deploy              # deploy to production
```

To test with local R2 data instead:

```bash
npx wrangler r2 object put doublesession-data/movies_by_title.json \
  --file ../input/movies_by_title.json \
  --local
npx wrangler dev   # uses local R2 simulation
```
