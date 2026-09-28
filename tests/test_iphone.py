"""Device-free tests of the AFC import path."""

import asyncio
from datetime import datetime, timezone

from photo_organizer.iphone import _organize_from_afc


class FakeAfc:
    def __init__(self, files):
        self.files = files
        self.handles = {}
        self.next_handle = 1
        self.fail_path = None

    async def listdir(self, path):
        if path == "/DCIM":
            return ["100APPLE", "101APPLE", "._ignored"]
        return [p.rsplit("/", 1)[1] for p in self.files if p.rsplit("/", 1)[0] == path]

    async def stat(self, path):
        if path in ("/DCIM/100APPLE", "/DCIM/101APPLE"):
            return {"st_ifmt": "S_IFDIR"}
        data, timestamp = self.files[path]
        return {"st_ifmt": "S_IFREG", "st_size": len(data), "st_birthtime": timestamp}

    async def fopen(self, path, mode):
        assert mode == "r"
        handle = self.next_handle
        self.next_handle += 1
        self.handles[handle] = [path, 0]
        return handle

    async def fread(self, handle, size):
        path, offset = self.handles[handle]
        if path == self.fail_path:
            raise OSError("simulated device disconnect")
        data = self.files[path][0][offset : offset + size]
        self.handles[handle][1] += len(data)
        return data

    async def fclose(self, handle):
        del self.handles[handle]


def test_iphone_import_resumes_and_skips_duplicate(tmp_path):
    early = datetime(2020, 1, 1, tzinfo=timezone.utc)
    late = datetime(2021, 1, 1, tzinfo=timezone.utc)
    afc = FakeAfc(
        {
            "/DCIM/100APPLE/IMG_1.JPG": (b"first", early),
            "/DCIM/101APPLE/IMG_1.JPG": (b"second", late),
        }
    )
    first = asyncio.run(_organize_from_afc(afc, str(tmp_path), 1))
    second = asyncio.run(_organize_from_afc(afc, str(tmp_path), 1))

    assert first == 2
    assert second == 0
    assert (tmp_path / "Directory_1" / "IMG_1.JPG").read_bytes() == b"first"
    assert (tmp_path / "Directory_2" / "IMG_1.JPG").read_bytes() == b"second"
    assert not afc.handles


def test_iphone_failed_read_leaves_no_partial_photo(tmp_path):
    stamp = datetime(2020, 1, 1, tzinfo=timezone.utc)
    afc = FakeAfc(
        {
            "/DCIM/100APPLE/IMG_1.JPG": (b"first", stamp),
            "/DCIM/100APPLE/IMG_2.JPG": (b"second", stamp),
        }
    )
    afc.fail_path = "/DCIM/100APPLE/IMG_1.JPG"
    result = asyncio.run(_organize_from_afc(afc, str(tmp_path), 1))

    assert result == 1
    assert len(result.failures) == 1
    assert (tmp_path / "Directory_1" / "IMG_2.JPG").read_bytes() == b"second"
    assert list(tmp_path.rglob("IMG_1.JPG")) == []
    assert not any(p.name.startswith(".photo-organizer-tmp-") for p in tmp_path.rglob("*"))
    assert not afc.handles
