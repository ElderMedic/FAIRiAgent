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

    def test_hit_same_digest_different_doc_stem_preserves_inner_tree(self):
        """Lookup is SHA-256 only; doc_stem only names mineru_<stem> output folder."""
        base = Path(tempfile.mkdtemp())
        cache_root = base / "cache"
        digest = "c" * 64
        proj = base / "proj"
        proj.mkdir()
        mo = proj / "mineru_original_name"
        (mo / "original_name" / "vlm").mkdir(parents=True)
        (mo / "original_name" / "vlm" / "original_name.md").write_text("# cached", encoding="utf-8")

        store_mineru_output_after_success(cache_root, digest, mo)

        dest = try_get_cached_mineru_tree(cache_root, digest, proj, "renamed_upload")
        self.assertIsNotNone(dest)
        self.assertEqual(dest, proj / "mineru_renamed_upload")
        # Inner folders keep MinerU layout from stored tree, not the new stem.
        self.assertTrue((dest / "original_name" / "vlm" / "original_name.md").is_file())

    def test_miss_wrong_digest(self):
        base = Path(tempfile.mkdtemp())
        cache_root = base / "cache"
        digest_store = "d" * 64
        digest_lookup = "e" * 64
        proj = base / "proj"
        proj.mkdir()
        mo = proj / "mineru_doc"
        mo.mkdir()
        (mo / "x.md").write_text("# t", encoding="utf-8")
        store_mineru_output_after_success(cache_root, digest_store, mo)

        self.assertIsNone(
            try_get_cached_mineru_tree(cache_root, digest_lookup, proj, "doc")
        )


if __name__ == "__main__":
    unittest.main()
