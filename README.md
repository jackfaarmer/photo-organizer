# photo-organizer

A small utility that moves a flat directory of photos into numbered
subdirectories (`Directory_1`, `Directory_2`, …), ordered by each file's
creation time and capped at a configurable number of files per subdirectory.

## Installation

```bash
python -m pip install -e .
```

## Usage

As a command (after installing):

```bash
photo-organizer <source_dir> <dest_dir> [items_per_directory] [--platform mac|pc] [--recursive] [--copy]
```

As a module:

```bash
python -m photo_organizer <source_dir> <dest_dir> [items_per_directory] [--platform mac|pc] [--recursive] [--copy]
```

From Python:

```python
from photo_organizer import organize_photos

organize_photos(
    source_dir=r"D:\Photos From My Phone\iPhone 12",
    dest_dir=r"D:\Photos From My Phone\iPhone 12 Reorg",
    items_per_directory=1000,
    platform="pc",  # or "mac"; omit to auto-detect the host OS.
    recursive=False,  # set True to descend into sub-directories.
    copy=False,  # set True to copy (preserve originals) instead of moving.
)
```

The source directory is read non-recursively by default, and the destination
directory is created automatically if it does not already exist.

`main.py` is kept as an editable example script — adjust the paths at the
bottom and run `python main.py`.

### Platform handling (`--platform`)

"Creation time" is not portable, so the organizer needs to know which
filesystem it is running on:

- **`pc`** — reads Windows creation time via `os.path.getctime`.
- **`mac`** — reads the true birth time via `st_birthtime` (macOS's
  `getctime` is only the metadata-change time), and skips macOS filesystem
  junk (`.DS_Store` and AppleDouble `._*` sidecar files) so they are not
  organized as photos.

When `--platform` is omitted, the host OS is auto-detected (macOS → `mac`,
everything else → `pc`). Note that on Linux `pc`'s `getctime` returns the
inode metadata-change time, not a true creation time.

### Recursive scanning (`--recursive`)

By default only the top level of `source_dir` is read. Pass `--recursive` to
walk the tree and collect files at any depth (e.g. a camera's
`DCIM/100APPLE/…`, `DCIM/101APPLE/…` layout). Because files from different
sub-folders can share a basename, any collision in a destination subdirectory
is resolved by appending a numeric suffix (`IMG_0001.HEIC` →
`IMG_0001_1.HEIC`) so nothing is clobbered.

### Copy mode (`--copy`)

By default files are **moved** (`shutil.move`), which deletes each one from the
source once it lands in the destination. Pass `--copy` (or `copy=True`) to
**copy** files instead (`shutil.copy2`, preserving timestamps and metadata),
leaving every original in place. This is the safe choice for importing an
irreplaceable library — a wrong path or an interrupted run can't lose photos.

Because the originals stay put, copy mode is **not** idempotent: re-running
`--copy` into the same destination re-copies every source file, and the
collision handling gives the second batch numeric suffixes (`IMG_0001_1.HEIC`,
…) rather than skipping duplicates. Point each import at a fresh destination.
Note also that `copy2` follows symlinks (copying the target's contents),
whereas move relocates the link itself.

> **Warning:** the default **move** mode is destructive — it removes files from
> the source. Use `--copy` for a non-destructive import, or run against a
> backup first if you are unsure.

## Development

```bash
python -m pip install -e ".[dev]"
pytest        # run the test suite
ruff check .  # lint
```

## License

[MIT](LICENSE)
