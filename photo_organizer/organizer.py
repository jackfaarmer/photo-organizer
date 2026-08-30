import hashlib
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

MAC = "mac"
PC = "pc"
PLATFORMS = (MAC, PC)

# macOS filesystem artifacts that should never be organized as if they were
# photos: the Finder metadata file and AppleDouble ``._*`` sidecar files.
_MAC_JUNK_NAMES = frozenset({".DS_Store"})
_MAC_JUNK_PREFIXES = ("._",)

# Temp files written by ``_atomic_copy2``; the duplicate index skips them.
_TMP_PREFIX = ".photo-organizer-tmp-"

_DIGEST_CHUNK_SIZE = 1024 * 1024

_DIRECTORY_PATTERN = re.compile(r"^Directory_(\d+)$")


class OrganizeResult(int):
    """Count of files transferred; ``failures`` holds ``(path, error)`` pairs."""

    failures = ()

    def __new__(cls, count, failures=()):
        result = super().__new__(cls, count)
        result.failures = tuple(failures)
        return result


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


def _atomic_copy2(source_path, dest_path):
    """Copy ``source_path`` to ``dest_path`` preserving metadata, atomically.

    ``shutil.copy2`` writes straight to the destination, so an interrupted or
    failing copy (a full disk, a pulled drive) leaves a truncated file behind —
    and because copy mode never overwrites, that garbage would sit alongside the
    good files. Copy to a temp file in the same directory first, then
    ``os.replace`` it into place: the destination only ever appears complete,
    and any partial temp file is removed on failure.
    """
    dest_dir = os.path.dirname(dest_path)
    fd, tmp_path = tempfile.mkstemp(dir=dest_dir, prefix=_TMP_PREFIX)
    os.close(fd)
    try:
        shutil.copy2(source_path, tmp_path)
        os.replace(tmp_path, dest_path)
    except BaseException:
        # Clean up the partial temp file on any error or interrupt (e.g.
        # KeyboardInterrupt) so no stray fragments are left in the destination.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _resume_point(dest_dir, items_per_directory):
    """Return ``(directory_number, files_in_it)`` to continue an earlier run.

    Returns ``(0, items_per_directory)`` for a fresh destination, which makes
    the transfer loop open ``Directory_1`` on its first file.
    """
    highest = 0
    for name in os.listdir(dest_dir):
        match = _DIRECTORY_PATTERN.match(name)
        if match and os.path.isdir(os.path.join(dest_dir, name)):
            highest = max(highest, int(match.group(1)))
    if highest == 0:
        return 0, items_per_directory

    last = os.path.join(dest_dir, f"Directory_{highest}")
    used = sum(
        1
        for entry in os.listdir(last)
        if not entry.startswith(_TMP_PREFIX) and os.path.isfile(os.path.join(last, entry))
    )
    return highest, used


def _file_digest(path):
    """Return the SHA-256 hex digest of ``path``, streamed to bound memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(_DIGEST_CHUNK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def _index_dest_by_size(dest_dir):
    """Return ``{size: [path, ...]}`` for ``dest_dir``, a stat-only duplicate index."""
    index = {}
    for dirpath, _dirs, filenames in os.walk(dest_dir):
        for filename in filenames:
            if filename.startswith(_TMP_PREFIX):
                continue
            path = os.path.join(dirpath, filename)
            try:
                size = os.path.getsize(path)
            except OSError:
                # Broken symlink or vanished mid-walk; nothing can match it.
                continue
            index.setdefault(size, []).append(path)
    return index


def _is_duplicate(source_path, size_index, digest_cache):
    """Return True when ``source_path``'s content is already in the destination.

    Compares content, not filenames, and only hashes on a size collision.
    """
    candidates = size_index.get(os.path.getsize(source_path))
    if not candidates:
        return False
    source_digest = _file_digest(source_path)
    for candidate in candidates:
        digest = digest_cache.get(candidate)
        if digest is None:
            try:
                digest = _file_digest(candidate)
            except OSError:
                # Unreadable destination file: non-match beats aborting the run.
                continue
            digest_cache[candidate] = digest
        if digest == source_digest:
            return True
    return False


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

            Copy mode is idempotent: source files whose content is already in
            ``dest_dir`` are skipped, so a repeated or interrupted import can be
            re-run safely. Move mode is unaffected.

    Returns:
        An ``OrganizeResult`` (an ``int`` of the files actually transferred)
        whose ``failures`` holds ``(path, error)`` for each file that could not
        be transferred. Skipped duplicates are not counted.

        Numbering resumes from any existing ``Directory_N``, filling a partial
        one before opening the next, so repeated runs respect
        ``items_per_directory``. A file that fails to transfer is reported and
        skipped; the rest of the run continues.

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

    # Copy mode only; move mode keeps its existing behavior (see issue #6).
    size_index = _index_dest_by_size(dest_dir) if copy else {}
    digest_cache = {}

    # Collect files paired with their creation time
    files_sorted_by_date = _collect_files(source_dir, platform, recursive)

    # Sort files by creation date
    files_sorted_by_date.sort(key=lambda x: x[1])

    # Choose the transfer once: copy preserves the originals (and their
    # timestamps/metadata) and lands each file atomically; move deletes each
    # source after placing it.
    transfer = _atomic_copy2 if copy else shutil.move
    verb = "Copied" if copy else "Moved"

    # Resume an earlier run's numbering instead of restarting at Directory_1.
    directory_count, slots_used = _resume_point(dest_dir, items_per_directory)
    current_sub_dir = (
        os.path.join(dest_dir, f"Directory_{directory_count}") if directory_count else None
    )
    file_count = 0
    skipped_count = 0
    failures = []

    for source_path, _ in files_sorted_by_date:
        filename = os.path.basename(source_path)

        # Guarded as one unit: the duplicate check reads the source to hash it,
        # so it fails on exactly the files the transfer would fail on.
        try:
            # Skips do not increment file_count, so they consume no split slot.
            if copy and _is_duplicate(source_path, size_index, digest_cache):
                skipped_count += 1
                print(f"Skipped {filename} (already in destination)")
                continue

            if slots_used >= items_per_directory:
                directory_count += 1
                current_sub_dir = os.path.join(dest_dir, f"Directory_{directory_count}")
                Path(current_sub_dir).mkdir(parents=True, exist_ok=True)
                slots_used = 0

            # Different sub-directories may hold files with the same basename;
            # give collisions a numeric suffix so nothing is overwritten.
            dest_path = _unique_dest_path(current_sub_dir, filename)
            transfer(source_path, dest_path)
        except OSError as exc:
            failures.append((source_path, exc))
            print(f"error: could not transfer {filename}: {exc}", file=sys.stderr)
            continue
        print(f"{verb} {os.path.basename(dest_path)} to {current_sub_dir}")

        if copy:
            # Registered so identical files later in this same run also skip.
            size_index.setdefault(os.path.getsize(dest_path), []).append(dest_path)

        slots_used += 1
        file_count += 1

    if skipped_count:
        print(f"Skipped {skipped_count} file(s) already present in the destination.")
    if failures:
        print(f"error: {len(failures)} file(s) could not be transferred.", file=sys.stderr)

    return OrganizeResult(file_count, failures)
