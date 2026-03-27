# This is a utility module to format ISO timestamp strings into a human-readable format. 
# The timestamp is saved in the all_cinemas_data.json source file on scraping. by Python.
# The functions here are used in flaskapp.py as routes for jinja2 filters.

from datetime import datetime
import pytz # We'll use pytz for timezone awareness if you need it later, for robustness.

def format_timestamp_for_display(iso_timestamp: str, target_timezone: str = 'Europe/Lisbon') -> str:
    """
    Transforms an ISO-formatted timestamp string into a more human-readable format.

    Args:
        iso_timestamp (str): The ISO 8601 formatted datetime string (e.g., "2025-10-20T19:01:44.200641").
        target_timezone (str): The timezone to localize the datetime to for display.
                                Defaults to 'Europe/Lisbon'.

    Returns:
        str: A formatted string like "{weekday}, week {weeknumber} {yyyy}, Time: {hh:mm:ss}.
             Current weeknumber: {current weeknumber}."
             Returns "Invalid date/time" if parsing fails.
    """
    if iso_timestamp == "N/A" or not iso_timestamp:
        return "No data available."

    try:
        # 1. Parse the ISO timestamp string into a datetime object
        # The 'T' separates date and time, and the microseconds are optional
        dt_obj_utc = datetime.fromisoformat(iso_timestamp)

        # Ensure timezone awareness (the original string might be naive, or already UTC)
        # Assuming the ISO string is UTC if no timezone info is provided, then localize
        # A more robust solution might involve knowing the source timezone of the ISO string
        if dt_obj_utc.tzinfo is None:
            # If the datetime object is naive, assume it's UTC and make it timezone-aware
            dt_obj_utc = pytz.utc.localize(dt_obj_utc)
        else:
            # If it already has tzinfo, convert it to UTC
            dt_obj_utc = dt_obj_utc.astimezone(pytz.utc)

        # 2. Localize to the target timezone (e.g., Lisbon time)
        tz = pytz.timezone(target_timezone)
        dt_obj_local = dt_obj_utc.astimezone(tz)

        # 3. Extract components for formatting
        weekday = dt_obj_local.strftime('%A') # Full weekday name
        # weeknumber = dt_obj_local.strftime('%W') # Week number of the year (Sunday as first day) # This gave week 00 in Jan-02 2026
        weeknumber = dt_obj_local.isocalendar()[1]  # ISO week number
        year = dt_obj_local.strftime('%Y')    # Full year
        time_str = dt_obj_local.strftime('%H:%M:%S') # Hour:Minute:Second

        # 4. Get current week number for comparison
        # Get current time in the target timezone
        now_local = datetime.now(tz)
        # current_weeknumber = now_local.strftime('%W') # This gave week 00 in Jan-02 2026
        current_weeknumber = now_local.isocalendar()[1]  # ISO week number


        # 5. Assemble the desired string
        formatted_string = (
            f"{weekday}, week {weeknumber}, {year}, Time: {time_str}. "
            f"(current weeknumber: {current_weeknumber})."
        )
        return formatted_string

    except ValueError:
        return f"Invalid date/time format: {iso_timestamp}"
    except pytz.exceptions.UnknownTimeZoneError:
        return f"Invalid timezone specified: {target_timezone}"

# --- Example Usage (for testing this module directly) ---
if __name__ == "__main__":
    test_timestamp_1 = "2025-10-20T19:01:44.200641" # Monday
    test_timestamp_2 = "2023-01-01T12:30:00"      # Sunday, start of a new week
    test_timestamp_3 = "2024-03-15T08:00:00Z"     # With Z for UTC
    test_timestamp_4 = "N/A"
    test_timestamp_5 = "invalid-date"

    print(f"Original: {test_timestamp_1} -> {format_timestamp_for_display(test_timestamp_1)}")
    print(f"Original: {test_timestamp_2} -> {format_timestamp_for_display(test_timestamp_2)}")
    print(f"Original: {test_timestamp_3} -> {format_timestamp_for_display(test_timestamp_3)}")
    print(f"Original: {test_timestamp_4} -> {format_timestamp_for_display(test_timestamp_4)}")
    print(f"Original: {test_timestamp_5} -> {format_timestamp_for_display(test_timestamp_5)}")

    # Example with a different timezone
    print(f"\nUsing 'America/New_York' timezone:")
    print(f"Original: {test_timestamp_1} -> {format_timestamp_for_display(test_timestamp_1, target_timezone='America/New_York')}")


def format_time_only(iso_datetime_string):
    """
    Formats an ISO 8601 datetime string to display only HH:MM.
    """
    try:
        dt_object = datetime.fromisoformat(iso_datetime_string)
        return dt_object.strftime("%H:%M")
    except (ValueError, TypeError):
        return iso_datetime_string