from workers import WorkerEntrypoint
from fastapi import FastAPI, Request, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from datetime import datetime
import json

from filters import get_movies_data, DEFAULT_EXCLUDED_CINEMAS, DEFAULT_DAY_SETTINGS, ALL_WEEKDAYS
from calculator import calculate_double_sessions

# --- Festival registry ---
# Maps URL slug → display name + R2 filename
FESTIVALS = {
    "festa-do-cinema-italiano-2026": {
        "name": "Festa do Cinema Italiano 2026",
        "r2_key": "festival_italiano.json",
    },
}

DEFAULT_PREFERRED_CINEMA = 'UCI Cinemas El Corte Inglés - Lisboa'
DEFAULT_GAPS = {'min_gap_same_cinema': -15, 'max_gap_same_cinema': 45,
                'min_gap_different_cinema': 5, 'max_gap_different_cinema': 45}

app = FastAPI()

# --- Jinja2 setup ---
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

def format_time_only(iso_str):
    if not iso_str or iso_str == "N/A":
        return "N/A"
    try:
        return datetime.fromisoformat(iso_str).strftime('%H:%M')
    except (ValueError, TypeError):
        return iso_str

def format_timestamp_for_display(iso_str):
    if not iso_str or iso_str == "N/A":
        return "N/A"
    try:
        return datetime.fromisoformat(iso_str).strftime('%d %b %Y %H:%M UTC')
    except (ValueError, TypeError):
        return iso_str

def format_release_date(iso_date: str) -> str:
    try:
        dt = datetime.strptime(iso_date, "%Y-%m-%d")
        return f"{dt.day} {dt.strftime('%B %Y')}"
    except (ValueError, TypeError):
        return iso_date
    
def format_date_short(iso_str):
    if not iso_str or iso_str == "N/A":
        return ""
    try:
        # This handles the "2026-04-02T19:30:00" format for in festival screenings, showing just the date as "02/04"
        return datetime.fromisoformat(iso_str).strftime('%d/%m')
    except (ValueError, TypeError):
        return iso_str

templates.env.filters["format_time_only"] = format_time_only
templates.env.filters["format_timestamp_for_display"] = format_timestamp_for_display
templates.env.filters["format_release_date"] = format_release_date
templates.env.filters["format_date_short"] = format_date_short

# --- R2 cache (persists for the lifetime of the Worker isolate) ---
_movie_data_cache = None
_festival_data_cache = {}

async def get_movie_data(env):
    global _movie_data_cache
    if _movie_data_cache is None:
        obj = await env.MOVIE_DATA.get("movies_by_title.json")
        if obj is None:
            return None
        text = await obj.text()
        _movie_data_cache = json.loads(text)
    return _movie_data_cache

async def get_festival_data(env, r2_key: str):
    global _festival_data_cache
    if r2_key not in _festival_data_cache:
        obj = await env.MOVIE_DATA.get(r2_key)
        if obj is None:
            return None
        text = await obj.text()
        _festival_data_cache[r2_key] = json.loads(text)
    return _festival_data_cache[r2_key]

# --- Cookie helpers ---
def parse_session_cookie(session_cookie: str | None) -> dict:
    if not session_cookie:
        return {}
    try:
        return json.loads(session_cookie)
    except (json.JSONDecodeError, TypeError):
        return {}

def get_day_settings(session_data: dict) -> dict:
    """Returns day_settings from cookie, falling back to defaults for any missing days."""
    stored = session_data.get("day_settings", {})
    if not stored:
        return DEFAULT_DAY_SETTINGS.copy()
    # Fill in any missing days with defaults (defensive)
    return {day: stored.get(day, DEFAULT_DAY_SETTINGS[day]) for day in ALL_WEEKDAYS}

# --- Routes ---

