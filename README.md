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
photo-organizer <source_dir> <dest_dir> [items_per_directory]
```

As a module:

```bash
python -m photo_organizer <source_dir> <dest_dir> [items_per_directory]
```

From Python:

```python
from photo_organizer import organize_photos

organize_photos(
    source_dir=r"D:\Photos From My Phone\iPhone 12",
    dest_dir=r"D:\Photos From My Phone\iPhone 12 Reorg",
    items_per_directory=1000,
)
```

`main.py` is kept as an editable example script — adjust the paths at the
bottom and run `python main.py`.

> **Note:** files are **moved**, not copied. Run against a backup first if
> you are unsure.

## Development

```bash
python -m pip install -e ".[dev]"
pytest        # run the test suite
ruff check .  # lint
```

## License

[MIT](LICENSE)
