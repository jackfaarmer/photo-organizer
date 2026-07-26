"""Tests for the argparse CLI (`photo_organizer.__main__:main`)."""

import os

import pytest

from photo_organizer.__main__ import main


def _make_files(directory, count):
    for i in range(count):
        (directory / f"photo_{i}.jpg").write_text(f"content {i}")


def test_main_organizes_files(tmp_path, capsys):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    _make_files(source, 3)

    rc = main([str(source), str(dest), "2"])

    assert rc == 0
    assert "Moved 3 file(s)" in capsys.readouterr().out
    # items_per_directory=2 -> Directory_1(2), Directory_2(1)
    assert len(os.listdir(dest / "Directory_1")) == 2
    assert len(os.listdir(dest / "Directory_2")) == 1


def test_main_default_items_per_directory(tmp_path, capsys):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    _make_files(source, 4)

    rc = main([str(source), str(dest)])

    assert rc == 0
    # Default cap (1000) -> everything lands in a single directory.
    assert os.listdir(dest) == ["Directory_1"]
    assert len(os.listdir(dest / "Directory_1")) == 4


def test_main_passes_platform_through(tmp_path, capsys):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()
    (source / "photo.jpg").write_text("x")
    (source / ".DS_Store").write_text("junk")

    rc = main([str(source), str(dest), "--platform", "mac"])

    assert rc == 0
    assert "Moved 1 file(s)" in capsys.readouterr().out
    # mac platform skips the junk file, leaving it in the source.
    assert (source / ".DS_Store").exists()


def test_main_reports_invalid_items_per_directory(tmp_path, capsys):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()

    rc = main([str(source), str(dest), "0"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "error:" in err
    assert "items_per_directory" in err


def test_main_reports_missing_source(tmp_path, capsys):
    source = tmp_path / "does_not_exist"
    dest = tmp_path / "dst"

    rc = main([str(source), str(dest)])

    assert rc == 2
    assert "error:" in capsys.readouterr().err


def test_main_rejects_invalid_platform(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "dst"
    source.mkdir()

    # argparse rejects out-of-choice values with SystemExit(2).
    with pytest.raises(SystemExit) as exc_info:
        main([str(source), str(dest), "--platform", "linux"])
    assert exc_info.value.code == 2


def test_main_requires_source_and_dest():
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 2
