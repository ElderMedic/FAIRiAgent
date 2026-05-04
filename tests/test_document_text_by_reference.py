"""Tests for document_content → document_text_path migration (P1 §5 of refactor)."""

import tempfile
from pathlib import Path

from fairifier.utils.document_text import read_document_text


class TestReadDocumentText:
    def test_reads_from_document_text_path(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as fp:
            fp.write("This is the document text on disk.")
            text_path = fp.name
        try:
            state = {"document_text_path": text_path, "document_content": None}
            assert read_document_text(state) == "This is the document text on disk."
        finally:
            Path(text_path).unlink()

    def test_falls_back_to_document_content_when_path_missing(self):
        state = {
            "document_text_path": None,
            "document_content": "Inline text fallback",
        }
        assert read_document_text(state) == "Inline text fallback"

    def test_falls_back_when_path_does_not_exist(self):
        state = {
            "document_text_path": "/nonexistent/path/that/does/not/exist.txt",
            "document_content": "fallback content",
        }
        assert read_document_text(state) == "fallback content"

    def test_empty_when_neither_set(self):
        assert read_document_text({}) == ""

    def test_max_chars_truncation(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as fp:
            fp.write("ABCDEFGHIJKLMNOP")
            text_path = fp.name
        try:
            state = {"document_text_path": text_path}
            assert read_document_text(state, max_chars=5) == "ABCDE"
        finally:
            Path(text_path).unlink()

    def test_max_chars_zero_returns_empty(self):
        state = {"document_content": "any content"}
        assert read_document_text(state, max_chars=0) == ""

    def test_handles_corrupt_path_gracefully(self):
        """If document_text_path points to a directory or non-text file,
        should fall back gracefully without raising."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = {
                "document_text_path": tmpdir,
                "document_content": "fallback",
            }
            # Should not raise
            result = read_document_text(state)
            assert result == "fallback" or result == ""