@app.get("/")
async def home(req: Request):
    env = req.scope["env"]
    all_data = await get_movie_data(env)
    last_scraped = all_data.get("_metadata", {}).get("last_scraped", "N/A") if all_data else "N/A"
    return templates.TemplateResponse(req, "home.html", {
        "last_scraped": last_scraped,
        "current_year": datetime.now().year,
        "message": None,
    })

@app.get("/movies")
async def movies_get(req: Request, session: str = Cookie(default=None)):
    env = req.scope["env"]
    all_data = await get_movie_data(env)
    if all_data is None:
        return HTMLResponse("Movie data not found. Please upload movies_by_title.json to R2.", status_code=503)

    session_data = parse_session_cookie(session)
    excluded_cinemas = session_data.get("excluded_cinemas", DEFAULT_EXCLUDED_CINEMAS)
    day_settings = get_day_settings(session_data)

    data = get_movies_data(all_data, excluded_cinemas, day_settings)

    return templates.TemplateResponse(req, "movies.html", {
        **data,
        "selected_titles": session_data.get("selected_titles", []),
        "current_year": datetime.now().year,
        "message": req.query_params.get("error"),
        "message_category": "warning",
    })

@app.post("/movies")
async def movies_post(req: Request, session: str = Cookie(default=None)):
    form = await req.form()
    session_data = parse_session_cookie(session)

    if "restore_defaults" in form:
        session_data.pop("excluded_cinemas", None)
        session_data.pop("day_settings", None)
    elif "apply_filters" in form:
        session_data["excluded_cinemas"] = form.getlist("excluded_cinemas")
        day_settings = {}
        for day in ALL_WEEKDAYS:
            excluded = f"exclude_day_{day}" in form
            start = form.get(f"start_{day}", DEFAULT_DAY_SETTINGS[day]['start'])
            day_settings[day] = {"excluded": excluded, "start": start}
        session_data["day_settings"] = day_settings

    response = RedirectResponse("/movies", status_code=303)
    response.set_cookie("session", json.dumps(session_data), max_age=60*60*24*30)
    return response


@app.get("/upcoming")
async def upcoming_get(req: Request):
    env = req.scope["env"]
    all_data = await get_movie_data(env)
    if all_data is None:
        return HTMLResponse("Movie data not found. Please upload movies_by_title.json to R2.", status_code=503)

    upcoming_weeks = all_data.get("upcoming", [])

    return templates.TemplateResponse(req, "upcoming.html", {
        "upcoming_weeks": upcoming_weeks,
        "current_year": datetime.now().year,
        "message": None,
    })


@app.post("/selected_for_double_sessions")
async def selected_for_double_sessions(req: Request, session: str = Cookie(default=None)):
    form = await req.form()
    selected_titles = form.getlist("movie_title")
    session_data = parse_session_cookie(session)
    session_data["current_context"] = None # Clear any festival context since we're now in the main planner

    if len(selected_titles) < 2 or len(selected_titles) > 15:
        return RedirectResponse("/movies?error=Please+select+between+2+and+15+movies", status_code=303)

    session_data["selected_titles"] = selected_titles
    response = RedirectResponse("/double_sessions", status_code=303)
    response.set_cookie("session", json.dumps(session_data), max_age=60*60*24*30)
    return response

