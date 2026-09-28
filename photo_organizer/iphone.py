"""Copy photos from an iPhone's AFC media directory. SPDX-License-Identifier: MIT"""

import asyncio
import hashlib
import os
import posixpath
import sys
import tempfile
from pathlib import Path

from .organizer import (
    _DIGEST_CHUNK_SIZE,
    _TMP_PREFIX,
    OrganizeResult,
    _file_digest,
    _index_dest_by_size,
    _resume_point,
    _unique_dest_path,
)


def _safe_name(name):
    """Reject device names that could escape a local destination directory."""
    return name not in ("", ".", "..") and "/" not in name and "\\" not in name


async def _collect_files(afc, directory="/DCIM"):
    """List regular media files with their size and device timestamps."""
    files = []
    pending = [directory]
    while pending:
        parent = pending.pop()
        for name in await afc.listdir(parent):
            if not _safe_name(name) or name.startswith("._") or name == ".DS_Store":
                continue
            path = posixpath.join(parent, name)
            info = await afc.stat(path)
            if info.get("st_ifmt") == "S_IFDIR":
                pending.append(path)
            elif info.get("st_ifmt") == "S_IFREG":
                stamp = info.get("st_birthtime") or info.get("st_mtime")
                files.append((path, info["st_size"], stamp.timestamp()))
    files.sort(key=lambda item: (item[2], item[0]))
    return files


async def _remote_digest(afc, path):
    digest = hashlib.sha256()
    handle = await afc.fopen(path, "r")
    try:
        while block := await afc.fread(handle, _DIGEST_CHUNK_SIZE):
            digest.update(block)
    finally:
        await afc.fclose(handle)
    return digest.hexdigest()


async def _is_duplicate(afc, path, size, size_index, digest_cache):
    candidates = size_index.get(size, ())
    if not candidates:
        return False
    source_digest = await _remote_digest(afc, path)
    for candidate in candidates:
        digest = digest_cache.get(candidate)
        if digest is None:
            try:
                digest = _file_digest(candidate)
            except OSError:
                continue
            digest_cache[candidate] = digest
        if digest == source_digest:
            return True
    return False


async def _copy_file(afc, source, destination, expected_size, timestamp):
    """Stream to a temporary file, then publish only a complete copy."""
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(destination), prefix=_TMP_PREFIX)
    try:
        total = 0
        handle = await afc.fopen(source, "r")
        try:
            with os.fdopen(fd, "wb") as output:
                fd = None
                while block := await afc.fread(handle, _DIGEST_CHUNK_SIZE):
                    output.write(block)
                    total += len(block)
        finally:
            await afc.fclose(handle)
        if total != expected_size:
            raise OSError(f"incomplete iPhone read: expected {expected_size} bytes, got {total}")
        os.utime(temporary, (timestamp, timestamp))
        os.replace(temporary, destination)
    except BaseException:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


async def _organize_from_afc(afc, dest_dir, items_per_directory, max_files=None):
    """Import from an already connected AFC service; useful for tests."""
    if items_per_directory < 1:
        raise ValueError("items_per_directory must be at least 1")
    if max_files is not None and max_files < 1:
        raise ValueError("max_files must be at least 1")

    files = await _collect_files(afc)
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    size_index = _index_dest_by_size(dest_dir)
    digest_cache = {}
    directory_count, slots_used = _resume_point(dest_dir, items_per_directory)
    current_dir = os.path.join(dest_dir, f"Directory_{directory_count}")
    copied = skipped = 0
    failures = []

    for source, size, timestamp in files:
        name = posixpath.basename(source)
        try:
            if await _is_duplicate(afc, source, size, size_index, digest_cache):
                skipped += 1
                print(f"Skipped {source} (already in destination)")
                continue
            if slots_used >= items_per_directory:
                directory_count += 1
                current_dir = os.path.join(dest_dir, f"Directory_{directory_count}")
                Path(current_dir).mkdir(parents=True, exist_ok=True)
                slots_used = 0
            destination = _unique_dest_path(current_dir, name)
            await _copy_file(afc, source, destination, size, timestamp)
        except Exception as exc:  # noqa: BLE001 - AFC errors vary; continue with other photos.
            failures.append((source, exc))
            print(f"error: could not copy {source}: {exc}", file=sys.stderr)
            continue
        size_index.setdefault(size, []).append(destination)
        copied += 1
        slots_used += 1
        print(f"Copied {source} to {destination}")
        if max_files is not None and copied >= max_files:
            break

    if skipped:
        print(f"Skipped {skipped} file(s) already present in the destination.")
    if failures:
        print(f"error: {len(failures)} file(s) could not be copied.", file=sys.stderr)
    return OrganizeResult(copied, failures)


async def organize_iphone_photos_async(
    dest_dir, items_per_directory=1000, device=None, max_files=None
):
    """Copy an iPhone's DCIM media into numbered local directories, never deleting on device."""
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.afc import AfcService
    except ImportError as exc:
        raise RuntimeError(
            "iPhone support requires: pip install 'photo-organizer[iphone]'"
        ) from exc

    async with (
        await create_using_usbmux(serial=device) as phone,
        AfcService(lockdown=phone) as afc,
    ):
        return await _organize_from_afc(afc, dest_dir, items_per_directory, max_files)


def organize_iphone_photos(dest_dir, items_per_directory=1000, device=None, max_files=None):
    """Synchronous wrapper for the iPhone importer."""
    return asyncio.run(
        organize_iphone_photos_async(dest_dir, items_per_directory, device, max_files)
    )
