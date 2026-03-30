"""
Ported from availableMoviesDynamic.py.
Filters movie data by excluded cinemas and day settings into 3 categories:
1. approved_movies: in included cinemas on non-excluded days
2. excl_day_movies: in included cinemas but only on excluded days
3. missing_movies: only in excluded cinemas

It also returns the data dict for the templates during classification function. If you want to render more data in the template, add it to the base dict in classify_movies and it will be available in all 3 categories.
"""
from typing import List, Dict, Any, Tuple, Set

ALL_WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

DEFAULT_EXCLUDED_CINEMAS = [
    'Cinemas NOS Almada Forum',
    'Cinema City Alvalade - Lisboa',
    'Cinema City Campo Pequeno - Lisboa'
]

DEFAULT_DAY_SETTINGS = {
    'Monday':    {'excluded': False, 'start': '18:00'},
    'Tuesday':   {'excluded': False, 'start': '18:00'},
    'Wednesday': {'excluded': False, 'start': '18:00'},
    'Thursday':  {'excluded': False, 'start': '18:00'},
    'Friday':    {'excluded': False, 'start': '14:00'},
    'Saturday':  {'excluded': False, 'start': '10:00'},
    'Sunday':    {'excluded': False, 'start': '10:00'},
}


def get_all_cinemas(all_data: dict) -> List[str]:
    return list(all_data.get('cinema_slug_to_name_map', {}).values())


def get_cinema_lists(all_data: dict, excluded_cinemas: List[str]) -> Tuple[List[str], Set[str]]:
    all_cinemas = get_all_cinemas(all_data)
    included = sorted([c for c in all_cinemas if c not in excluded_cinemas])
    return included, set(included)


def get_day_sets(day_settings: Dict[str, Any]) -> Tuple[Set[str], Set[str]]:
    excluded = {day for day, cfg in day_settings.items() if cfg.get('excluded', False)}
    included = {day for day in ALL_WEEKDAYS if day not in excluded}
    return excluded, included


def classify_movies(
    all_data: dict,
    included_cinemas_set: Set[str],
    included_days_set: Set[str],
    excluded_days_set: Set[str]
) -> Tuple[Dict, Dict, Dict]:
    approved, excl_day, missing = {}, {}, {}

    for movie in all_data.get('movies', []):
        title = movie.get('title')
        if not title or not isinstance(movie.get('cinemas'), list):
            continue

        approved_cinemas, excl_day_cinemas, missing_cinemas = [], [], []
        has_approved_session = False

        for cinema in movie['cinemas']:
            cinema_name = cinema.get('cinema_name')
            if not cinema_name:
                continue

            if cinema_name in included_cinemas_set:
                preferred_sessions, excl_sessions = {}, {}
                for day, sessions in cinema.get('sessions', {}).items():
                    if day in included_days_set and sessions:
                        preferred_sessions[day] = sessions
                        has_approved_session = True
                    elif day in excluded_days_set and sessions:
                        excl_sessions[day] = sessions

                if preferred_sessions:
                    c = cinema.copy()
                    c['sessions'] = preferred_sessions
                    approved_cinemas.append(c)
                elif excl_sessions:
                    c = cinema.copy()
                    c['sessions'] = excl_sessions
                    excl_day_cinemas.append(c)
            else:
                missing_cinemas.append(cinema)

        base = {
            'detail_link': movie.get('detail_link', ''),
            'poster_url': movie.get('poster_url', ''),
            'duration': movie.get('duration', ''),
            'description': movie.get('description', ''),
            'director': movie.get('director'),
            'year': movie.get('year'),
        }

        if has_approved_session:
            approved[title] = {**base, 'cinemas': approved_cinemas}
        elif excl_day_cinemas:
            excl_day[title] = {**base, 'cinemas': excl_day_cinemas}
        elif missing_cinemas:
            missing[title] = {**base, 'cinemas': missing_cinemas}

    return approved, excl_day, missing


def format_movies(movies_dict: Dict) -> List[Dict]:
    return [
        {'title': title, **details}
        for title, details in sorted(movies_dict.items())
    ]


def get_movies_data(all_data: dict, excluded_cinemas: List[str], day_settings: Dict[str, Any]) -> Dict[str, Any]:
    included_list, included_set = get_cinema_lists(all_data, excluded_cinemas)
    excluded_days_set, included_days_set = get_day_sets(day_settings)

    approved, excl_day, missing = classify_movies(
        all_data, included_set, included_days_set, excluded_days_set
    )

    return {
        'approved_movies': format_movies(approved),
        'excl_day_movies': format_movies(excl_day),
        'missing_movies': format_movies(missing),
        'last_scraped': all_data.get('_metadata', {}).get('last_scraped', 'N/A'),
        'all_cinemas': get_all_cinemas(all_data),
        'included_cinemas': included_list,
        'excluded_cinemas': excluded_cinemas,
        'day_settings': day_settings,
    }