"""
@app.get("/double_sessions")
async def double_sessions_get(req: Request, session: str = Cookie(default=None)):
    env = req.scope["env"]
    all_data = await get_movie_data(env)
    if all_data is None:
        return HTMLResponse("Movie data not found.", status_code=503)

    session_data = parse_session_cookie(session)
    excluded_cinemas = session_data.get("excluded_cinemas", DEFAULT_EXCLUDED_CINEMAS)
    day_settings = get_day_settings(session_data)
    selected_titles = session_data.get("selected_titles", [])
    min_gap_same = session_data.get("min_gap_same_cinema", DEFAULT_GAPS["min_gap_same_cinema"])
    max_gap_same = session_data.get("max_gap_same_cinema", DEFAULT_GAPS["max_gap_same_cinema"])
    min_gap_diff = session_data.get("min_gap_different_cinema", DEFAULT_GAPS["min_gap_different_cinema"])
    max_gap_diff = session_data.get("max_gap_different_cinema", DEFAULT_GAPS["max_gap_different_cinema"])
    preferred_cinema = session_data.get("preferred_cinema", DEFAULT_PREFERRED_CINEMA)

    data = get_movies_data(all_data, excluded_cinemas, day_settings)

    movie_plan_data = None
    if len(selected_titles) >= 2:
        movie_plan_data = calculate_double_sessions(
            all_data, selected_titles, excluded_cinemas, day_settings,
            min_gap_same, max_gap_same, min_gap_diff, max_gap_diff, preferred_cinema
        )

    return templates.TemplateResponse(req, "double_sessions.html", {
        "approved_movies": data["approved_movies"],
        "all_cinemas": data["all_cinemas"],
        "included_cinemas": data["included_cinemas"],
        "excluded_cinemas": excluded_cinemas,
        "day_settings": day_settings,
        "selected_titles": selected_titles,
        "movie_plan_data": movie_plan_data,
        "min_gap_same_cinema": min_gap_same,
        "max_gap_same_cinema": max_gap_same,
        "min_gap_different_cinema": min_gap_diff,
        "max_gap_different_cinema": max_gap_diff,
        "preferred_cinema": preferred_cinema,
        "last_scraped": data["last_scraped"],
        "error": req.query_params.get("error"),
        "current_year": datetime.now().year,
        "message": None,
    })
    """
@app.get("/double_sessions")
async def double_sessions_get(req: Request, session: str = Cookie(default=None)):
    env = req.scope["env"]
    session_data = parse_session_cookie(session)
    
    # --- 1. Determine Context (Festival vs Regular) ---
    context = session_data.get("current_context")
    
    if context in FESTIVALS:
        # Load Festival Data and its specific settings
        festival = FESTIVALS[context]
        all_data = await get_festival_data(env, festival["r2_key"])
        
        fest_session = get_festival_cookie(session_data, context)
        excluded_cinemas = fest_session.get("excluded_cinemas", [])
        # Rebuild day_settings specifically from the festival part of the cookie
        day_settings = {
            day: fest_session.get("day_settings", {}).get(day, DEFAULT_DAY_SETTINGS[day])
            for day in ALL_WEEKDAYS
        }
    else:
        # Load Regular Movie Data and regular settings
        all_data = await get_movie_data(env)
        excluded_cinemas = session_data.get("excluded_cinemas", DEFAULT_EXCLUDED_CINEMAS)
        day_settings = get_day_settings(session_data)

    if all_data is None:
        return HTMLResponse("Movie data not found.", status_code=503)

    # --- 2. Get User Preferences ---
    # These are global across both regular and festival planning
    selected_titles = session_data.get("selected_titles", [])
    min_gap_same = session_data.get("min_gap_same_cinema", DEFAULT_GAPS["min_gap_same_cinema"])
    max_gap_same = session_data.get("max_gap_same_cinema", DEFAULT_GAPS["max_gap_same_cinema"])
    min_gap_diff = session_data.get("min_gap_different_cinema", DEFAULT_GAPS["min_gap_different_cinema"])
    max_gap_diff = session_data.get("max_gap_different_cinema", DEFAULT_GAPS["max_gap_different_cinema"])
    preferred_cinema = session_data.get("preferred_cinema", DEFAULT_PREFERRED_CINEMA)

    # --- 3. Run Calculations ---
    # get_movies_data prepares the "approved_movies" list for the checkboxes
    data = get_movies_data(all_data, excluded_cinemas, day_settings)

    movie_plan_data = None
    if len(selected_titles) >= 2:
        # calculate_double_sessions uses the data we loaded in Step 1
        movie_plan_data = calculate_double_sessions(
            all_data, selected_titles, excluded_cinemas, day_settings,
            min_gap_same, max_gap_same, min_gap_diff, max_gap_diff, preferred_cinema
        )

    return templates.TemplateResponse(req, "double_sessions.html", {
        "approved_movies": data["approved_movies"],
        "all_cinemas": data["all_cinemas"],
        "included_cinemas": data["included_cinemas"],
        "excluded_cinemas": excluded_cinemas,
        "day_settings": day_settings,
        "selected_titles": selected_titles,
        "movie_plan_data": movie_plan_data,
        "min_gap_same_cinema": min_gap_same,
        "max_gap_same_cinema": max_gap_same,
        "min_gap_different_cinema": min_gap_diff,
        "max_gap_different_cinema": max_gap_diff,
        "preferred_cinema": preferred_cinema,
        "last_scraped": data["last_scraped"],
        "error": req.query_params.get("error"),
        "current_year": datetime.now().year,
        "current_context": context, # Pass this so the HTML knows where to link back
        "message": None,
    })


