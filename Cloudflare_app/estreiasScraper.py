"""
Scrapes the monthly upcoming-releases page on filmspot.pt (estreias).

URL pattern: https://filmspot.pt/estreias/YYYYMM/

The page is structured as a flat sequence of elements inside
  div#contentsNoSidebar.estreias_lado_lado
alternating between:
  - h2.estreiasH2  — week/date separator, id encodes the date: estreiasH2YYYYMMDD
  - div.filmeLista — one card per film,   id encodes the film: filmeListaFILMID

Each filmeLista card contains:
  - div.filmeListaPoster > a  (href = detail page, img alt = title, img src = thumb)
  - div.filmeListaInfo        (h3 with PT title, possibly extra metadata spans)

Output: list of week-blocks, each with an ISO date and a list of film dicts.
"""

import re
import time
import logging
import requests
from bs4 import BeautifulSoup, NavigableString
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional

BASE_URL = "https://filmspot.pt"
ESTREIAS_URL = BASE_URL + "/estreias/{yyyymm}/"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Referer': 'https://filmspot.pt/'
}


def _fetch_soup(url: str) -> BeautifulSoup:
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        return BeautifulSoup(response.content, 'lxml')
    finally:
        time.sleep(1)

# --- helpers ---

def _parse_date_from_h2_id(h2_id: str) -> Optional[str]:
    """
    estreiasH220260402  ->  '2026-04-02'
    Returns None if the id does not match the expected pattern.
    """
    m = re.search(r"estreiasH2(\d{8})$", h2_id)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y%m%d").strftime("%Y-%m-%d")


def _parse_film_id_from_div_id(div_id: str) -> Optional[str]:
    """
    filmeLista1294698  ->  '1294698'
    Returns None if the id does not match the expected pattern.
    """
    m = re.match(r"filmeLista(\d+)$", div_id)
    return m.group(1) if m else None


def _parse_film_card(card_div) -> Dict[str, Any]:
    """
    Extract structured data from a single div.filmeLista element.
    """
    film: Dict[str, Any] = {
        "film_id": _parse_film_id_from_div_id(card_div.get("id", "")),
        "title_pt": None,
        "title_original": None,
        "detail_url": None,
        "poster_thumb_url": None,
    }

    # --- poster section ---
    poster_div = card_div.find("div", class_="filmeListaPoster")
    if poster_div:
        anchor = poster_div.find("a")
        if anchor:
            href = anchor.get("href", "")
            film["detail_url"] = BASE_URL + href if href.startswith("/") else href
            img = anchor.find("img")
            if img:
                film["poster_thumb_url"] = img.get("src")
                # img alt typically holds the PT title
                film["title_pt"] = img.get("alt") or img.get("title")

    # --- info section ---
    info_div = card_div.find("div", class_="filmeListaInfo")
    if info_div:
        h3 = info_div.find("h3")
        if h3:
            anchor = h3.find("a")
            if anchor:
                # Original title is in span.tituloOriginal inside the anchor
                span = anchor.find("span", class_="tituloOriginal")
                if span:
                    film["title_original"] = span.get_text(strip=True)
                    span.extract()  # remove it so it doesn't pollute the PT title
                # PT title is the remaining direct text of the anchor
                film["title_pt"] = anchor.get_text(strip=True) or film["title_pt"]

    return film


def _get_movie_details(detail_url: str) -> Dict[str, Any]:
    """
    Scrapes duration, full poster URL, and description from a film detail page.
    Mirrors get_movie_details_from_page() in dataAllCinemas.py.
    """
    details: Dict[str, Any] = {'duration': None, 'poster_url': None, 'description': None}
    soup = _fetch_soup(detail_url)

    # Duration: div#filmeInfoDivRight > b[string='Duração'] + span > NavigableString
    info_div = soup.find('div', id='filmeInfoDivRight')
    if info_div:
        duration_bold = info_div.find('b', string='Duração')
        if duration_bold:
            duration_span = duration_bold.find_next_sibling('span')
            if duration_span:
                for child in duration_span.children:
                    if isinstance(child, NavigableString):
                        val = child.strip()
                        if val.isdigit():
                            details['duration'] = val
                            break
    if not details['duration']:
        logging.warning(f"Could not extract numeric duration for {detail_url}")

    # Poster: div#filmePosterDiv p a.lightbox img.filmePosterShadow
    poster_img = soup.select_one('div#filmePosterDiv p a.lightbox img.filmePosterShadow')
    if poster_img and 'src' in poster_img.attrs:
        details['poster_url'] = poster_img['src']
    else:
        logging.warning(f"Could not find poster image URL for {detail_url}")

    # Description: #filmeInfoDivLeft > div:nth-child(1)
    description_div = soup.select_one('#filmeInfoDivLeft > div:nth-child(1)')
    if description_div:
        paragraphs = description_div.find_all('p', recursive=False)
        if paragraphs:
            text = "\n".join(p.get_text(strip=True) for p in paragraphs)
        else:
            text = description_div.get_text(separator="\n", strip=True)
        if text:
            details['description'] = text
        else:
            logging.warning(f"Description div empty for {detail_url}")
    else:
        logging.warning(f"Could not find description div for {detail_url}")

    return details


