import os
import sys

def rel2abs_Filepath(relative_path):
    """
    Converts a relative path to an absolute path,
    assuming the utility file is one level down from the project root.
    """
    # Get the directory where THIS utility file resides (e.g., /path/to/your_project/utils)
    utils_dir = os.path.abspath(os.path.dirname(__file__))

    # Go up one level to get the project root directory
    # (e.g., /path/to/your_project)
    project_root = os.path.dirname(utils_dir)

    # Join the project root with the provided relative_path
    absolute_path = os.path.join(project_root, relative_path)

    # Adjust path separators for the specific OS
    if sys.platform == 'win32':
        absolute_path = absolute_path.replace('/', '\\')
    else:
        absolute_path = absolute_path.replace('\\', '/')

    return absolute_path

# --- Example Usage ---
# Assuming utils/utils_file.py and input/all_movie_data.json
# are structured like this:
# your_project/
# ├── utils/
# │   └── utils_file.py  (where rel2abs_Filepath is defined)
# └── input/
#     └── all_movie_data.json
# └── main_script.py (where you call rel2abs_Filepath)

# In your main script, when calling rel2abs_Filepath:
# all_movie_data_filepath = rel2abs_Filepath('input/all_movie_data.json')
# print(all_movie_data_filepath)