@app.post("/double_sessions")
async def double_sessions_post(req: Request, session: str = Cookie(default=None)):
    form = await req.form()
    session_data = parse_session_cookie(session)

    selected_titles = form.getlist("movie_title")
    if len(selected_titles) < 2 or len(selected_titles) > 15:
        response = RedirectResponse("/double_sessions?error=Please+select+between+2+and+15+movies", status_code=303)
        response.set_cookie("session", json.dumps(session_data), max_age=60*60*24*30)
        return response

    try:
        min_gap_same = int(form.get("min_gap_same_cinema", DEFAULT_GAPS["min_gap_same_cinema"]))
        max_gap_same = int(form.get("max_gap_same_cinema", DEFAULT_GAPS["max_gap_same_cinema"]))
        min_gap_diff = int(form.get("min_gap_different_cinema", DEFAULT_GAPS["min_gap_different_cinema"]))
        max_gap_diff = int(form.get("max_gap_different_cinema", DEFAULT_GAPS["max_gap_different_cinema"]))
    except (ValueError, TypeError):
        return RedirectResponse("/double_sessions?error=Invalid+gap+values", status_code=303)

    errors = []
    if not (-20 <= min_gap_same <= 60):
        errors.append("Min Gap (Same Cinema) must be between -20 and 60")
    if not (0 <= max_gap_same <= 520):
        errors.append("Max Gap (Same Cinema) must be between 0 and 520")
    if not (0 <= min_gap_diff <= 120):
        errors.append("Min Gap (Different Cinema) must be between 0 and 120")
    if not (0 <= max_gap_diff <= 520):
        errors.append("Max Gap (Different Cinema) must be between 0 and 520")
    if min_gap_same > max_gap_same:
        errors.append("Min Gap (Same Cinema) cannot exceed Max Gap")
    if min_gap_diff > max_gap_diff:
        errors.append("Min Gap (Different Cinema) cannot exceed Max Gap")
    if errors:
        from urllib.parse import quote
        return RedirectResponse(f"/double_sessions?error={quote('. '.join(errors))}", status_code=303)

    preferred_cinema = form.get("preferred_cinema", DEFAULT_PREFERRED_CINEMA)

    session_data.update({
        "selected_titles": selected_titles,
        "min_gap_same_cinema": min_gap_same,
        "max_gap_same_cinema": max_gap_same,
        "min_gap_different_cinema": min_gap_diff,
        "max_gap_different_cinema": max_gap_diff,
        "preferred_cinema": preferred_cinema,
    })

    response = RedirectResponse("/double_sessions", status_code=303)
    response.set_cookie("session", json.dumps(session_data), max_age=60*60*24*30)
    return response


def get_festival_cookie(session_data: dict, festival_key: str) -> dict:
    return session_data.get("festivals", {}).get(festival_key, {})

