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
    parser.add_argument(
        "source_dir", help="Directory to read files from (top-level only by default)."
    )
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
        type=str.lower,
        default=None,
        help=(
            "Filesystem behavior to use for reading/routing files. "
            "Defaults to auto-detecting the host OS."
        ),
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help=(
            "Recurse into sub-directories of source_dir, collecting files at any "
            "depth (default: read only the top level)."
        ),
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help=(
            "Copy files (preserving the originals) instead of moving them. "
            "The default is to MOVE, which deletes each file from the source; "
            "use --copy for a non-destructive import."
        ),
    )
    args = parser.parse_args(argv)

    try:
        count = organize_photos(
            args.source_dir,
            args.dest_dir,
            args.items_per_directory,
            platform=args.platform,
            recursive=args.recursive,
            copy=args.copy,
        )
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    verb = "Copied" if args.copy else "Moved"
    print(f"Done. {verb} {count} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