# --- public API ---

def _scrape_listing(year: int, month: int) -> List[Dict[str, Any]]:
    """
    Scrapes the listing page for a given year/month and returns week-blocks
    with basic film data only (no detail page requests).
    """
    yyyymm = f"{year:04d}{month:02d}"
    url = ESTREIAS_URL.format(yyyymm=yyyymm)

    soup = _fetch_soup(url)

    container = soup.find("div", id="contentsNoSidebar")
    if container is None:
        raise RuntimeError(f"Could not find #contentsNoSidebar on {url}")

    weeks: List[Dict[str, Any]] = []
    current_date: Optional[str] = None
    current_films: List[Dict[str, Any]] = []

    for element in container.children:
        if not hasattr(element, "get"):          # skip NavigableString / whitespace
            continue

        tag = element.name
        classes = element.get("class") or []
        el_id = element.get("id", "")

        if tag == "h2" and "estreiasH2" in classes:
            if current_date is not None:
                weeks.append({"release_date": current_date, "films": current_films})
            current_date = _parse_date_from_h2_id(el_id)
            current_films = []

        elif tag == "div":
            if "filmeLista" in classes and el_id.startswith("filmeLista"):
                if current_date is not None:
                    current_films.append(_parse_film_card(element))
            else:
                for card in element.find_all("div", class_="filmeLista", recursive=False):
                    if current_date is not None:
                        current_films.append(_parse_film_card(card))

    if current_date is not None and current_films:
        weeks.append({"release_date": current_date, "films": current_films})

    return weeks


def _enrich_with_details(weeks: List[Dict[str, Any]]) -> None:
    """Fetches detail pages and updates each film dict in-place."""
    all_films = [film for week in weeks for film in week["films"]]
    logging.info(f"Scraping details for {len(all_films)} films...")
    for film in all_films:
        if film.get("detail_url"):
            film.update(_get_movie_details(film["detail_url"]))


def scrape_estreias(year: int, month: int) -> List[Dict[str, Any]]:
    """Scrapes listing + details for a single year/month. Returns week-blocks."""
    weeks = _scrape_listing(year, month)
    _enrich_with_details(weeks)
    return weeks


def scrape_upcoming_weeks(num_weeks: int = 8) -> List[Dict[str, Any]]:
    """
    Scrapes the next num_weeks of release weeks starting from today,
    spanning as many months as needed.

    Returns week-blocks (listing + details) sorted by release_date,
    filtered to the [today, today + num_weeks] window.
    """
    today = date.today()
    end_date = today + timedelta(weeks=num_weeks)

    # Collect all (year, month) pairs that fall within the window
    months: List[tuple] = []
    cursor = today.replace(day=1)
    while cursor <= end_date:
        months.append((cursor.year, cursor.month))
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1)

    logging.info(f"Scraping {num_weeks} weeks ahead across months: "
                 f"{[f'{y}-{m:02d}' for y, m in months]}")

    # Phase 1: collect listing for all months, filter to the window
    filtered_weeks: List[Dict[str, Any]] = []
    for year, month in months:
        for week in _scrape_listing(year, month):
            release_date = date.fromisoformat(week["release_date"])
            if today <= release_date <= end_date:
                filtered_weeks.append(week)

    filtered_weeks.sort(key=lambda w: w["release_date"])

    # Phase 2: enrich only the filtered weeks
    _enrich_with_details(filtered_weeks)

    return filtered_weeks


# --- output path (mirrors pattern in rearrangeToMoviesByTitle.py) ---

import os as _os
_basedir = _os.path.abspath(_os.path.dirname(__file__))
DEFAULT_OUTPUT_FILE = _os.path.join(_basedir, "input", "upcoming_movies.json")


# --- CLI ---

if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) == 3:
        # explicit year + month: scrape that single month
        data = scrape_estreias(int(sys.argv[1]), int(sys.argv[2]))
    else:
        # default: next 8 weeks from today across however many months needed
        data = scrape_upcoming_weeks(num_weeks=8)

    with open(DEFAULT_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logging.info(f"Saved {sum(len(w['films']) for w in data)} films to {DEFAULT_OUTPUT_FILE}")