def set_festival_cookie(session_data: dict, festival_key: str, festival_data: dict):
    session_data.setdefault("festivals", {})[festival_key] = festival_data


@app.get("/festivals")
async def festivals_list(req: Request):
    return templates.TemplateResponse(req, "festivals.html", {
        "festivals": FESTIVALS,
        "current_year": datetime.now().year,
        "message": None,
    })


@app.get("/festivals/{festival_key}")
async def festival_get(req: Request, festival_key: str, session: str = Cookie(default=None)):
    festival = FESTIVALS.get(festival_key)
    if festival is None:
        return HTMLResponse("Festival not found.", status_code=404)

    env = req.scope["env"]
    all_data = await get_festival_data(env, festival["r2_key"])
    if all_data is None:
        return HTMLResponse(f"Festival data not found in R2 ({festival['r2_key']}).", status_code=503)

    session_data = parse_session_cookie(session)
    fest_session = get_festival_cookie(session_data, festival_key)

    excluded_cinemas = fest_session.get("excluded_cinemas", [])
    day_settings = {
        day: fest_session.get("day_settings", {}).get(day, DEFAULT_DAY_SETTINGS[day])
        for day in ALL_WEEKDAYS
    }

    data = get_movies_data(all_data, excluded_cinemas, day_settings)

    return templates.TemplateResponse(req, "festival.html", {
        **data,
        "festival_key": festival_key,
        "festival_name": festival["name"],
        "selected_titles": fest_session.get("selected_titles", []),
        "current_year": datetime.now().year,
        "message": req.query_params.get("error"),
        "message_category": "warning",
    })


@app.post("/festivals/{festival_key}")
async def festival_post(req: Request, festival_key: str, session: str = Cookie(default=None)):
    if festival_key not in FESTIVALS:
        return HTMLResponse("Festival not found.", status_code=404)

    form = await req.form()
    session_data = parse_session_cookie(session)
    session_data["current_context"] = festival_key # Track which festival's settings are being edited

    if "restore_defaults" in form:
        session_data.get("festivals", {}).pop(festival_key, None)
    elif "apply_filters" in form:
        day_settings = {}
        for day in ALL_WEEKDAYS:
            excluded = f"exclude_day_{day}" in form
            start = form.get(f"start_{day}", DEFAULT_DAY_SETTINGS[day]['start'])
            day_settings[day] = {"excluded": excluded, "start": start}
        fest_session = get_festival_cookie(session_data, festival_key)
        fest_session["excluded_cinemas"] = form.getlist("excluded_cinemas")
        fest_session["day_settings"] = day_settings
        set_festival_cookie(session_data, festival_key, fest_session)

    response = RedirectResponse(f"/festivals/{festival_key}", status_code=303)
    response.set_cookie("session", json.dumps(session_data), max_age=60*60*24*30)
    return response


@app.post("/festivals/{festival_key}/selected")
async def festival_selected(req: Request, festival_key: str, session: str = Cookie(default=None)):
    if festival_key not in FESTIVALS:
        return HTMLResponse("Festival not found.", status_code=404)

    form = await req.form()
    selected_titles = form.getlist("movie_title")
    session_data = parse_session_cookie(session)

    if len(selected_titles) < 2 or len(selected_titles) > 15:
        return RedirectResponse(
            f"/festivals/{festival_key}?error=Please+select+between+2+and+15+movies",
            status_code=303
        )

    fest_session = get_festival_cookie(session_data, festival_key)
    fest_session["selected_titles"] = selected_titles
    set_festival_cookie(session_data, festival_key, fest_session)

    # Also write to top-level selected_titles and context so the double session planner picks them up
    session_data["selected_titles"] = selected_titles
    session_data["current_context"] = festival_key

    response = RedirectResponse("/double_sessions", status_code=303)
    response.set_cookie("session", json.dumps(session_data), max_age=60*60*24*30)
    return response


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        import asgi
        return await asgi.fetch(app, request, self.env)
