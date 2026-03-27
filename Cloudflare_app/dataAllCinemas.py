"""
This script scrapes movie session times for a list of cinemas from filmspot.pt.

Workflow:
1.  Fetches data for each cinema, extracting movie titles and session times.
2.  Identifies all unique movies across all cinemas.
3.  For each unique movie, it scrapes its detail page *once* to get duration, poster, and description.
4.  All collected data is aggregated into three distinct dictionaries:
    - cinemas_data: details per cinema including movie sessions.
    - movies_data: details per movie (duration, poster, description).
    - metadata: script execution details (last_scraped, source_url, cinema_slugs).
5.  The final structured data is written to a single JSON file.
"""

import requests
from bs4 import BeautifulSoup, NavigableString
import json
import logging
import os
import sys
from dotenv import load_dotenv
from datetime import datetime
from collections import defaultdict
import re
import pytz
import time
from typing import List, Dict, Any, Tuple, Set

cinema_slugs = [ # TODO Move to config
    "uci-cinemas-el-corte-ingles-lisboa-61",
    "cinema-city-alvalade-lisboa-59",
    "cinema-city-campo-pequeno-lisboa-58",
    "cinema-fernando-lopes-223",
    "cinema-ideal-91",
    "cinemas-nos-colombo-lisboa-27",
    "medeia-cinema-nimas-lisboa-73",
    "cinemas-nos-almada-forum-22",
    "cinema-cine-teatro-turim-259",
    "cinemas-nos-amoreiras-lisboa-23"
]

SOURCE_URL = "https://filmspot.pt/" # Base URL for metadata

# --- NEW GLOBAL DICTIONARY TO STORE SLUG-TO-NAME MAPPING ---
CINEMA_SLUG_TO_NAME_MAP: Dict[str, str] = {}
# --- END NEW GLOBAL DICTIONARY ---

# --- Configuration and Setup ---

# Set up logging to monitor the script's progress
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables from a .env file (if any)
load_dotenv()

# Standard headers to mimic a browser visit
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Referer': 'https://filmspot.pt/'
}


# --- Utility Functions ---

def slugify(text: str) -> str:
    """Converts a string into a URL-friendly slug."""
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text) # Remove non-word chars
    text = re.sub(r'[\s_-]+', '-', text) # Replace spaces and multiple dashes with single dash
    text = re.sub(r'^-+|-+$', '', text) # Remove leading/trailing dashes
    return text

def fetch_html_soup(url: str) -> BeautifulSoup | None:
    """Fetches content from a URL and returns a BeautifulSoup object."""
    try:
        logging.info(f"Fetching HTML from: {url}")
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
        return BeautifulSoup(response.content, 'lxml')
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch data from {url}: {e}")
        return None
    finally:
        # Always wait after an attempt to fetch, successful or not
        time.sleep(1) # Wait 2 seconds after each request

def extract_screening_events(soup: BeautifulSoup) -> list[dict]:
    """Extracts all application/ld+json scripts containing ScreeningEvent data."""
    scripts = soup.find_all('script', type='application/ld+json')
    events = []
    for script in scripts:
        try:
            if script.string:
                data = json.loads(script.string)
                if isinstance(data, dict) and "@graph" in data:
                    if isinstance(data["@graph"], list):
                        for item in data["@graph"]:
                            if item.get("@type") == "ScreeningEvent":
                                events.append(item)
                    elif isinstance(data["@graph"], dict) and data["@graph"].get("@type") == "ScreeningEvent":
                        events.append(data["@graph"])
                elif isinstance(data, dict) and data.get("@type") == "ScreeningEvent":
                    events.append(data)
        except (json.JSONDecodeError, AttributeError) as e:
            logging.warning(f"Could not parse a JSON-LD script: {e}")
            continue
    return events

