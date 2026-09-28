import hashlib
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


def test_copy_mode_preserves_source_files(tmp_path, capsys):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    originals = _make_files(source, 5)

    copied = organize_photos(str(source), str(dest), items_per_directory=1000, copy=True)

    assert copied == 5
    assert len(os.listdir(dest / "Directory_1")) == 5
    # copy=True leaves every source file in place, untouched.
    assert sorted(os.listdir(source)) == sorted(p.name for p in originals)
    # The copies are faithful: source and destination bytes match.
    for original in originals:
        copied_file = dest / "Directory_1" / original.name
        assert copied_file.read_text() == original.read_text()
    # Per-file progress lines use the "Copied" verb (not "Moved").
    out = capsys.readouterr().out
    assert "Copied " in out
    assert "Moved " not in out


def test_copy_mode_splits_across_directories_and_preserves_source(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    originals = _make_files(source, 5)

    # copy mode shares the split loop with move mode; exercise a real split.
    copied = organize_photos(str(source), str(dest), items_per_directory=2, copy=True)

    assert copied == 5
    # 5 files, 2 per dir -> Directory_1(2), Directory_2(2), Directory_3(1).
    assert sorted(os.listdir(dest)) == ["Directory_1", "Directory_2", "Directory_3"]
    # Every original remains in the source across the split.
    assert sorted(os.listdir(source)) == sorted(p.name for p in originals)


def test_copy_mode_cleans_up_partial_file_on_failure(tmp_path, monkeypatch):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    _make_files(source, 1)

    def boom(*args, **kwargs):
        raise OSError("simulated disk full")

    # Simulate a copy failing midway (e.g. the disk filling up).
    monkeypatch.setattr(organizer.shutil, "copy2", boom)

    result = organize_photos(str(source), str(dest), copy=True)

    # The failure is recorded rather than aborting the run, and the copy is
    # atomic: no truncated file and no leftover temp file remain.
    assert result == 0
    assert len(result.failures) == 1
    assert os.listdir(dest / "Directory_1") == []


def test_copy_mode_retains_timestamps(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    (path,) = _make_files(source, 1)
    expected_mtime = os.stat(path).st_mtime

    organize_photos(str(source), str(dest), items_per_directory=1000, copy=True)

    copied = dest / "Directory_1" / path.name
    # copy2 preserves the original modification time.
    assert os.stat(copied).st_mtime == expected_mtime


def test_copy_mode_is_idempotent_on_rerun(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    originals = _make_files(source, 5)

    first = organize_photos(str(source), str(dest), items_per_directory=1000, copy=True)
    second = organize_photos(str(source), str(dest), items_per_directory=1000, copy=True)

    assert first == 5
    assert second == 0
    assert len(os.listdir(dest / "Directory_1")) == 5
    # No suffixed duplicates (photo_000_1.jpg) were created.
    assert sorted(os.listdir(dest / "Directory_1")) == sorted(p.name for p in originals)
    assert sorted(os.listdir(source)) == sorted(p.name for p in originals)


def test_copy_mode_rerun_imports_only_new_files(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    _make_files(source, 5)

    organize_photos(str(source), str(dest), items_per_directory=1000, copy=True)

    # Two new photos arrive after the first import.
    for i in (5, 6):
        path = source / f"photo_{i:03d}.jpg"
        path.write_text(f"content {i}")
        ts = 1_600_000_000 + i * 60
        os.utime(path, (ts, ts))

    copied = organize_photos(str(source), str(dest), items_per_directory=1000, copy=True)

    assert copied == 2
    landed = [name for folder in os.listdir(dest) for name in os.listdir(dest / folder)]
    assert len(landed) == 7


def test_copy_mode_recognizes_renamed_destination_file(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    _make_files(source, 1)

    organize_photos(str(source), str(dest), copy=True)
    # Matching is on content, so a renamed import is still recognized.
    (dest / "Directory_1" / "photo_000.jpg").rename(dest / "Directory_1" / "vacation.jpg")

    copied = organize_photos(str(source), str(dest), copy=True)

    assert copied == 0
    assert os.listdir(dest / "Directory_1") == ["vacation.jpg"]


def test_copy_mode_imports_same_size_files_with_different_content(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    # Equal sizes, different bytes: size alone must not declare a duplicate.
    (source / "a.jpg").write_text("AAAA")
    (source / "b.jpg").write_text("BBBB")

    copied = organize_photos(str(source), str(dest), copy=True)

    assert copied == 2
    assert sorted(os.listdir(dest / "Directory_1")) == ["a.jpg", "b.jpg"]


def test_copy_mode_collapses_duplicates_within_one_run(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    # The same photo twice under different names.
    (source / "IMG_0001.jpg").write_text("same bytes")
    (source / "IMG_0001_copy.jpg").write_text("same bytes")

    copied = organize_photos(str(source), str(dest), copy=True)

    assert copied == 1
    assert len(os.listdir(dest / "Directory_1")) == 1


def test_copy_mode_reports_skipped_count(tmp_path, capsys):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    _make_files(source, 3)

    organize_photos(str(source), str(dest), copy=True)
    capsys.readouterr()  # discard first-run output
    organize_photos(str(source), str(dest), copy=True)

    out = capsys.readouterr().out
    assert "already in destination" in out
    assert "Skipped 3 file(s) already present in the destination." in out


def test_copy_mode_does_not_hash_when_no_size_matches(tmp_path, monkeypatch):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    # Distinct sizes, so the pre-filter alone settles every file.
    for i in range(4):
        (source / f"photo_{i}.jpg").write_text("x" * (i + 1))

    def boom(path):
        raise AssertionError(f"hashed {path} despite no size collision")

    monkeypatch.setattr(organizer, "_file_digest", boom)

    assert organize_photos(str(source), str(dest), copy=True) == 4


def test_move_mode_rerun_behavior_is_unchanged(tmp_path):
    """Pin move mode's current (unfixed) re-run behavior; see issue #6."""
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    _make_files(source, 2)

    organize_photos(str(source), str(dest), items_per_directory=1000)
    _make_files(source, 2)
    moved = organize_photos(str(source), str(dest), items_per_directory=1000)

    # Move mode does not skip duplicates; idempotency is copy-mode only.
    assert moved == 2
    assert len(os.listdir(dest / "Directory_1")) == 4


def test_index_dest_by_size_groups_paths_by_size(tmp_path):
    (tmp_path / "a.jpg").write_text("xx")
    (tmp_path / "b.jpg").write_text("yy")
    (tmp_path / "c.jpg").write_text("zzz")

    index = organizer._index_dest_by_size(str(tmp_path))

    assert sorted(index) == [2, 3]
    assert sorted(os.path.basename(p) for p in index[2]) == ["a.jpg", "b.jpg"]
    assert [os.path.basename(p) for p in index[3]] == ["c.jpg"]


def test_index_dest_by_size_walks_nested_directories(tmp_path):
    (tmp_path / "Directory_1").mkdir()
    (tmp_path / "Directory_1" / "a.jpg").write_text("xx")

    index = organizer._index_dest_by_size(str(tmp_path))

    assert [os.path.basename(p) for p in index[2]] == ["a.jpg"]


def test_index_dest_by_size_ignores_temp_files(tmp_path):
    # A crashed run's fragment must never mask a real photo.
    (tmp_path / f"{organizer._TMP_PREFIX}abc123").write_text("partial")

    assert organizer._index_dest_by_size(str(tmp_path)) == {}


def test_index_dest_by_size_of_empty_destination(tmp_path):
    assert organizer._index_dest_by_size(str(tmp_path)) == {}


def test_file_digest_matches_hashlib(tmp_path):
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"some image bytes")

    assert organizer._file_digest(str(path)) == hashlib.sha256(b"some image bytes").hexdigest()


def test_file_digest_streams_large_files(tmp_path):
    # Spans several read chunks.
    payload = b"z" * (organizer._DIGEST_CHUNK_SIZE * 2 + 7)
    path = tmp_path / "big.jpg"
    path.write_bytes(payload)

    assert organizer._file_digest(str(path)) == hashlib.sha256(payload).hexdigest()


def test_is_duplicate_skips_hashing_on_size_miss(tmp_path, monkeypatch):
    path = tmp_path / "photo.jpg"
    path.write_text("abc")

    def boom(_path):
        raise AssertionError("hashed despite a size miss")

    monkeypatch.setattr(organizer, "_file_digest", boom)

    assert organizer._is_duplicate(str(path), {99: ["/nonexistent"]}, {}) is False


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


def test_rerun_fills_partial_directory_before_opening_the_next(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    _make_files(source, 2)

    organize_photos(str(source), str(dest), items_per_directory=4)
    _make_files(source, 2)
    organize_photos(str(source), str(dest), items_per_directory=4)

    # Directory_1 had 2 of 4 slots used; the re-run tops it up rather than
    # restarting numbering and blowing past the cap.
    assert sorted(os.listdir(dest)) == ["Directory_1"]
    assert len(os.listdir(dest / "Directory_1")) == 4


def test_rerun_opens_next_directory_when_last_is_full(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    _make_files(source, 2)

    organize_photos(str(source), str(dest), items_per_directory=2)
    _make_files(source, 3)
    organize_photos(str(source), str(dest), items_per_directory=2)

    assert sorted(os.listdir(dest)) == ["Directory_1", "Directory_2", "Directory_3"]
    assert len(os.listdir(dest / "Directory_1")) == 2
    assert len(os.listdir(dest / "Directory_2")) == 2
    assert len(os.listdir(dest / "Directory_3")) == 1


def test_rerun_never_exceeds_items_per_directory(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()

    for _ in range(4):
        _make_files(source, 3)
        organize_photos(str(source), str(dest), items_per_directory=5)

    counts = [len(os.listdir(dest / d)) for d in os.listdir(dest)]
    assert sum(counts) == 12
    assert max(counts) <= 5


def test_resume_numbering_ignores_unrelated_directories(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    dest.mkdir()
    (dest / "Vacation").mkdir()
    (dest / "Directory_notanumber").mkdir()
    _make_files(source, 1)

    organize_photos(str(source), str(dest), items_per_directory=2)

    # Only Directory_<int> participates in numbering.
    assert (dest / "Directory_1").is_dir()
    assert len(os.listdir(dest / "Directory_1")) == 1


def test_resume_point_reports_last_directory_and_fill(tmp_path):
    (tmp_path / "Directory_1").mkdir()
    (tmp_path / "Directory_2").mkdir()
    (tmp_path / "Directory_2" / "a.jpg").write_text("a")

    assert organizer._resume_point(str(tmp_path), 10) == (2, 1)


def test_resume_point_on_empty_destination(tmp_path):
    # (0, cap) makes the transfer loop open Directory_1 on its first file.
    assert organizer._resume_point(str(tmp_path), 10) == (0, 10)


def test_resume_point_ignores_temp_files_when_counting(tmp_path):
    (tmp_path / "Directory_1").mkdir()
    (tmp_path / "Directory_1" / f"{organizer._TMP_PREFIX}xyz").write_text("partial")

    assert organizer._resume_point(str(tmp_path), 10) == (1, 0)


def test_failed_transfer_does_not_abort_the_run(tmp_path, monkeypatch):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    _make_files(source, 5)
    doomed = str(source / "photo_002.jpg")
    real_move = organizer.shutil.move

    def flaky(src, dst):
        if src == doomed:
            raise OSError("simulated locked file")
        return real_move(src, dst)

    monkeypatch.setattr(organizer.shutil, "move", flaky)

    result = organize_photos(str(source), str(dest), items_per_directory=1000)

    # The other four still transfer; only the locked file is left behind.
    assert result == 4
    assert len(result.failures) == 1
    assert result.failures[0][0] == doomed
    assert os.listdir(source) == ["photo_002.jpg"]
    assert len(os.listdir(dest / "Directory_1")) == 4


def test_failed_transfer_consumes_no_directory_slot(tmp_path, monkeypatch):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    _make_files(source, 4)
    real_move = organizer.shutil.move

    def flaky(src, dst):
        if os.path.basename(src) == "photo_001.jpg":
            raise OSError("simulated locked file")
        return real_move(src, dst)

    monkeypatch.setattr(organizer.shutil, "move", flaky)

    result = organize_photos(str(source), str(dest), items_per_directory=2)

    # 3 files landed; a failure must not leave a hole in the 2-per-dir split.
    assert result == 3
    assert len(os.listdir(dest / "Directory_1")) == 2
    assert len(os.listdir(dest / "Directory_2")) == 1


def test_failure_is_reported_on_stderr(tmp_path, monkeypatch, capsys):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    _make_files(source, 1)

    def boom(*args, **kwargs):
        raise OSError("simulated locked file")

    monkeypatch.setattr(organizer.shutil, "move", boom)

    organize_photos(str(source), str(dest))

    err = capsys.readouterr().err
    assert "could not transfer photo_000.jpg" in err
    assert "1 file(s) could not be transferred." in err


def test_unreadable_source_in_copy_mode_does_not_abort_the_run(tmp_path, monkeypatch):
    """The duplicate check reads the source, so it must be guarded too."""
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    # Equal sizes force _is_duplicate to hash, which is where the read happens;
    # distinct bytes keep them from being genuine duplicates.
    for name, body in (("a.jpg", "aaaaaaa"), ("b.jpg", "bbbbbbb"), ("c.jpg", "ccccccc")):
        (source / name).write_text(body)

    real_digest = organizer._file_digest

    def flaky(path):
        if os.path.basename(path) == "b.jpg":
            raise PermissionError(13, "Permission denied")
        return real_digest(path)

    monkeypatch.setattr(organizer, "_file_digest", flaky)

    result = organize_photos(str(source), str(dest), copy=True)

    assert result == 2
    assert len(result.failures) == 1
    assert os.path.basename(result.failures[0][0]) == "b.jpg"


def test_move_mode_does_not_overwrite_existing_destination_file(tmp_path):
    """Regression guard for #6: a name collision must never clobber."""
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    (dest / "Directory_1").mkdir(parents=True)
    (dest / "Directory_1" / "photo_000.jpg").write_text("precious original")
    _make_files(source, 1)

    organize_photos(str(source), str(dest), items_per_directory=1000)

    assert (dest / "Directory_1" / "photo_000.jpg").read_text() == "precious original"
    assert sorted(os.listdir(dest / "Directory_1")) == ["photo_000.jpg", "photo_000_1.jpg"]


def test_organize_result_behaves_as_an_int(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    _make_files(source, 3)

    result = organize_photos(str(source), str(dest))

    assert result == 3
    assert result + 1 == 4
    assert result.failures == ()


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


def test_recursive_dedupes_colliding_basenames(tmp_path, monkeypatch):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    (source / "100APPLE").mkdir(parents=True)
    (source / "101APPLE").mkdir(parents=True)
    first = source / "100APPLE" / "IMG_0001.jpg"
    second = source / "101APPLE" / "IMG_0001.jpg"
    first.write_text("from 100APPLE")
    second.write_text("from 101APPLE")
    # This test exercises collision handling. On Linux, os.utime changes mtime
    # but not creation time, so use the staged mtime for deterministic ordering.
    os.utime(first, (1_600_000_000, 1_600_000_000))
    os.utime(second, (1_600_000_060, 1_600_000_060))
    monkeypatch.setattr(organizer, "_creation_time", lambda path, platform: os.path.getmtime(path))

    moved = organize_photos(str(source), str(dest), items_per_directory=1000, recursive=True)

    assert moved == 2
    directory = dest / "Directory_1"
    # Both files survive as two distinct files; nothing is clobbered.
    assert sorted(os.listdir(directory)) == ["IMG_0001.jpg", "IMG_0001_1.jpg"]
    # Ordering is deterministic: the earlier file keeps the bare name, the
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
