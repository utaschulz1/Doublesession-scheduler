"""
Scrapes session data for Cinema Medeia Nimas from medeiafilmes.com
and appends/merges it into input/movies_by_title.json.

Run after rearrangeToMoviesByTitle.py (Cloudflare pipeline equivalent):
    python appendNimas.py

Workflow:
1. Fetches https://medeiafilmes.com/cinemas/cinema-medeia-nimas
2. Parses date sections (id="date-YYYY-MM-DD"), time-slot articles, and film groups
3. For each unique film, fetches its detail page for duration and description
4. Merges Nimas sessions into movies_by_title.json:
   - Matches films by slugified title against existing movies
   - Adds new movie entries for films not already in the file
   - Replaces any existing Nimas sessions (idempotent)
   - Updates cinema_slug_to_name_map
"""

import requests
from bs4 import BeautifulSoup
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from collections import defaultdict

NIMAS_URL = 'https://medeiafilmes.com/cinemas/cinema-medeia-nimas'
CINEMA_SLUG = 'medeia-cinema-nimas-lisboa-73'
CINEMA_NAME = 'Cinema Medeia Nimas'
ADVERTISEMENT_BUFFER_MINUTES = 15

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'pt-PT,pt;q=0.9,en;q=0.5',
    'Referer': 'https://medeiafilmes.com',
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

basedir = os.path.abspath(os.path.dirname(__file__))
MOVIES_BY_TITLE = os.path.join(basedir, 'input', 'movies_by_title.json')


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    text = re.sub(r'^-+|-+$', '', text)
    return text