def get_movie_details_from_page(detail_url: str) -> dict:
    """
    Scrapes the movie duration, poster image URL, and description from its detail page.
    Returns a dictionary with 'duration', 'poster_url', and 'description'.
    """
    details = {'duration': None, 'poster_url': None, 'description': None}
    soup = fetch_html_soup(detail_url)
    if not soup:
        return details

    # Extract Duration
    info_div = soup.find('div', id='filmeInfoDivRight')
    if info_div:
        duration_bold_tag = info_div.find('b', string='Duração')
        if duration_bold_tag:
            duration_span = duration_bold_tag.find_next_sibling('span')
            if duration_span:
                for child in duration_span.children:
                    if isinstance(child, NavigableString):
                        duration_value = child.strip()
                        if duration_value.isdigit():
                            details['duration'] = duration_value
                            # logging.info(f"Extracted duration '{duration_value}' for {detail_url}") # Too verbose
                            break
    if not details['duration']:
        logging.warning(f"Could not extract numeric duration for {detail_url}")

    # Extract Poster Image URL
    poster_img = soup.select_one('div#filmePosterDiv p a.lightbox img.filmePosterShadow')
    if poster_img and 'src' in poster_img.attrs:
        details['poster_url'] = poster_img['src']
        # logging.info(f"Extracted poster URL '{details['poster_url']}' for {detail_url}") # Too verbose
    else:
        logging.warning(f"Could not find poster image URL for {detail_url}")

    # Extract Description
    description_div = soup.select_one('#filmeInfoDivLeft > div:nth-child(1)')
    if description_div:
        paragraphs = description_div.find_all('p', recursive=False)
        if paragraphs:
            description_text = "\n".join(p.get_text(strip=True) for p in paragraphs)
            if description_text:
                details['description'] = description_text
            else:
                logging.warning(f"Description div found, but no text content for {detail_url}")
        else:
            description_text = description_div.get_text(separator="\n", strip=True)
            if description_text:
                details['description'] = description_text
            else:
                logging.warning(f"Description div found, but no text content for {detail_url} (fallback)")
    else:
        logging.warning(f"Could not find description div for {detail_url}")

    return details

# --- Main Scraping Functions ---

def scrape_cinema_sessions(cinema_slug: str) -> dict | None:
    """
    Scrapes a single cinema's page for movie titles and session times.
    Returns a dictionary with cinema name and a list of movies with their sessions,
    and a set of unique movie detail links found.
    """
    base_url = f'https://filmspot.pt/cinema/{cinema_slug}/'
    logging.info(f"--- Starting session scrape for cinema: {cinema_slug} ---")

    soup = fetch_html_soup(base_url)
    if not soup:
        logging.error(f"Could not fetch or parse the page for {cinema_slug}. Skipping.")
        return None

    # Try to get the cinema name from the page title
    cinema_name_tag = soup.find('h1')
    cinema_name = cinema_name_tag.get_text(strip=True) if cinema_name_tag else cinema_slug
    
    # --- NEW: Store the cinema slug-to-name mapping ---
    global CINEMA_SLUG_TO_NAME_MAP
    CINEMA_SLUG_TO_NAME_MAP[cinema_slug] = cinema_name
    # --- END NEW ---

    screening_events = extract_screening_events(soup)
    if not screening_events:
        logging.warning(f"No screening events found for {cinema_slug}. Skipping.")
        return {"name": cinema_name, "movies": [], "unique_movie_detail_links": set()}

    movies_with_sessions = defaultdict(lambda: {'sessions': defaultdict(list), 'detail_link': ''})
    day_map = {'Seg': 'Segunda-feira', 'Ter': 'Terça-feira', 'Qua': 'Quarta-feira', 'Qui': 'Quinta-feira', 'Sex': 'Sexta-feira', 'Sáb': 'Sábado', 'Dom': 'Domingo'}

    for event in screening_events:
        movie_title = event.get('name')
        if not movie_title: continue
            
        detail_link = event.get('workPresented', {}).get('url') or event.get('url')
        if not detail_link:
            logging.warning(f"No detail link found for movie: {movie_title}")
            continue

        # Use the detail link as a unique identifier for the movie details,
        # but store by title for cinema sessions structure.
        movies_with_sessions[movie_title]['detail_link'] = detail_link

