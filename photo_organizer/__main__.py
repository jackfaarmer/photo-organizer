import sys

from .organizer import organize_photos

USAGE = "Usage: photo-organizer <source_dir> <dest_dir> [items_per_directory]"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print(USAGE, file=sys.stderr)
        return 2

    source_dir, dest_dir = argv[0], argv[1]
    items_per_directory = int(argv[2]) if len(argv) > 2 else 1000

    moved = organize_photos(source_dir, dest_dir, items_per_directory)
    print(f"Done. Moved {moved} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
