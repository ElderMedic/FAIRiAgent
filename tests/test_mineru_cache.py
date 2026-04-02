"""Tests for MinerU checksum cache."""

import tempfile
import unittest
from pathlib import Path

from fairifier.services.mineru_cache import (
    cache_entry_ready,
    sha256_file,
    store_mineru_output_after_success,
    try_get_cached_mineru_tree,
)


class TestMinerUCache(unittest.TestCase):
    def test_sha256_stable(self):
        base = Path(tempfile.mkdtemp())
        p = base / "f.bin"
        p.write_bytes(b"abc")
        self.assertEqual(sha256_file(p), sha256_file(p))

    def test_store_and_hit(self):
        base = Path(tempfile.mkdtemp())
        cache_root = base / "cache"
        digest = "a" * 64
        proj = base / "proj"
        proj.mkdir()
        mo = proj / "mineru_doc"
        (mo / "inner" / "vlm").mkdir(parents=True)
        (mo / "inner" / "vlm" / "x.md").write_text("# t", encoding="utf-8")

        store_mineru_output_after_success(cache_root, digest, mo)
        self.assertTrue(cache_entry_ready(cache_root / digest))

        dest = try_get_cached_mineru_tree(cache_root, digest, proj, "other")
        self.assertIsNotNone(dest)
        self.assertTrue((dest / "inner" / "vlm" / "x.md").is_file())


if __name__ == "__main__":
    unittest.main()