def fetch_soup(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return BeautifulSoup(r.content, 'lxml')
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch {url}: {e}")
        return None
    finally:
        time.sleep(1)


def scrape_film_details(film_url: str) -> dict:
    """
    Fetch film detail page on medeiafilmes.com.
    Returns {duration_minutes, duration, description}.
    Poster URL is already extracted from the schedule page.
    """
    details = {'duration_minutes': None, 'duration': None, 'description': None}
    soup = fetch_soup(film_url)
    if not soup:
        return details

    # Duration appears in a <li> element like "1h 48min |", "48min |", or "2h05 |"
    for el in soup.find_all(['li', 'p', 'span']):
        dur_match = re.search(r'(\d+)h\s*(\d+)(?:min)?|(\d+)min', el.get_text())
        if dur_match:
            if dur_match.group(1):  # XhYY or Xh YYmin
                hours, mins = int(dur_match.group(1)), int(dur_match.group(2))
            else:                   # YYmin only
                hours, mins = 0, int(dur_match.group(3))
            total = hours * 60 + mins
            if total > 0:
                details['duration_minutes'] = total
                details['duration'] = str(total)
                break

    # Description: content of the sinopse section
    sinopse_h2 = soup.find('h2', string=re.compile('sinopse', re.I))
    if sinopse_h2:
        desc_container = sinopse_h2.find_next_sibling()
        if desc_container:
            desc_text = desc_container.get_text(separator='\n', strip=True)
            if desc_text:
                details['description'] = desc_text

    return details


def get_current_movie_week() -> tuple:
    """Returns (week_start, week_end) as date objects for the current Thu-Wed movie week."""
    today = datetime.now().date()
    days_since_thursday = (today.weekday() - 3) % 7
    week_start = today - timedelta(days=days_since_thursday)
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def scrape_nimas_sessions() -> dict:
    """
    Scrape the Nimas cinema page for all scheduled sessions.

    Returns a dict keyed by slugified movie title:
    {
        "film-slug": {
            "title": "Film Title",
            "detail_link": "https://medeiafilmes.com/filmes/...",
            "poster_url": "https://medeiafilmes.com/uploads/library/....jpg",
            "sessions_by_day": {
                "Friday": ["2026-03-27T13:00:00", ...],
                ...
            }
        }
    }
    """
    soup = fetch_soup(NIMAS_URL)
    if not soup:
        return {}

    films: dict = defaultdict(lambda: {
        'title': None,
        'detail_link': None,
        'poster_url': None,
        'sessions_by_day': defaultdict(list),
    })

    week_start, week_end = get_current_movie_week()
    logging.info(f"Filtering Nimas sessions to current movie week: {week_start} – {week_end}")

    date_sections = soup.find_all('section', id=re.compile(r'^date-\d{4}-\d{2}-\d{2}$'))
    logging.info(f"Found {len(date_sections)} date sections on Nimas page")

    for section in date_sections:
        date_str = section['id'].replace('date-', '')  # e.g. "2026-03-27"
        try:
            section_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            continue
        if not (week_start <= section_date <= week_end):
            logging.debug(f"Skipping {date_str} (outside current movie week)")
            continue

        for article in section.find_all('article', class_='schedule'):
            time_header = article.find('header', class_='schedule-designation')
            if not time_header:
                continue
            h3 = time_header.find('h3')
            if not h3:
                continue
            time_text = h3.get_text(strip=True)  # "13:00"
            iso_datetime = f"{date_str}T{time_text}:00"

            try:
                dt = datetime.fromisoformat(iso_datetime)
            except ValueError:
                logging.warning(f"Could not parse datetime: {iso_datetime}")
                continue
            weekday = dt.strftime('%A')  # "Friday"

            for group in article.find_all('div', class_='schedule-group'):
                title_el = group.find('h3')
                if not title_el:
                    continue
                link_el = title_el.find('a', class_='h-link')
                if not link_el:
                    continue

                title = link_el.get_text(strip=True)
                film_url = link_el.get('href', '').strip()
                movie_id = slugify(title)

                films[movie_id]['title'] = title
                films[movie_id]['detail_link'] = film_url

                # Poster from the schedule group (direct uploads URL)
                if not films[movie_id]['poster_url']:
                    poster_div = group.find(attrs={'data-src': re.compile(r'uploads/library')})
                    if poster_div:
                        films[movie_id]['poster_url'] = poster_div.get('data-src')

                if iso_datetime not in films[movie_id]['sessions_by_day'][weekday]:
                    films[movie_id]['sessions_by_day'][weekday].append(iso_datetime)

    # Sort session times within each day
    for movie_id in films:
        for day in films[movie_id]['sessions_by_day']:
            films[movie_id]['sessions_by_day'][day].sort()

    return dict(films)


def calculate_session_details(start_iso: str, duration_minutes: int | None, buffer: int) -> dict:
    session = {'start': start_iso, 'end': 'N/A', 'end_day_offset': 0}
    if duration_minutes is None:
        return session
    try:
        start = datetime.fromisoformat(start_iso)
        end = start + timedelta(minutes=duration_minutes + buffer)
        session['end'] = end.isoformat()
        if end.day > start.day:
            session['end_day_offset'] = 1
    except (ValueError, TypeError) as e:
        logging.warning(f"Could not calculate end time for {start_iso}: {e}")
    return session


def append_nimas(movies_file: str = MOVIES_BY_TITLE):
    # --- Phase 1: Scrape schedule ---
    logging.info("Scraping Nimas session schedule...")
    nimas_films = scrape_nimas_sessions()
    if not nimas_films:
        logging.error("No films found on Nimas page. Aborting.")
        return
    logging.info(f"Found {len(nimas_films)} unique films at Nimas")

    # --- Phase 2: Load movies_by_title.json ---
    try:
        with open(movies_file, 'r', encoding='utf-8') as f:
            movies_data = json.load(f)
    except FileNotFoundError:
        logging.error(f"File not found: {movies_file}")
        return
    except json.JSONDecodeError:
        logging.error(f"Could not parse JSON: {movies_file}")
        return

    movies_list: list = movies_data.get('movies', [])

    # Build lookup dict by slugified title, plus a secondary lookup with years stripped
    # so "A Criada" matches "A Criada (2025)" from filmspot
    movies_by_id: dict[str, dict] = {}
    movies_by_id_no_year: dict[str, dict] = {}
    for movie in movies_list:
        title = movie.get('title', '')
        mid = slugify(title)
        movies_by_id[mid] = movie
        title_no_year = re.sub(r'\s*\(\d{4}\)\s*$', '', title).strip()
        if title_no_year != title:
            movies_by_id_no_year[slugify(title_no_year)] = movie

    # --- Phase 3: Scrape film detail pages, skipping films already fully described ---
    logging.info("Fetching film detail pages for duration and description...")
    film_details: dict[str, dict] = {}
    for movie_id, film in nimas_films.items():
        if not film['detail_link']:
            continue
        existing = movies_by_id.get(movie_id) or movies_by_id_no_year.get(movie_id)
        if existing and existing.get('duration_minutes') and existing.get('description'):
            logging.info(f"  Skipping details (already in file): {film['title']}")
            continue
        logging.info(f"  Fetching details: {film['title']}")
        film_details[movie_id] = scrape_film_details(film['detail_link'])

    # --- Phase 4: Merge Nimas data into movies_by_title ---
    # Strip all existing Nimas entries from every movie first so stale future-week
    # sessions don't survive when a movie no longer appears in the current week's scrape.
    for movie in movies_list:
        movie['cinemas'] = [c for c in movie.get('cinemas', []) if c.get('cinema_slug') != CINEMA_SLUG]

    updated = 0
    added = 0

    for movie_id, film in nimas_films.items():
        details = film_details.get(movie_id, {})
        duration_minutes = details.get('duration_minutes')

        movie = movies_by_id.get(movie_id) or movies_by_id_no_year.get(movie_id)

        if movie is None:
            # Film not in file yet — create new entry
            movie = {
                'title': film['title'],
                'duration': details.get('duration'),
                'duration_minutes': duration_minutes,
                'detail_link': film['detail_link'],
                'poster_url': film.get('poster_url'),
                'description': details.get('description'),
                'cinemas': [],
            }
            movies_list.append(movie)
            movies_by_id[movie_id] = movie
            added += 1
            logging.info(f"  Added new movie: {film['title']}")
        else:
            # Film already in file — fill gaps and use existing duration if Nimas didn't provide one
            if not movie.get('poster_url') and film.get('poster_url'):
                movie['poster_url'] = film['poster_url']
            if not movie.get('description') and details.get('description'):
                movie['description'] = details['description']
            if not movie.get('duration_minutes') and duration_minutes:
                movie['duration_minutes'] = duration_minutes
                movie['duration'] = details.get('duration')
            if duration_minutes is None:
                duration_minutes = movie.get('duration_minutes')
            updated += 1

        # Build sessions with calculated end times
        sessions_with_details: dict[str, list] = {}
        for day, start_times in film['sessions_by_day'].items():
            sessions_with_details[day] = [
                calculate_session_details(t, duration_minutes, ADVERTISEMENT_BUFFER_MINUTES)
                for t in start_times
            ]

        movie['cinemas'].append({
            'cinema_slug': CINEMA_SLUG,
            'cinema_name': CINEMA_NAME,
            'sessions': sessions_with_details,
        })

    # Re-sort movies alphabetically
    movies_list.sort(key=lambda x: x.get('title', '').lower())

    # Ensure Nimas is in the slug-to-name map
    slug_map = movies_data.setdefault('cinema_slug_to_name_map', {})
    slug_map[CINEMA_SLUG] = CINEMA_NAME

    with open(movies_file, 'w', encoding='utf-8') as f:
        json.dump(movies_data, f, ensure_ascii=False, indent=4)

    logging.info(
        f"Done. Merged {updated} existing + added {added} new movies "
        f"with Nimas sessions into {movies_file}"
    )


if __name__ == '__main__':
    append_nimas()
