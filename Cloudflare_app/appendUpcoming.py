"""
Reads input/upcoming_movies.json (produced by estreiasScraper.py) and injects
its contents into input/movies_by_title.json as an "upcoming" key.

Run after estreiasScraper.py:
    python estreiasScraper.py 2026 4
    python appendUpcoming.py

Film fields are normalised to match the existing "movies" structure:
  title_pt + title_original  →  title  ("PT / Original" or just "PT")
  detail_url                 →  detail_link
  duration (str)             →  duration + duration_minutes (int)
  poster_thumb_url is dropped; poster_url is kept
  film_id is kept (not present in current movies, but useful for upcoming)
"""

import json
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

basedir = os.path.abspath(os.path.dirname(__file__))
UPCOMING_FILE   = os.path.join(basedir, "input", "upcoming_movies.json")
MOVIES_BY_TITLE = os.path.join(basedir, "input", "movies_by_title.json")


def _normalise_film(film: dict) -> dict:
    """Renames/reshapes upcoming film fields to match the existing movies structure."""
    title_pt       = film.get("title_pt") or ""
    title_original = film.get("title_original")
    title = f"{title_pt} / {title_original}" if title_original else title_pt

    duration_str = film.get("duration")
    duration_minutes = int(duration_str) if duration_str and duration_str.isdigit() else None

    return {
        "film_id":          film.get("film_id"),
        "title":            title,
        "duration":         duration_str,
        "duration_minutes": duration_minutes,
        "detail_link":      film.get("detail_url"),
        "poster_url":       film.get("poster_url"),
        "description":      film.get("description"),
    }


def append_upcoming(upcoming_file=UPCOMING_FILE, movies_file=MOVIES_BY_TITLE):
    try:
        with open(upcoming_file, "r", encoding="utf-8") as f:
            upcoming = json.load(f)
    except FileNotFoundError:
        logging.error(f"Upcoming file not found: {upcoming_file}")
        return
    except json.JSONDecodeError:
        logging.error(f"Could not parse JSON from: {upcoming_file}")
        return

    try:
        with open(movies_file, "r", encoding="utf-8") as f:
            movies_data = json.load(f)
    except FileNotFoundError:
        logging.error(f"Movies file not found: {movies_file}")
        return
    except json.JSONDecodeError:
        logging.error(f"Could not parse JSON from: {movies_file}")
        return

    normalised = [
        {
            "release_date": week["release_date"],
            "movies": [_normalise_film(f) for f in week["films"]],
        }
        for week in upcoming
    ]

    movies_data["upcoming"] = normalised

    with open(movies_file, "w", encoding="utf-8") as f:
        json.dump(movies_data, f, ensure_ascii=False, indent=4)

    total_films = sum(len(week["movies"]) for week in normalised)
    logging.info(
        f"Injected {len(upcoming)} release weeks / {total_films} films "
        f"as 'upcoming' into {movies_file}"
    )


if __name__ == "__main__":
    append_upcoming()
