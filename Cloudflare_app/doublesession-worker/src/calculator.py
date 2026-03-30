"""
Ported from doubleSessionCalculator.py.
Finds double feature combinations from movie session data.
File I/O and settings imports removed — data and settings passed as arguments.
"""
from datetime import datetime, time as TimeType, date
from itertools import permutations
from typing import List, Dict, Any, Tuple


def filter_and_flatten_sessions(
    all_data: dict,
    selected_titles: List[str],
    excluded_cinemas: List[str],
    day_settings: Dict[str, Any]
) -> List[Dict]:
    valid_sessions = []

    for movie in all_data.get('movies', []):
        title = movie.get('title')
        if title not in selected_titles:
            continue

        for cinema in movie.get('cinemas', []):
            cinema_name = cinema.get('cinema_name', '')
            if cinema_name in excluded_cinemas:
                continue

            for day, sessions_list in cinema.get('sessions', {}).items():
                day_cfg = day_settings.get(day, {})
                if day_cfg.get('excluded', False):
                    continue
                if not isinstance(sessions_list, list):
                    continue

                min_start_str = day_cfg.get('start', '00:00')

                for session in sessions_list:
                    if not isinstance(session, dict):
                        continue

                    if min_start_str != '00:00':
                        session_start = session.get('start')
                        if not session_start:
                            continue
                        try:
                            hour, minute = map(int, min_start_str.split(':'))
                            if datetime.fromisoformat(session_start).time() < TimeType(hour, minute):
                                continue
                        except (ValueError, TypeError):
                            continue

                    valid_sessions.append({
                        'title': title,
                        'cinema': cinema_name,
                        'day': day,
                        **session
                    })

    return valid_sessions


def find_double_features(
    valid_sessions: List[Dict],
    min_gap_same: int,
    max_gap_same: int,
    min_gap_diff: int,
    max_gap_diff: int
) -> List[Tuple[Dict, Dict]]:
    if not valid_sessions:
        return []

    found = []
    for first, second in permutations(valid_sessions, 2):
        if first['day'] != second['day'] or first['title'] == second['title']:
            continue
        if first.get('end_day_offset', 0) == 1:
            continue

        try:
            gap_minutes = (
                datetime.fromisoformat(second['start']) - datetime.fromisoformat(first['end'])
            ).total_seconds() // 60
        except (ValueError, TypeError):
            continue

        if first['cinema'] == second['cinema']:
            if min_gap_same <= gap_minutes <= max_gap_same:
                found.append((first, second))
        else:
            if min_gap_diff <= gap_minutes <= max_gap_diff:
                found.append((first, second))

    found.sort(key=lambda c: (c[0]['day'], c[0]['start'], c[1]['start']))
    return found


def prepare_results_for_display(combinations: List[Tuple], preferred_cinema: str) -> Dict:
    if not combinations:
        return {"message": "No double features found with the selected movies and criteria.", "categories": []}

    today = date.today()

    same_cinema, preferred, other = [], [], []
    for first, second in combinations:
        if first['cinema'] == second['cinema']:
            same_cinema.append((first, second))
        elif first['cinema'] == preferred_cinema or second['cinema'] == preferred_cinema:
            preferred.append((first, second))
        else:
            other.append((first, second))

    same_cinema.sort(key=lambda c: c[0]['cinema'] != preferred_cinema)

    def format_category(title, combos):
        if not combos:
            return None
        by_date = {}
        for first, second in combos:
            date_str = first['start'][:10]
            gap = int((
                datetime.fromisoformat(second['start']) - datetime.fromisoformat(first['end'])
            ).total_seconds() // 60)
            by_date.setdefault(date_str, []).append({
                'first_movie': first,
                'second_movie': second,
                'gap_minutes': gap
            })

        sorted_days = []
        for date_str in sorted(by_date.keys()):
            session_date = date.fromisoformat(date_str)
            sorted_days.append({
                'day': session_date.strftime('%A'),
                'combinations': sorted(by_date[date_str], key=lambda c: datetime.fromisoformat(c['first_movie']['start'])),
                'is_past': session_date < today
            })
        return {'title': title, 'days': sorted_days}

    categories = []
    for title, combos in [
        ("🎬 Same-Cinema Double Features (Most Convenient!)", same_cinema),
        (f"🍿 Double Features Including {preferred_cinema}", preferred),
        ("🎟️ Other Double Feature Options", other),
    ]:
        cat = format_category(title, combos)
        if cat:
            categories.append(cat)

    return {"message": "", "categories": categories}


def calculate_double_sessions(
    all_data: dict,
    selected_titles: List[str],
    excluded_cinemas: List[str],
    day_settings: Dict[str, Any],
    min_gap_same: int,
    max_gap_same: int,
    min_gap_diff: int,
    max_gap_diff: int,
    preferred_cinema: str
) -> Dict:
    valid_sessions = filter_and_flatten_sessions(all_data, selected_titles, excluded_cinemas, day_settings)
    combinations = find_double_features(valid_sessions, min_gap_same, max_gap_same, min_gap_diff, max_gap_diff)
    return prepare_results_for_display(combinations, preferred_cinema)
