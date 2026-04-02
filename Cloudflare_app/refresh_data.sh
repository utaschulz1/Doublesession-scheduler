#!/usr/bin/env bash
set -e #makes it stop immediately if any step fails, so a scrape failure won't silently skip the upload

# Activate the conda environment that has requests, beautifulsoup4, etc.
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate doublesession

python dataAllCinemas.py
python rearrangeToMoviesByTitle.py

# Scrape Nimas directly from medeiafilmes.com (not on filmspot) and append to movies_by_title.json
python appendNimas.py

# Scrape upcoming releases and append to movies_by_title.json
python estreiasScraper.py
python appendUpcoming.py

npx wrangler r2 object put doublesession-data/movies_by_title.json --file input/movies_by_title.json --remote
# npx wrangler r2 object put doublesession-data/festival_italiano.json --file input/festival_italiano.json --remote

# --- Deploy options (run manually from doublesession-worker/) ---
# cd doublesession-worker

# Local dev (connects to remote R2):
# npx wrangler dev --remote

# Deploy to Cloudflare:
# npx wrangler deploy
