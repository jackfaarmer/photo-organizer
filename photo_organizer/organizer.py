import os
import shutil
import sys
from pathlib import Path

MAC = "mac"
PC = "pc"
PLATFORMS = (MAC, PC)

# macOS filesystem artifacts that should never be organized as if they were
# photos: the Finder metadata file and AppleDouble ``._*`` sidecar files.
_MAC_JUNK_NAMES = frozenset({".DS_Store"})
_MAC_JUNK_PREFIXES = ("._",)


def _detect_platform():
    """Return ``"mac"`` on macOS, otherwise ``"pc"``."""
    return MAC if sys.platform == "darwin" else PC


def _normalize_platform(platform):
    """Validate/normalize a platform value, auto-detecting when ``None``."""
    if platform is None:
        return _detect_platform()
    normalized = platform.lower()
    if normalized not in PLATFORMS:
        raise ValueError(f"platform must be one of {PLATFORMS}, got {platform!r}")
    return normalized


def _creation_time(source_path, platform):
    """Return the best-available creation timestamp for ``source_path``.

    On macOS the true birth time is exposed as ``st_birthtime``; ``getctime``
    there is only the inode metadata-change time. On Windows ``getctime`` is the
    real creation time, so it is used directly.
    """
    if platform == MAC:
        birthtime = getattr(os.stat(source_path), "st_birthtime", None)
        if birthtime is not None:
            return birthtime
    return os.path.getctime(source_path)


def _is_mac_junk(filename):
    """Return True for macOS filesystem artifacts that should be skipped."""
    return filename in _MAC_JUNK_NAMES or filename.startswith(_MAC_JUNK_PREFIXES)


def organize_photos(source_dir, dest_dir, items_per_directory=1000, platform=None):
    """Move files from ``source_dir`` into ``dest_dir`` split across numbered
    subdirectories (``Directory_1``, ``Directory_2``, ...), ordered by each
    file's creation time.

    Args:
        source_dir: Directory to read files from (non-recursive).
        dest_dir: Directory to create the numbered subdirectories in.
        items_per_directory: Maximum number of files placed in each subdirectory.
        platform: Filesystem behavior to use, ``"mac"`` or ``"pc"``. Controls how
            each file's creation time is read (macOS uses ``st_birthtime``) and,
            on ``"mac"``, skips macOS junk files (``.DS_Store``, ``._*``).
            Defaults to auto-detecting the host OS.

    Returns:
        The number of files moved.
    """
    if items_per_directory < 1:
        raise ValueError("items_per_directory must be at least 1")

    platform = _normalize_platform(platform)

    # Create destination directory if it doesn't exist
    Path(dest_dir).mkdir(parents=True, exist_ok=True)

    # Collect files (skip sub-directories) paired with their creation time
    files_sorted_by_date = []
    for filename in os.listdir(source_dir):
        source_path = os.path.join(source_dir, filename)
        if not os.path.isfile(source_path):
            continue
        # On macOS, leave Finder/AppleDouble artifacts where they are.
        if platform == MAC and _is_mac_junk(filename):
            continue
        creation_time = _creation_time(source_path, platform)
        files_sorted_by_date.append((source_path, creation_time))

    # Sort files by creation date
    files_sorted_by_date.sort(key=lambda x: x[1])

    directory_count = 0
    file_count = 0
    current_sub_dir = None

    for source_path, _ in files_sorted_by_date:
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
