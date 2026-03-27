"""
This script scrapes movie session times for a list of cinemas from https://medeiafilmes.com/cinemas/cinema-medeia-nimas

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

SOURCE_URL = 'https://medeiafilmes.com/cinemas/cinema-medeia-nimas' # Base URL for metadata

# --- NEW GLOBAL DICTIONARY TO STORE SLUG-TO-NAME MAPPING ---
CINEMA_SLUG_TO_NAME_MAP: Dict[str, str] = {}
# --- END NEW GLOBAL DICTIONARY ---

# --- Configuration and Setup ---

# Set up logging to monitor the script's progress
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables from a .env file (if any)
load_dotenv()

# Standard headers to mimic a browser visit
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Referer': 'https://medeiafilmes.com'
}
url = "https://medeiafilmes.com/cinemas/cinema-medeia-nimas"

session = requests.Session()
session.headers.update(headers) # Apply headers to the session

try:
    response = session.get(url)
    response.raise_for_status()
    html_content = response.text
    # ... rest of your parsing code ...
    print("Successfully fetched content using a session.")

    # 2. You can use Beautiful Soup here to parse the HTML
    # (though for your specific JSON extraction, regex might be more direct)
    soup = BeautifulSoup(html_content, 'html.parser')

    # Example: Find the title tag
    title = soup.find('title')
    if title:
        print(f"Page Title: {title.text}")

    # 3. Extract the JSON string using regex from the raw html_content
    # (as Beautiful Soup doesn't directly help with JavaScript variable extraction)
    match = re.search(r"global\.data = (\{.*\});", html_content, re.DOTALL) # re.DOTALL for multiline match
    if match:
        json_string = match.group(1)
        data = json.loads(json_string)
        print("\nExtracted JSON data (partial):")
        print(f"Theater Title: {data['theater']['title']}")
       # print(f"First film in program: {data['date']['2025-11-07']['sessions']['13:00:00']['films'][0]['film_title']}")
    else:
        print("Could not find global.data JSON.")

except requests.exceptions.RequestException as e:
    print(f"Error fetching the URL: {e}")
except json.JSONDecodeError as e:
    print(f"Error decoding JSON: {e}")
except KeyError as e:
    print(f"Error accessing JSON data (key not found): {e}")
'''
def explore_json_schema(data, indent=0, path=""):
    """Recursively explores and prints the schema of a JSON-like object."""
    prefix = "  " * indent
    if isinstance(data, dict):
        print(f"{prefix}{path or 'Root'}: (Object of {len(data)} items)")
        if len(data) > 0:
            # For lists, we usually just show the schema of the first item
            
            for key, value in data.items():
                explore_json_schema(value, indent + 1, f"'{key}'")
        else:
            print(f"{prefix}  - (Empty Array)")
    elif isinstance(data, list):
        print(f"{prefix}{path or 'Root'}: (Array of {len(data)} items)")
        if len(data) > 0:
            # For lists, we usually just show the schema of the first item
            
            explore_json_schema(data[0], indent + 2, "")
        else:
            print(f"{prefix}  - (Empty Array)")
    else:
        # For primitive types (string, int, float, bool, None)
        print(f"{prefix}{path}: ({type(data).__name__})")
'''
def explore_json_schema(data, indent=0, path="", exclude_paths=None):
    """
    Recursively explores and prints the schema of a JSON-like object.
    Excludes detailed content for specified paths to reduce verbosity.

    Args:
        data: The JSON-like object (dict or list).
        indent: Current indentation level for pretty printing.
        path: The current "path" as a string for context (e.g., "Root.programme.sessions").
        exclude_paths: A set of string paths (e.g., {"programme.sessions.films"})
                       for which to skip detailed recursion.
    """
    if exclude_paths is None:
        exclude_paths = set()

    prefix = "  " * indent
    current_full_path = path

    # Check if the current path should be excluded from detailed recursion
    # This assumes 'path' is built in a dot-notation fashion for checks
    for exclude_pattern in exclude_paths:
        if current_full_path.endswith(f".'{exclude_pattern.split('.')[-1]}'") or \
           current_full_path == f"'{exclude_pattern}'":
            # If the current element's key matches the last part of an exclude_pattern
            # and it's a list or dict, we can summarize it.
            if isinstance(data, (dict, list)):
                if isinstance(data, dict):
                    print(f"{prefix}{path}: (Object of {len(data)} items) - Structure details skipped.")
                else: # It's a list
                    print(f"{prefix}{path}: (Array of {len(data)} items) - Structure details skipped.")
                return # Stop further recursion for this path

    if isinstance(data, dict):
        print(f"{prefix}{path or 'Root'}: (Object of {len(data)} items)")
        for key, value in data.items():
            new_path_segment = f"'{key}'"
            explore_json_schema(value, indent + 1, f"{current_full_path}.{new_path_segment}" if current_full_path else new_path_segment, exclude_paths)
    elif isinstance(data, list):
        print(f"{prefix}{path or 'Root'}: (Array of {len(data)} items)")
        if len(data) > 0:
            # For non-empty lists, show the schema of the first item
            print(f"{prefix}  - Item Structure (from first element):")
            # The path for the item itself doesn't need to append the key, as it's an item within a list
            explore_json_schema(data[0], indent + 2, "", exclude_paths)
        else:
            print(f"{prefix}  - (Empty Array)")
    else:
        # For primitive types (string, int, float, bool, None)
        print(f"{prefix}{path}: ({type(data).__name__})")


print("--- JSON Schema Exploration ---")
explore_json_schema(data)

