# photo-organizer

A small utility that moves a flat directory of photos into numbered
subdirectories (`Directory_1`, `Directory_2`, …), ordered by each file's
creation time and capped at a configurable number of files per subdirectory.

## Installation

### Global install (recommended)

[pipx](https://pipx.pypa.io) installs the tool into its own isolated
environment and puts the `photo-organizer` command on your PATH for you:

```bash
python -m pip install --user pipx
python -m pipx ensurepath
pipx install .
```

Open a new terminal afterwards (`ensurepath` only affects shells started
after it runs). `photo-organizer` is then available from any directory, and
this repository is no longer needed — pipx copied the package out.

Plain pip works too, if you would rather not add pipx:

```bash
python -m pip install .
```

Note there is no `-e`: that copies the package into `site-packages` rather
than linking back to this checkout, so you can move or delete the repo
afterwards. You are responsible for the PATH step yourself — see below.

### Updating an installed copy

```bash
git pull
pipx install --force .             # standard installation
pipx install --force '.[iphone]'    # use this instead for direct iPhone import
```

`--force` matters. `pipx upgrade` and `pip install --upgrade .` compare version
numbers and do nothing when the version is unchanged, so a same-version rebuild
silently leaves you on the old code. `--force` rebuilds unconditionally.

To install (and update) straight from GitHub without keeping a checkout:

```bash
pipx install --force git+https://github.com/jackfaarmer/photo-organizer.git
```

### Windows: `command not found` after installing

`pip` installs the launcher as `photo-organizer.exe` in your Python
installation's **Scripts** directory, which is frequently not on PATH. pip
prints a warning about this during install, but it is easy to miss. Locate
the directory with:

```bash
python -c "import sysconfig; print(sysconfig.get_path('scripts'))"
```

(For a `--user` install, pass `'scripts', 'nt_user'` instead.) Add that path
to your account's `Path` environment variable and open a new terminal.

To skip PATH configuration entirely, invoke the package as a module — it is
the same entry point and accepts identical arguments:

```bash
python -m photo_organizer <source_dir> <dest_dir>
```

If `python` and `py` point at different Python installations, install and run
with the same one (`py -m pip install .` then `py -m photo_organizer`), or the
launcher will land in an interpreter you are not invoking.

### Editable install (for working on the code)

```bash
python -m pip install -e .
```

This links back to the checkout so edits take effect immediately, but it means
the repository must stay where it is. See [Development](#development).

## Usage

### Import directly from an iPhone

Install the optional device dependency, connect and unlock the iPhone, and tap
**Trust** if prompted:

```bash
pipx install --force '.[iphone]'   # from this checkout; includes pymobiledevice3
photo-organizer iphone /path/to/destination
```

For a plain pip installation, use `python -m pip install '.[iphone]'` instead.
The standard `pipx install .` installs the directory-only tool without this
optional dependency.

This copies files from the phone's `/DCIM` media directory into the same
`Directory_N` layout as the directory command. It never moves or deletes files
on the phone. It sorts by the device's file creation timestamp, falling back to
modification time; this is not yet EXIF capture-date sorting. It preserves
modification timestamps, skips content duplicates on rerun, and publishes each
local file only after a complete transfer. `--items-per-directory N` changes
the folder cap, `--device UDID` selects a specific connected phone, and
`--max-files N` limits the number of successful copies for a trial run.

From Python, use `organize_iphone_photos(destination)` or its async counterpart
`organize_iphone_photos_async(destination)`; neither requires the optional
dependency until called. On Windows, install Apple Mobile Device Support. On
Linux, install and run `usbmuxd`. Full-size media stored only in iCloud is not
available through the phone's local `/DCIM` directory.

The core photo-organizer code remains MIT licensed. The optional
`pymobiledevice3` dependency is GPL-3.0-or-later; distributing a combined
application that imports it must comply with its GPL terms. The MIT license on
the core code does not remove those terms for the combined application.

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

### Re-running an import

Numbering resumes from whatever the destination already holds. An existing
`Directory_N` that is not yet full is topped up to `items_per_directory` before
the next one is opened, so repeated imports keep the cap instead of piling
everything back into `Directory_1`. Only `Directory_<number>` folders take part
— anything else you keep alongside them is ignored.

A file that cannot be transferred (locked, unreadable, a full disk) is reported
on stderr and skipped; the run continues and the remaining files still land.
The command exits `1` when anything failed, and the final `Done.` line counts
only the files that actually transferred. Nothing is overwritten in either
mode: a name collision in the destination gets a numeric suffix
(`IMG_0001.jpg` → `IMG_0001_1.jpg`).

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

Copy mode is **idempotent**: any source file whose content is already in the
destination is skipped rather than copied again, so an interrupted or repeated
import can simply be re-run, and pointing a later import at the same
destination brings over only the genuinely new photos.

Duplicates are matched by **content**, not filename — a photo you renamed in
the destination after an earlier import is still recognized. Detection is
cheap: the destination is indexed by file size, and a SHA-256 is computed only
when a source file's size actually collides with something already there, so an
import with nothing to skip never reads the destination's image data.

Two consequences worth knowing:

- Byte-identical files **within a single source** also collapse to one copy.
  Real photos differ, but exact duplicates you were carrying deliberately will
  not survive the import.
Note also that `copy2` follows symlinks (copying the target's contents),
whereas move relocates the link itself. Duplicate-skipping applies to copy mode
only: a move is a request to empty the source, so move mode always transfers,
giving any name collision a numeric suffix.

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
