"""
This script reads all_cinemas_data.json (produced by dataAllCinemas.py),
transforms it to be movie-centric, and enriches the data by calculating
accurate end times (using scraped DURATION and ADVERTISEMENT_BUFFER_MINUTES from Setting. 
I also calulates a 'end_day_offset' to handle sessions that cross midnight.
It extracts movie details (poster_url, description) from the 'movies' section of the input data.

The output is movies_by_title.json.
Tests:
1. After pressing "Refresh Data" in the Flask app, check that movies_by_title.json is updated.
2. After pressing "Save Preferences" in the Flask app/preferences with a changed ADVERTISEMENT_BUFFER_MINUTES,
   verify that movies_by_title.json reflects the new buffer in its session end times (Endtimes changed accordingly).
3. After pressing "Reset to Default Settings" in the Flask app, verify that movies_by_title.json
   uses the default ADVERTISEMENT_BUFFER_MINUTES in its session end times (Duration + 15).
"""
import json
from datetime import datetime, timedelta
import logging
import sys
import os

ADVERTISEMENT_BUFFER_MINUTES = 15

# --- Configure logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DEFAULT_REARRANGE_INPUT_FILE = 'input/all_cinemas_data.json'
# for Pythonanywhere: convert DEFAULT INPUT FILE PATH path to absolute using system base_dir
basedir = os.path.abspath(os.path.dirname(__file__))
original_default_rearrange_input_file = DEFAULT_REARRANGE_INPUT_FILE
DEFAULT_REARRANGE_INPUT_FILE = os.path.join(basedir, original_default_rearrange_input_file)
if sys.platform == 'win32':
    DEFAULT_REARRANGE_INPUT_FILE = DEFAULT_REARRANGE_INPUT_FILE.replace('/', '\\')
else:
    DEFAULT_REARRANGE_INPUT_FILE = DEFAULT_REARRANGE_INPUT_FILE.replace('\\', '/')

DEFAULT_REARRANGE_OUTPUT_FILE_RELATIVE = 'input/movies_by_title.json' # This is the file for doubleSessionCalculator.py and for readwrite_settings.py which passes it to doubleSessionCalculator.py
# for Pythonanywhere: convert DEFAULT OUTPUT FILE PATH path to absolute using system base_dir
basedir = os.path.abspath(os.path.dirname(__file__))
original_default_rearrange_output_file = DEFAULT_REARRANGE_OUTPUT_FILE_RELATIVE
DEFAULT_REARRANGE_OUTPUT_FILE = os.path.join(basedir, original_default_rearrange_output_file)
if sys.platform == 'win32':
    DEFAULT_REARRANGE_OUTPUT_FILE = DEFAULT_REARRANGE_OUTPUT_FILE.replace('/', '\\')
else:
    DEFAULT_REARRANGE_OUTPUT_FILE = DEFAULT_REARRANGE_OUTPUT_FILE.replace('\\', '/')


def calculate_session_details(start_time_str: str, duration_minutes: int | None, advertisement_buffer_minutes: int) -> dict:
    
    """
     
    Calculates the end time and day offset for a movie session.
    
    Args:
        start_time_str (str): The session start time (e.g., "2025-11-11T21:15:00").
        duration_minutes (int | None): The movie duration in minutes.
        advertisement_buffer (int): The advertisement buffer in minutes to add to duration.

    Returns:
        A dictionary like {"start": "21:50", "end": "00:06", "end_day_offset": 1}
    
    """

    session_details = {
        "start": start_time_str,
        "end": "N/A",
        "end_day_offset": 0
    }

    if duration_minutes is None:
        return session_details

    try:
        total_session_minutes = duration_minutes + advertisement_buffer_minutes
        start_time_obj = datetime.fromisoformat(start_time_str)
        end_time_obj = start_time_obj + timedelta(minutes=total_session_minutes)

        session_details["start"] = start_time_obj.isoformat()
        session_details["end"] = end_time_obj.isoformat()

        # Check if the end time crosses midnight (i.e., is on the next day)
        if end_time_obj.day > start_time_obj.day:
             session_details["end_day_offset"] = 1

        return session_details
    except (ValueError, TypeError) as e:
        logging.warning(f"Error calculating session details for start_time='{start_time_str}', duration='{duration_minutes}': {e}")
        return session_details

