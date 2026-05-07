"""Tests for MinerU checksum cache."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from fairifier.config import config
from fairifier.graph.langgraph_app import FAIRifierLangGraphApp
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

    def test_langgraph_single_pdf_path_stores_then_hits_shared_cache(self):
        base = Path(tempfile.mkdtemp())
        cache_root = base / "cache"
        run1 = base / "run1"
        run2 = base / "run2"
        run1.mkdir()
        run2.mkdir()
        pdf = base / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake pdf bytes")

        app = FAIRifierLangGraphApp.__new__(FAIRifierLangGraphApp)
        app.mineru_tool = Mock()
        app._find_existing_mineru_result = FAIRifierLangGraphApp._find_existing_mineru_result.__get__(
            app, FAIRifierLangGraphApp
        )
        app._read_single_document_content = FAIRifierLangGraphApp._read_single_document_content.__get__(
            app, FAIRifierLangGraphApp
        )

        def fake_invoke(payload):
            od = Path(payload["output_dir"])
            inner = od / "paper" / "vlm"
            inner.mkdir(parents=True, exist_ok=True)
            md = inner / "paper.md"
            md.write_text("# converted from mineru", encoding="utf-8")
            return {
                "success": True,
                "markdown_text": "# converted from mineru",
                "markdown_path": str(md),
                "output_dir": str(od),
                "images_dir": None,
                "method": "mineru",
                "error": None,
            }

        app.mineru_tool.invoke.side_effect = fake_invoke

        orig_enabled = config.mineru_enabled
        orig_cache_enabled = config.mineru_cache_enabled
        orig_cache_dir = config.mineru_cache_dir
        try:
            config.mineru_enabled = True
            config.mineru_cache_enabled = True
            config.mineru_cache_dir = cache_root

            text1, info1 = app._read_single_document_content(str(pdf), str(run1))
            self.assertEqual(info1["method"], "mineru")
            self.assertTrue(any(cache_entry_ready(path) for path in cache_root.iterdir() if path.is_dir()))

            app.mineru_tool.invoke.reset_mock()
            text2, info2 = app._read_single_document_content(str(pdf), str(run2))
            self.assertEqual(info2["method"], "mineru_cache")
            self.assertEqual(info2["source"], "mineru_cache")
            self.assertEqual(text1, text2)
            self.assertEqual(app.mineru_tool.invoke.call_count, 0)
            self.assertTrue((run2 / "mineru_paper").exists())
        finally:
            config.mineru_enabled = orig_enabled
            config.mineru_cache_enabled = orig_cache_enabled
            config.mineru_cache_dir = orig_cache_dir


if __name__ == "__main__":
    unittest.main()
