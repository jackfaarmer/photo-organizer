import os

import pytest

from photo_organizer import organize_photos


def _make_files(directory, count):
    """Create ``count`` files with staggered modification/creation times."""
    paths = []
    for i in range(count):
        path = directory / f"photo_{i:03d}.jpg"
        path.write_text(f"content {i}")
        # Stagger timestamps so ordering by ctime/mtime is deterministic.
        ts = 1_600_000_000 + i * 60
        os.utime(path, (ts, ts))
        paths.append(path)
    return paths


def test_moves_all_files_into_single_directory(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    _make_files(source, 5)

    moved = organize_photos(str(source), str(dest), items_per_directory=1000)

    assert moved == 5
    assert sorted(os.listdir(dest)) == ["Directory_1"]
    assert len(os.listdir(dest / "Directory_1")) == 5
    # Source files were moved, not copied.
    assert os.listdir(source) == []


def test_splits_across_directories(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    _make_files(source, 5)

    moved = organize_photos(str(source), str(dest), items_per_directory=2)

    assert moved == 5
    # 5 files, 2 per dir -> Directory_1(2), Directory_2(2), Directory_3(1)
    assert sorted(os.listdir(dest)) == ["Directory_1", "Directory_2", "Directory_3"]
    assert len(os.listdir(dest / "Directory_1")) == 2
    assert len(os.listdir(dest / "Directory_2")) == 2
    assert len(os.listdir(dest / "Directory_3")) == 1


def test_creates_destination_if_missing(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "nested" / "dst"
    source.mkdir()
    _make_files(source, 1)

    organize_photos(str(source), str(dest))

    assert dest.is_dir()


def test_ignores_subdirectories_in_source(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    (source / "a_subdir").mkdir()
    _make_files(source, 3)

    moved = organize_photos(str(source), str(dest), items_per_directory=1000)

    assert moved == 3
    assert (source / "a_subdir").is_dir()


def test_empty_source_creates_no_subdirectories(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()

    moved = organize_photos(str(source), str(dest))

    assert moved == 0
    assert os.listdir(dest) == []


def test_invalid_items_per_directory_raises(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()

    with pytest.raises(ValueError):
        organize_photos(str(source), str(dest), items_per_directory=0)