def rearrange_cinema_data(input_filename=DEFAULT_REARRANGE_INPUT_FILE, output_filename=DEFAULT_REARRANGE_OUTPUT_FILE):
    advertisement_buffer_minutes = ADVERTISEMENT_BUFFER_MINUTES
    logging.info(f"rearrange_cinema_data is using ADVERTISEMENT_BUFFER_MINUTES: {advertisement_buffer_minutes}")

    """
    Reads structured JSON from DEFAULT_REARRANGE_INPUT_FILE, enriches it with calculated end times, and
    writes a clean, movie-centric JSON file including poster links and descriptions.
    """
    try:
        with open(input_filename, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
        logging.info(f"Successfully loaded '{input_filename}'.")
    except FileNotFoundError:
        logging.error(f"Error: The input file '{input_filename}' was not found.")
        return
    except json.JSONDecodeError:
        logging.error(f"Error: Could not decode JSON from '{input_filename}'. Check file format.")
        return

    # Extract top-level sections
    metadata_input = raw_data.get('metadata', {})
    cinemas_input = raw_data.get('cinemas', {})
    movies_details_input = raw_data.get('movies', {}) # This now contains the duration, poster, description
    cinema_slug_to_name_map_input = raw_data.get('cinema_slug_to_name_map', {})
    
    # Catching potential issues with movies_details_input and log output
    first_three_items = dict(list(movies_details_input.items())[:3])
    logging.info(f"First three movies: {first_three_items}")
    
    movies_by_title_output = {}

    # Initialize movies_by_title_output with core movie details
    # This ensures each movie has its title, duration, poster_url, description, and detail_link
    # even before we add cinema-specific session data.
    for movie_id, details in movies_details_input.items():
        if not isinstance(details, dict):
            logging.warning(f"Skipping invalid movie_id '{movie_id}' in movies_details_input. Expected dict, got: {details}")
            continue

        title = details.get('title')
        if not title:
            logging.warning(f"Skipping movie with no title for movie_id '{movie_id}'. Details: {details}")
            continue

        duration_str = details.get('duration')
        duration_minutes = None
        if isinstance(duration_str, str) and duration_str.isdigit():
            duration_minutes = int(duration_str)
        else:
            logging.warning(f"Invalid or missing duration for movie_id '{movie_id}'. Duration: '{duration_str}'")
        
        movies_by_title_output[movie_id] = {
            'title': title,
            'duration': duration_str, # Store as string as per original script output
            'duration_minutes': duration_minutes, # Store as int for calculations
            'detail_link': details.get('detail_link'),
            'poster_url': details.get('poster_url'),  # New: Poster URL
            'description': details.get('description'), # New: Description
            'cinemas': [] # Placeholder for cinema sessions
        }

    # Now, iterate through cinemas to attach session data to the movies
    for cinema_slug, cinema_info in cinemas_input.items():
        if not isinstance(cinema_info, dict):
            logging.warning(f"Skipping invalid cinema_slug '{cinema_slug}'. Expected dict, got: {cinema_info}")
            continue
        
        cinema_name = cinema_info.get('name', cinema_slug)
        cinema_movies_list = cinema_info.get('movies', [])

        if not isinstance(cinema_movies_list, list):
            logging.warning(f"Skipping invalid movies list for cinema '{cinema_name}'. Expected list, got: {cinema_movies_list}")
            continue

        for movie_at_cinema in cinema_movies_list:
            if not isinstance(movie_at_cinema, dict):
                logging.warning(f"Skipping invalid movie entry in cinema '{cinema_name}'. Entry: {movie_at_cinema}")
                continue

            movie_id = movie_at_cinema.get('movie_id')
            if not movie_id:
                logging.warning(f"Skipping movie in cinema '{cinema_name}' with no movie_id. Movie data: {movie_at_cinema}")
                continue

            if movie_id not in movies_by_title_output:
                logging.warning(f"Movie with movie_id '{movie_id}' found in cinema '{cinema_name}' but not in global movies_details_input. Skipping session data for this movie.")
                continue

            # Get the duration_minutes from the pre-populated movie details for calculation
            duration_for_calc = movies_by_title_output[movie_id].get('duration_minutes')

# TODO: use full ISO time and date strings for start and end times
            sessions_with_details = {}
            movie_sessions = movie_at_cinema.get('sessions')
            if isinstance(movie_sessions, dict):
                for day, start_times in movie_sessions.items():
                    sessions_with_details[day] = []
                    if isinstance(start_times, list):
                        for start_time in start_times:
                            if isinstance(start_time, str):
                                session_info = calculate_session_details(start_time, duration_for_calc,advertisement_buffer_minutes)
                                sessions_with_details[day].append(session_info)
                            else:
                                logging.warning(f"Skipping invalid start_time format for movie_id '{movie_id}' in cinema '{cinema_name}' for day '{day}'. Value: {start_time}")
                    else:
                        logging.warning(f"Skipping invalid sessions format for movie_id '{movie_id}' in cinema '{cinema_name}' for day '{day}'. Expected list of start times, got: {start_times}")
            else:
                logging.warning(f"Skipping invalid sessions structure for movie_id '{movie_id}' in cinema '{cinema_name}'. Expected dict, got: {movie_sessions}")

            cinema_showing_info = {
                'cinema_slug': cinema_slug,
                'cinema_name': cinema_name, # Include cinema name for convenience
                'sessions': sessions_with_details
            }
            movies_by_title_output[movie_id]['cinemas'].append(cinema_showing_info)
    
    # Construct the final output structure
    final_output_structure = {
        "_metadata": {
            "last_scraped": metadata_input.get('last_scraped'),
            "source_url": metadata_input.get('source_url'),
            "cinema_slugs_used": metadata_input.get('cinema_slugs') # Renamed for clarity
        },
        "movies": list(movies_by_title_output.values()), # Convert dict to list of movies
        "cinema_slug_to_name_map": cinema_slug_to_name_map_input
    }

    # Sort movies by title for consistent output
    final_output_structure['movies'].sort(key=lambda x: x.get('title', '').lower())


    with open(output_filename, 'w', encoding='utf-8') as f:
        json.dump(final_output_structure, f, ensure_ascii=False, indent=4)

    logging.info(f"Successfully created '{output_filename}' with enriched data for {len(movies_by_title_output)} unique movies.")

if __name__ == '__main__':
    rearrange_cinema_data(DEFAULT_REARRANGE_INPUT_FILE, DEFAULT_REARRANGE_OUTPUT_FILE)