# TODO: use full ISO time and date strings for start times
        try:
            start_datetime = datetime.fromisoformat(event['startDate'])
            iso_datetime_str = start_datetime.isoformat()
            weekday_abbr = start_datetime.strftime('%a')
            weekday_full = day_map.get(weekday_abbr, start_datetime.strftime('%A'))
            time_str = start_datetime.strftime('%H:%M')
            if time_str not in movies_with_sessions[movie_title]['sessions'][weekday_full]:
                movies_with_sessions[movie_title]['sessions'][weekday_full].append(iso_datetime_str)
        except (ValueError, KeyError) as e:
            logging.warning(f"Error processing session date/time for movie {movie_title}: {e}")
            continue
            
    cinema_movies_list = []
    unique_movie_detail_links = set()
    for title, data in movies_with_sessions.items():
        for day in data['sessions']: data['sessions'][day].sort()
        
        # We'll use a slugified title as the movie_id for easier reference
        movie_id = slugify(title) 

        cinema_movies_list.append({
            "movie_id": movie_id, # Reference to the global movies dictionary
            "title": title, # Keep title here for convenience in cinema view
            "sessions": dict(data['sessions'])
        })
        unique_movie_detail_links.add((movie_id, title, data['detail_link']))

    return {
        "name": cinema_name,
        "movies": cinema_movies_list,
        "unique_movie_detail_links": unique_movie_detail_links
    }

# --- Main Execution ---

def main():
    """Main function to run the scraper for a list of cinemas and save to one file with structured data."""
    
    output_filename = 'input/all_cinemas_data.json'
    # for Pythonanywhere: convert output filename path to absolute using system base_dir
    basedir = os.path.abspath(os.path.dirname(__file__))
    original_output_filename = output_filename
    output_filename = os.path.join(basedir, original_output_filename)
    if sys.platform == 'win32':
        output_filename = output_filename.replace('/', '\\')
    else:
        output_filename = output_filename.replace('\\', '/')
    
    all_cinemas_data = {} # Stores data structured by cinema
    all_movies_data = {}  # Stores data structured by movie_id
    global_unique_movie_detail_links = set() # Collects all unique movie links across all cinemas

    try:

        # Phase 1: Scrape all cinemas for sessions and collect unique movie detail links
        for slug in cinema_slugs:
            cinema_result = scrape_cinema_sessions(slug)
            if cinema_result:
                cinema_name = cinema_result.pop("name") # Extract cinema name
                unique_links_for_cinema = cinema_result.pop("unique_movie_detail_links") # Extract unique links
                
                all_cinemas_data[slug] = {
                    "name": cinema_name,
                    "movies": cinema_result["movies"]
                }
                global_unique_movie_detail_links.update(unique_links_for_cinema)
            time.sleep(1) # <--- ADD A DELAY HERE: After each cinema page is scraped

        # Phase 2: Scrape unique movie detail pages for duration, poster, description
        logging.info(f"--- Starting detail scrape for {len(global_unique_movie_detail_links)} unique movies ---")
        for movie_id, title, detail_link in global_unique_movie_detail_links:
            if movie_id not in all_movies_data: # Ensure we only scrape each movie_id once
                # logging.info(f"Scraping details for movie: '{title}' ({detail_link})")
                movie_details = get_movie_details_from_page(detail_link)
                all_movies_data[movie_id] = {
                    "title": title,
                    "detail_link": detail_link,
                    "duration": movie_details.get('duration'),
                    "poster_url": movie_details.get('poster_url'),
                    "description": movie_details.get('description')
                }
            else:
                logging.debug(f"Skipping duplicate movie detail scrape for: '{title}'")
            time.sleep(1) # <--- ADD A DELAY HERE: After each movie detail page is scraped.
                          # Could be shorter than cinema pages, as these might be less intensive.



        # Phase 3: Assemble the final structured output
        final_output = {
            "metadata": {
                "last_scraped": datetime.now(pytz.utc).isoformat(),
                "source_url": SOURCE_URL,
                "cinema_slugs": cinema_slugs # List of slugs used
            },
            "cinemas": all_cinemas_data,
            "movies": all_movies_data,
            "cinema_slug_to_name_map": CINEMA_SLUG_TO_NAME_MAP
        }

        # Write the combined data to a single JSON file
        os.makedirs(os.path.dirname(output_filename), exist_ok=True)
        with open(output_filename, 'w', encoding='utf-8') as json_file:
            json.dump(final_output, json_file, ensure_ascii=False, indent=4)
        
        logging.info(f"--- SCRAPE COMPLETE ---")
        logging.info(f"Successfully wrote data for {len(all_cinemas_data)} cinemas and {len(all_movies_data)} unique movies to {output_filename}")

        return True
    except Exception as e:
        logging.error(f"An unexpected error occurred during scraping: {e}", exc_info=True)
        return False    
    

if __name__ == '__main__':
    main()
    # pass