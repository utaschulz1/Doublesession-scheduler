from typing import Dict, Any
import json
import logging

# Loads data from Input_File for the doubleSessionCalculator which is currently movies_by_title.json
def load_movie_data(filename: str) -> Dict[str, Any]:
    """
    Loads movie data from a JSON file with robust error handling.
    Raises FileNotFoundError or json.JSONDecodeError on failure.
    """
    try:
        logging.info(f"Attempting to load movie data from '{filename}'...")
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
            logging.info(f"Successfully loaded movie data from '{filename}'.")
            return data
    except FileNotFoundError:
        logging.error(f"ERROR: Input file not found: '{filename}'. "
                      "Please ensure 'rearrangeToMoviesByTitle.py' has been run successfully.")
        raise
    except json.JSONDecodeError as e:
        logging.error(f"ERROR: Invalid JSON in file '{filename}': {e}")
        raise
    except Exception as e:
        logging.error(f"An unexpected error occurred while loading '{filename}': {e}")
        raise