"""
Scrapes the Festa do Cinema Italiano website and produces
input/festival_italiano.json with the same structure as movies_by_title.json.

Only sessions in Lisboa, Almada and Setúbal are included.
Films with no qualifying sessions are omitted.
Here is the cinema list for this festival 2026:
Lisboa:
Cinema São Jorge
UCI Cinemas - El Corte Inglés
Coliseu Club
Cinemateca Portuguesa - Museu do Cinema
Setúbal:
Cinema Charlot - Auditório Municipal
Almada:
Auditório Fernando Lopes Graça

Run standalone:
    python scrapeFestivalItaliano.py

Output: input/festival_italiano.json
"""
import requests
from bs4 import BeautifulSoup, NavigableString
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, UTC
from collections import defaultdict
from typing import Optional

LISTING_URL = 'https://festadocinemaitaliano.com/todos-os-filmes'
CITIES_ALLOWED = {'Lisboa', 'Setúbal', 'Almada'}
ADVERTISEMENT_BUFFER_MINUTES = 15

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'pt-PT,pt;q=0.9,en;q=0.5',
    'Referer': 'https://festadocinemaitaliano.com',
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

basedir = os.path.abspath(os.path.dirname(__file__))
OUTPUT_FILE = os.path.join(basedir, 'input', 'festival_italiano.json')


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    text = re.sub(r'^-+|-+$', '', text)
    return text


def fetch_soup(url: str) -> Optional[BeautifulSoup]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return BeautifulSoup(r.content, 'lxml')
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch {url}: {e}")
        return None
    finally:
        time.sleep(1)


def parse_date_iso(date_str: str) -> Optional[str]:
    """Parse 'DD.MM.YYYY' → 'YYYY-MM-DD'."""
    m = re.match(r'(\d{2})\.(\d{2})\.(\d{4})', date_str.strip())
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


def calculate_session_details(start_iso: str, duration_minutes: Optional[int], buffer: int) -> dict:
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


def get_film_links(listing_url: str) -> list[str]:
    """Return all film detail page URLs from the listing page."""
    soup = fetch_soup(listing_url)
    if not soup:
        return []
    cards = soup.select('div.card.cell.h-sorting-item')
    links = []
    for card in cards:
        a = card.find('a', class_='card-link')
        if a and a.get('href'):
            links.append(a['href'])
    logging.info(f"Found {len(links)} film links on listing page")
    return links


