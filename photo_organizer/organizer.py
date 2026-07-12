import os
import shutil
from pathlib import Path


def organize_photos(source_dir, dest_dir, items_per_directory=1000):
    """Move files from ``source_dir`` into ``dest_dir`` split across numbered
    subdirectories (``Directory_1``, ``Directory_2``, ...), ordered by each
    file's creation time.

    Args:
        source_dir: Directory to read files from (non-recursive).
        dest_dir: Directory to create the numbered subdirectories in.
        items_per_directory: Maximum number of files placed in each subdirectory.

    Returns:
        The number of files moved.
    """
    if items_per_directory < 1:
        raise ValueError("items_per_directory must be at least 1")

    # Create destination directory if it doesn't exist
    Path(dest_dir).mkdir(parents=True, exist_ok=True)

    # Collect files (skip sub-directories) paired with their creation time
    files_sorted_by_date = []
    for filename in os.listdir(source_dir):
        source_path = os.path.join(source_dir, filename)
        if not os.path.isfile(source_path):
            continue
        creation_time = os.path.getctime(source_path)
        files_sorted_by_date.append((source_path, creation_time))

    # Sort files by creation date
    files_sorted_by_date.sort(key=lambda x: x[1])

    directory_count = 0
    file_count = 0
    current_sub_dir = None

    for source_path, _creation_time in files_sorted_by_date:
        filename = os.path.basename(source_path)

        # Start a new subdirectory every ``items_per_directory`` files
        if file_count % items_per_directory == 0:
            directory_count += 1
            current_sub_dir = os.path.join(dest_dir, f"Directory_{directory_count}")
            Path(current_sub_dir).mkdir(parents=True, exist_ok=True)

        dest_path = os.path.join(current_sub_dir, filename)
        shutil.move(source_path, dest_path)
        print(f"Moved {filename} to {current_sub_dir}")

        file_count += 1

    return file_count
