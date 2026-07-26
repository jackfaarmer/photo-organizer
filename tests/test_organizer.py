import os

import pytest

from photo_organizer import organize_photos, organizer


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


def test_recursive_collects_nested_files(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    (source / "100APPLE").mkdir(parents=True)
    (source / "101APPLE").mkdir(parents=True)
    _make_files(source / "100APPLE", 3)
    _make_files(source / "101APPLE", 4)

    moved = organize_photos(str(source), str(dest), recursive=True)

    assert moved == 7
    assert sorted(os.listdir(dest)) == ["Directory_1"]
    assert len(os.listdir(dest / "Directory_1")) == 7


def test_non_recursive_ignores_nested_files(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    (source / "100APPLE").mkdir(parents=True)
    _make_files(source / "100APPLE", 3)

    # Default (recursive=False) reads only the top level, which has no files.
    moved = organize_photos(str(source), str(dest))

    assert moved == 0
    assert os.listdir(dest) == []
    # Nested files are left untouched.
    assert len(os.listdir(source / "100APPLE")) == 3


def test_recursive_skips_broken_symlinks(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    (source / "100APPLE").mkdir(parents=True)
    _make_files(source / "100APPLE", 2)
    # A broken symlink is listed by os.walk but os.stat would raise on it;
    # the collector must skip it rather than abort the whole run.
    broken = source / "100APPLE" / "dangling.jpg"
    try:
        os.symlink(source / "nonexistent-target.jpg", broken)
    except (OSError, NotImplementedError):
        pytest.skip("platform does not support symlinks")

    moved = organize_photos(str(source), str(dest), recursive=True)

    assert moved == 2
    assert len(os.listdir(dest / "Directory_1")) == 2


def test_recursive_dedupes_colliding_basenames(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    (source / "100APPLE").mkdir(parents=True)
    (source / "101APPLE").mkdir(parents=True)
    first = source / "100APPLE" / "IMG_0001.jpg"
    second = source / "101APPLE" / "IMG_0001.jpg"
    first.write_text("from 100APPLE")
    second.write_text("from 101APPLE")
    # Stagger timestamps so ordering is deterministic (first moved first).
    os.utime(first, (1_600_000_000, 1_600_000_000))
    os.utime(second, (1_600_000_060, 1_600_000_060))

    moved = organize_photos(str(source), str(dest), items_per_directory=1000, recursive=True)

    assert moved == 2
    directory = dest / "Directory_1"
    # Both files survive as two distinct files; nothing is clobbered.
    assert sorted(os.listdir(directory)) == ["IMG_0001.jpg", "IMG_0001_1.jpg"]
    # Ordering is deterministic: the earlier-ctime file keeps the bare name, the
    # later one gets the numeric suffix.
    assert (directory / "IMG_0001.jpg").read_text() == "from 100APPLE"
    assert (directory / "IMG_0001_1.jpg").read_text() == "from 101APPLE"


def test_recursive_skips_nested_mac_junk(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    (source / "100APPLE").mkdir(parents=True)
    _make_files(source / "100APPLE", 3)
    # macOS artifacts nested inside a subfolder must be left behind.
    (source / "100APPLE" / ".DS_Store").write_text("finder metadata")
    (source / "100APPLE" / "._sidecar.jpg").write_text("appledouble sidecar")

    moved = organize_photos(str(source), str(dest), platform="mac", recursive=True)

    assert moved == 3
    assert len(os.listdir(dest / "Directory_1")) == 3
    assert (source / "100APPLE" / ".DS_Store").exists()
    assert (source / "100APPLE" / "._sidecar.jpg").exists()


def test_recursive_collects_files_at_arbitrary_depth(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    deep = source / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    _make_files(source / "a", 1)
    _make_files(deep, 2)

    moved = organize_photos(str(source), str(dest), recursive=True)

    assert moved == 3
    assert sorted(os.listdir(dest)) == ["Directory_1"]
    assert len(os.listdir(dest / "Directory_1")) == 3


def test_unique_dest_path_returns_free_path_unchanged(tmp_path):
    assert organizer._unique_dest_path(str(tmp_path), "IMG_0001.jpg") == str(
        tmp_path / "IMG_0001.jpg"
    )


def test_unique_dest_path_suffixes_on_collision(tmp_path):
    (tmp_path / "IMG_0001.jpg").write_text("existing")
    assert organizer._unique_dest_path(str(tmp_path), "IMG_0001.jpg") == str(
        tmp_path / "IMG_0001_1.jpg"
    )


def test_unique_dest_path_increments_past_first_suffix(tmp_path):
    (tmp_path / "IMG_0001.jpg").write_text("a")
    (tmp_path / "IMG_0001_1.jpg").write_text("b")
    assert organizer._unique_dest_path(str(tmp_path), "IMG_0001.jpg") == str(
        tmp_path / "IMG_0001_2.jpg"
    )


def test_unique_dest_path_handles_extensionless_names(tmp_path):
    (tmp_path / "IMG_0001").write_text("existing")
    assert organizer._unique_dest_path(str(tmp_path), "IMG_0001") == str(
        tmp_path / "IMG_0001_1"
    )


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


def test_invalid_platform_raises(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()

    with pytest.raises(ValueError):
        organize_photos(str(source), str(dest), platform="linux")


def test_mac_skips_macos_junk_files(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    _make_files(source, 3)
    # macOS filesystem artifacts that should be left behind, not organized.
    (source / ".DS_Store").write_text("finder metadata")
    (source / "._photo_000.jpg").write_text("appledouble sidecar")

    moved = organize_photos(str(source), str(dest), platform="mac")

    assert moved == 3
    assert len(os.listdir(dest / "Directory_1")) == 3
    # Junk files remain in the source directory.
    assert (source / ".DS_Store").exists()
    assert (source / "._photo_000.jpg").exists()


def test_pc_does_not_skip_dotfiles(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    _make_files(source, 2)
    (source / ".DS_Store").write_text("treated as a regular file on pc")
    (source / "._photo.jpg").write_text("appledouble sidecar, not skipped on pc")

    moved = organize_photos(str(source), str(dest), platform="pc")

    # On pc there is no macOS junk-file skipping, so all 4 files move.
    assert moved == 4
    assert not (source / ".DS_Store").exists()
    assert not (source / "._photo.jpg").exists()


def test_pc_creation_time_uses_getctime(tmp_path, monkeypatch):
    path = tmp_path / "photo.jpg"
    path.write_text("x")

    monkeypatch.setattr(organizer.os.path, "getctime", lambda p: 999.0)

    assert organizer._creation_time(str(path), "pc") == 999.0


def test_mac_creation_time_prefers_birthtime(tmp_path, monkeypatch):
    path = tmp_path / "photo.jpg"
    path.write_text("x")

    class FakeStat:
        st_birthtime = 12345.0

    monkeypatch.setattr(organizer.os, "stat", lambda p: FakeStat())
    # getctime would return something else; birthtime must win on mac.
    monkeypatch.setattr(organizer.os.path, "getctime", lambda p: 0.0)

    assert organizer._creation_time(str(path), "mac") == 12345.0


def test_mac_creation_time_falls_back_without_birthtime(tmp_path, monkeypatch):
    path = tmp_path / "photo.jpg"
    path.write_text("x")

    class FakeStat:
        pass  # no st_birthtime (e.g. Linux/CI)

    monkeypatch.setattr(organizer.os, "stat", lambda p: FakeStat())
    monkeypatch.setattr(organizer.os.path, "getctime", lambda p: 777.0)

    assert organizer._creation_time(str(path), "mac") == 777.0


def test_platform_defaults_to_host_os():
    assert organizer._normalize_platform(None) in organizer.PLATFORMS


def test_detect_platform_maps_darwin_to_mac(monkeypatch):
    monkeypatch.setattr(organizer.sys, "platform", "darwin")
    assert organizer._normalize_platform(None) == "mac"


def test_detect_platform_maps_non_darwin_to_pc(monkeypatch):
    monkeypatch.setattr(organizer.sys, "platform", "win32")
    assert organizer._normalize_platform(None) == "pc"