def scrape_film_detail(url: str) -> Optional[dict]:
    """
    Scrape a single film detail page.
    Returns a movie dict matching movies_by_title.json structure,
    or None if the film has no sessions in the allowed cities.

    Returned structure:
    {
        "title": ..., "director": ..., "duration": ..., "duration_minutes": ...,
        "detail_link": ..., "poster_url": ..., "description": ...,
        "cinemas": [{"cinema_slug": ..., "cinema_name": ..., "sessions": {...}}]
    }
    """
    soup = fetch_soup(url)
    if not soup:
        return None

    # --- Title ---
    h1 = soup.find('h1', class_='spotlight-title')
    title = h1.get_text(strip=True) if h1 else url.split('/')[-1]

    # --- Director (direct text of h2, before nested h3) ---
    h2_dir = soup.find('h2', class_=re.compile(r't-size-15'))
    director = None
    if h2_dir:
        raw = ''.join(str(c) for c in h2_dir.children if isinstance(c, NavigableString)).strip()
        director = re.sub(r'^de\s+', '', raw).strip() or None

    # --- Meta: country, year, duration ---
    meta_p = soup.find('p', class_=re.compile(r't-size-14.*t-weight-300'))
    duration_minutes = None
    duration_str = None
    year = None
    if meta_p:
        meta_text = meta_p.get_text(strip=True)
        dur_m = re.search(r'(\d+)\'', meta_text)
        if dur_m:
            duration_minutes = int(dur_m.group(1))
            duration_str = str(duration_minutes)
        year_m = re.search(r'\b(19\d{2}|20\d{2})\b', meta_text)
        if year_m:
            year = year_m.group(1)

    # --- Poster (first lazy image, can be <img> or <div>) ---
    poster_el = soup.find(attrs={'data-src': re.compile(r'library/media')})
    poster_url = poster_el.get('data-src') if poster_el else None

    # --- Description (classless <p> elements, skip credits/notes) ---
    description_parts = []
    for p in soup.find_all('p'):
        if p.get('class'):
            continue
        text = p.get_text(strip=True)
        if not text:
            continue
        # Skip "Texto:" attribution lines and "A apresentar..." notes
        if re.match(r'^(Texto:|A apresentar|Cópia|Versão)', text):
            break
        description_parts.append(text)
    description = '\n'.join(description_parts) if description_parts else None

    # --- Sessions (filtered by city) ---
    cinema_slug_to_name: dict[str, str] = {}
    sessions_by_cinema: dict[str, dict] = defaultdict(lambda: defaultdict(list))

    session_articles = soup.find_all('article', class_='l-padding-left-15')
    for article in session_articles:
        h3 = article.find('h3')
        if not h3:
            continue

        # Determine city from the span text
        city_span = h3.find('span')
        city_text = city_span.get_text(strip=True) if city_span else ''
        city = city_text.split('-')[0].strip()
        if city not in CITIES_ALLOWED:
            continue

        # Venue name and slug from the link inside h3
        venue_link = h3.find('a')
        if venue_link:
            venue_name = venue_link.get_text(strip=True)
            venue_href = venue_link.get('href', '')
            cinema_slug = venue_href.rstrip('/').split('/')[-1]
        else:
            venue_name = city_text
            cinema_slug = slugify(city_text)

        cinema_slug_to_name[cinema_slug] = venue_name

        for li in article.select('ul.t-list--arrows > li'):
            cells = li.find_all('div', class_=re.compile(r'^cell'))
            if len(cells) < 2:
                continue

            date_cell = cells[0].get_text(separator=' ', strip=True)
            time_cell = cells[1].get_text(strip=True)

            date_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', date_cell)
            if not date_match:
                continue
            date_iso = parse_date_iso(date_match.group(1))
            if not date_iso:
                continue

            # Build ISO datetime and derive weekday
            iso_datetime = f"{date_iso}T{time_cell}:00"
            try:
                dt = datetime.fromisoformat(iso_datetime)
            except ValueError:
                logging.warning(f"Could not parse datetime {iso_datetime} for {title}")
                continue
            weekday = dt.strftime('%A')

            session_detail = calculate_session_details(iso_datetime, duration_minutes, ADVERTISEMENT_BUFFER_MINUTES)
            if iso_datetime not in [s['start'] for s in sessions_by_cinema[cinema_slug][weekday]]:
                sessions_by_cinema[cinema_slug][weekday].append(session_detail)

    if not sessions_by_cinema:
        return None  # No sessions in allowed cities

    # Build cinemas list
    cinemas = []
    for cinema_slug, days in sessions_by_cinema.items():
        # Sort sessions within each day
        sorted_days = {day: sorted(times, key=lambda s: s['start']) for day, times in days.items()}
        cinemas.append({
            'cinema_slug': cinema_slug,
            'cinema_name': cinema_slug_to_name[cinema_slug],
            'sessions': sorted_days,
        })

    return {
        'title': title,
        'director': director,
        'year': year,
        'duration': duration_str,
        'duration_minutes': duration_minutes,
        'detail_link': url,
        'poster_url': poster_url,
        'description': description,
        'cinemas': cinemas,
        '_cinema_slug_to_name': cinema_slug_to_name,  # temp, stripped before output
    }


def scrape_festival(listing_url: str = LISTING_URL, output_file: str = OUTPUT_FILE):
    logging.info("Fetching film listing...")
    film_links = get_film_links(listing_url)
    if not film_links:
        logging.error("No film links found. Aborting.")
        return

    movies = []
    cinema_slug_to_name: dict[str, str] = {}

    for i, link in enumerate(film_links, 1):
        logging.info(f"[{i}/{len(film_links)}] Scraping: {link}")
        film = scrape_film_detail(link)
        if film is None:
            logging.info(f"  Skipped (no Lisboa/Setúbal sessions)")
            continue
        # Extract and merge cinema slug map, then clean temp key
        cinema_slug_to_name.update(film.pop('_cinema_slug_to_name', {}))
        movies.append(film)
        logging.info(f"  Added: {film['title']} ({len(film['cinemas'])} venue(s))")

    # Sort alphabetically by title
    movies.sort(key=lambda x: x.get('title', '').lower())

    output = {
        '_metadata': {
            'last_scraped': datetime.now(UTC).isoformat(),
            'source_url': listing_url,
            'festival': 'Festa do Cinema Italiano',
        },
        'movies': movies,
        'cinema_slug_to_name_map': cinema_slug_to_name,
    }

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)

    logging.info(
        f"Done. Wrote {len(movies)} films "
        f"({len(cinema_slug_to_name)} venues) to {output_file}"
    )


if __name__ == '__main__':
    scrape_festival()
