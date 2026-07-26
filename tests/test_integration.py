"""End-to-end integration tests: move 100 real images from dir A to dir B,
organized by date, capped at 10 photos per sub-folder."""

import binascii
import os
import struct
import zlib

from photo_organizer import organize_photos, organizer

IMAGE_COUNT = 100
PER_FOLDER = 10
EXPECTED_FOLDERS = IMAGE_COUNT // PER_FOLDER


def _png_bytes():
    """Return the bytes of a minimal valid 1x1 truecolor PNG."""

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", binascii.crc32(tag + data) & 0xFFFFFFFF)
        )

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1, 8-bit, truecolor
    scanline = b"\x00\xff\x00\x00"  # filter byte 0 + one red RGB pixel
    idat = zlib.compress(scanline)
    return signature + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _make_images(directory, count, order=None):
    """Write ``count`` real 1x1 PNG images named ``photo_000.png`` ...

    ``order`` controls the on-disk creation order (defaults to natural order).
    Returns the sorted list of filenames created.
    """
    png = _png_bytes()
    indices = range(count) if order is None else order
    names = []
    for i in indices:
        name = f"photo_{i:03d}.png"
        (directory / name).write_bytes(png)
        names.append(name)
    return sorted(names)


def test_100_real_images_split_into_ten_folders_of_ten(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    created = _make_images(dir_a, IMAGE_COUNT)

    moved = organize_photos(str(dir_a), str(dir_b), items_per_directory=PER_FOLDER)

    assert moved == IMAGE_COUNT
    # Exactly 10 numbered sub-folders, each holding exactly 10 photos.
    # (compare as a set: os.listdir order is arbitrary and "Directory_10"
    # sorts before "Directory_2" lexicographically.)
    folders = os.listdir(dir_b)
    assert set(folders) == {f"Directory_{n}" for n in range(1, EXPECTED_FOLDERS + 1)}
    for folder in folders:
        assert len(os.listdir(dir_b / folder)) == PER_FOLDER

    # Every image landed in B exactly once, and A is left empty (moved, not copied).
    landed = sorted(
        name
        for folder in folders
        for name in os.listdir(dir_b / folder)
    )
    assert landed == created
    assert os.listdir(dir_a) == []


def test_100_images_grouped_strictly_by_date(tmp_path, monkeypatch):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()

    # Create the images in REVERSE order on disk, but give each a creation date
    # equal to its index. Correct date-ordering must regroup them 0-9, 10-19, ...
    _make_images(dir_a, IMAGE_COUNT, order=reversed(range(IMAGE_COUNT)))

    def fake_creation_time(source_path, platform):
        name = os.path.basename(source_path)  # photo_042.png
        return int(name[len("photo_") : -len(".png")])

    monkeypatch.setattr(organizer, "_creation_time", fake_creation_time)

    moved = organize_photos(str(dir_a), str(dir_b), items_per_directory=PER_FOLDER)

    assert moved == IMAGE_COUNT
    for n in range(1, EXPECTED_FOLDERS + 1):
        names = sorted(os.listdir(dir_b / f"Directory_{n}"))
        start = (n - 1) * PER_FOLDER
        expected = [f"photo_{i:03d}.png" for i in range(start, start + PER_FOLDER)]
        assert names == expected


def test_generated_files_are_valid_pngs(tmp_path):
    # Guard the fixture itself: the bytes we write really are PNG images.
    dir_a = tmp_path / "a"
    dir_a.mkdir()
    _make_images(dir_a, 1)
    data = (dir_a / "photo_000.png").read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert data.endswith(b"IEND\xae\x42\x60\x82")
