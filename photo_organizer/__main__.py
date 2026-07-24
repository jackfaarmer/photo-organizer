import argparse
import sys

from .organizer import PLATFORMS, organize_photos


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    parser = argparse.ArgumentParser(
        prog="photo-organizer",
        description=(
            "Sort a directory of photos into numbered subdirectories by creation date."
        ),
    )
    parser.add_argument("source_dir", help="Directory to read files from (non-recursive).")
    parser.add_argument("dest_dir", help="Directory to create the numbered subdirectories in.")
    parser.add_argument(
        "items_per_directory",
        nargs="?",
        type=int,
        default=1000,
        help="Maximum number of files placed in each subdirectory (default: 1000).",
    )
    parser.add_argument(
        "--platform",
        choices=PLATFORMS,
        default=None,
        help=(
            "Filesystem behavior to use for reading/routing files. "
            "Defaults to auto-detecting the host OS."
        ),
    )
    args = parser.parse_args(argv)

    moved = organize_photos(
        args.source_dir,
        args.dest_dir,
        args.items_per_directory,
        platform=args.platform,
    )
    print(f"Done. Moved {moved} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
