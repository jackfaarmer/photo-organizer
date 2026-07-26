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


def _collect_files(source_dir, platform, recursive):
    """Collect ``(source_path, creation_time)`` tuples from ``source_dir``.

    When ``recursive`` is False, reads only the top level of ``source_dir``
    (skipping sub-directories); when True, walks the tree depth-first and
    collects files at any depth. In both cases macOS junk files are skipped
    when ``platform == MAC``.
    """
    if recursive:
        entries = ((dp, fn) for dp, _dirs, fns in os.walk(source_dir) for fn in fns)
    else:
        entries = ((source_dir, fn) for fn in os.listdir(source_dir))

    collected = []
    for dirpath, filename in entries:
        source_path = os.path.join(dirpath, filename)
        # Skip non-files (e.g. broken symlinks, FIFOs) so ``_creation_time``
        # never stats something that raises.
        if not os.path.isfile(source_path):
            continue
        # On macOS, leave Finder/AppleDouble artifacts where they are.
        if platform == MAC and _is_mac_junk(filename):
            continue
        collected.append((source_path, _creation_time(source_path, platform)))
    return collected


def _unique_dest_path(directory, filename):
    """Return a non-colliding path for ``filename`` inside ``directory``.

    If the path is free it is returned unchanged; otherwise ``_1``, ``_2``, ...
    is inserted between the stem and extension until a free path is found
    (e.g. ``IMG_0001.HEIC`` -> ``IMG_0001_1.HEIC``).
    """
    dest_path = os.path.join(directory, filename)
    if not os.path.exists(dest_path):
        return dest_path
    stem, ext = os.path.splitext(filename)
    counter = 1
    while True:
        candidate = os.path.join(directory, f"{stem}_{counter}{ext}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def organize_photos(
    source_dir, dest_dir, items_per_directory=1000, platform=None, recursive=False, copy=False
):
    """Move (or copy) files from ``source_dir`` into ``dest_dir`` split across
    numbered subdirectories (``Directory_1``, ``Directory_2``, ...), ordered by
    each file's creation time.

    Args:
        source_dir: Directory to read files from (non-recursive by default; set
            ``recursive=True`` to descend into sub-directories).
        dest_dir: Directory to create the numbered subdirectories in.
        items_per_directory: Maximum number of files placed in each subdirectory.
        platform: Filesystem behavior to use, ``"mac"`` or ``"pc"``. Controls how
            each file's creation time is read (macOS uses ``st_birthtime``) and,
            on ``"mac"``, skips macOS junk files (``.DS_Store``, ``._*``).
            Defaults to auto-detecting the host OS.
        recursive: When True, walk ``source_dir`` depth-first and collect files
            at any depth (e.g. ``DCIM/100APPLE/...``); when False (default) only
            the top level is read. Because files from different sub-directories
            can share a basename, any collision in a destination subdirectory is
            resolved by appending a numeric suffix (``IMG_0001.HEIC`` ->
            ``IMG_0001_1.HEIC``) so nothing is clobbered.
        copy: When True, copy each file (``shutil.copy2``, preserving timestamps
            and metadata) and leave the originals in place. When False (default)
            each file is moved (``shutil.move``), which deletes it from the
            source. Use ``copy=True`` for non-destructive imports.

    Returns:
        The number of files moved (or copied).

    Raises:
        ValueError: If ``items_per_directory`` is less than 1, or ``platform``
            is not ``None``, ``"mac"``, or ``"pc"``.
    """
    if items_per_directory < 1:
        raise ValueError("items_per_directory must be at least 1")

    platform = _normalize_platform(platform)

    # Fail consistently for a bad source in both modes: os.walk would otherwise
    # silently yield nothing, making --recursive "succeed" on a missing path.
    if not os.path.isdir(source_dir):
        raise NotADirectoryError(f"source is not a directory: {source_dir!r}")

    # Create destination directory if it doesn't exist
    Path(dest_dir).mkdir(parents=True, exist_ok=True)

    # Collect files paired with their creation time
    files_sorted_by_date = _collect_files(source_dir, platform, recursive)

    # Sort files by creation date
    files_sorted_by_date.sort(key=lambda x: x[1])

    # Choose the transfer once: copy2 preserves the originals (and their
    # timestamps/metadata); move deletes each source after placing it.
    transfer = shutil.copy2 if copy else shutil.move
    verb = "Copied" if copy else "Moved"

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

        # Different sub-directories may hold files with the same basename;
        # give collisions a numeric suffix so nothing is overwritten.
        dest_path = _unique_dest_path(current_sub_dir, filename)
        transfer(source_path, dest_path)
        print(f"{verb} {os.path.basename(dest_path)} to {current_sub_dir}")

        file_count += 1

    return file_count
