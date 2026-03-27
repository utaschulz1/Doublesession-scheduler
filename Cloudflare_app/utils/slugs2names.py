import logging
from typing import Set, Tuple, List
from utils.loadInputFile import load_movie_data
from rearrangeToMoviesByTitle import DEFAULT_REARRANGE_OUTPUT_FILE

INPUT_FILE = DEFAULT_REARRANGE_OUTPUT_FILE

def cinema_slugs_to_names(excluded_cinemas_set: Set[str], included_cinemas_set: Set[str]) -> Tuple[List[str], List[str]]:
    '''
    1. loads cinema slug:name dict from scraped data file (all_cinema_data.json) 
    },
    "cinema_slug_to_name_map": {
        "uci-cinemas-el-corte-ingles-lisboa-61": "UCI Cinemas El Corte Inglés - Lisboa",
        "cinema-city-alvalade-lisboa-59": "Cinema City Alvalade - Lisboa",
    2. turns ex/included cinema_slug list into cinema_name list
    '''
    all_movies_data = load_movie_data(INPUT_FILE)
    cinema_slug_to_name_map = all_movies_data.get('cinema_slug_to_name_map', {})
    if not cinema_slug_to_name_map:
        logging.warning("cinema_slug_to_name_map not found in JSON. Attempting to reconstruct from 'cinemas' section (not implemented here).")
        # You might add logic here to reconstruct the map if needed,
        # otherwise, this function will return empty lists for names.
        return {
            'included_cinema_names': [],
            'excluded_cinema_names': []
        }
    def convert_slugs_to_names(slug_set: Set[str]) -> List[str]:
        names = []
        for slug in slug_set:
            name = cinema_slug_to_name_map.get(slug)
            if name:
                names.append(name)
            else:
                logging.warning(f"Cinema slug '{slug}' not found in cinema_slug_to_name_map.")
        return names

    excluded_cinema_names = convert_slugs_to_names(excluded_cinemas_set)
    included_cinema_names = convert_slugs_to_names(included_cinemas_set)

    return excluded_cinema_names, included_cinema_names


def convert_single_cinema_slug_to_name(preferred_cinema_slug: str) -> str:
    '''
    Converts a single cinema_slug (dict with 1 key:value) to its cinema_name.
    '''
    all_movies_data = load_movie_data(INPUT_FILE)
    cinema_slug_to_name_map = all_movies_data.get('cinema_slug_to_name_map', {})

    if not cinema_slug_to_name_map:
        logging.warning("cinema_slug_to_name_map not found in JSON. Cannot convert cinema slug.")
        return None

    name = cinema_slug_to_name_map.get(preferred_cinema_slug)
    if not name:
        logging.warning(f"Preferred cinema slug '{preferred_cinema_slug}' not found in cinema_slug_to_name_map.")
    return name