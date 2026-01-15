"""MinerU HTTP client wrapper for document conversion."""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional


logger = logging.getLogger(__name__)


class MinerUConversionError(RuntimeError):
    """Raised when MinerU conversion fails."""


@dataclass
class MinerUConversionResult:
    """Structured result returned after running MinerU conversion."""

    input_path: Path
    output_dir: Path
    markdown_path: Path
    markdown_text: str
    images_dir: Optional[Path] = None
    other_files: List[Path] = field(default_factory=list)

    def to_dict(self) -> Dict[str, str]:
        """Return serialisable representation for workflow state."""
        data: Dict[str, str] = {
            "input_path": str(self.input_path),
            "output_dir": str(self.output_dir),
            "markdown_path": str(self.markdown_path),
        }
        if self.images_dir:
            data["images_dir"] = str(self.images_dir)
        if self.other_files:
            serialized = [str(path) for path in self.other_files]
            data["other_files"] = json.dumps(serialized)
        return data


class MinerUClient:
    """Minimal client for invoking MinerU HTTP backend via CLI."""

    def __init__(
        self,
        cli_path: str,
        server_url: str,
        backend: str = "vlm-http-client",
        timeout_seconds: int = 300,
    ):
        self.cli_path = cli_path
        self.server_url = server_url
        self.backend = backend
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        """Return True if CLI is installed and server URL configured."""
        if not self.server_url:
            return False
        try:
            subprocess.run(
                [self.cli_path, "--help"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
            return True
        except FileNotFoundError:
            return False
        except subprocess.TimeoutExpired:
            # CLI exists; help command hung but assume available.
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("MinerU availability check failed: %s", exc)
            return False

    def convert_document(
        self,
        input_path: str | Path,
        output_dir: Optional[str | Path] = None,
    ) -> MinerUConversionResult:
        """
        Convert a document to Markdown using MinerU.

        Args:
            input_path: Path to the source document (e.g. PDF).
            output_dir: Optional directory to store MinerU artifacts. When
                omitted, a temporary directory is created.

        Returns:
            MinerUConversionResult with paths and Markdown content.

        Raises:
            MinerUConversionError: Raised when conversion fails or expected
                artifacts are missing.
        """
        if not self.server_url:
            raise MinerUConversionError("MinerU server URL is not configured.")

        src_path = Path(input_path).expanduser().resolve()
        if not src_path.exists():
            message = f"Input file does not exist: {src_path}"
            raise MinerUConversionError(message)

        if output_dir is None:
            tmp_dir = tempfile.mkdtemp(prefix="mineru_", dir=None)
            out_dir = Path(tmp_dir)
        else:
            out_dir = Path(output_dir).expanduser().resolve()
            out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.cli_path,
            "-p",
            str(src_path),
            "-o",
            str(out_dir),
            "-b",
            self.backend,
            "-u",
            self.server_url,
        ]
        logger.info("Running MinerU conversion: %s", " ".join(cmd))

        try:
            completed = subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as exc:
            message = (
                f"MinerU CLI not found at '{self.cli_path}'. "
                "Ensure it is installed and on PATH."
            )
            raise MinerUConversionError(message) from exc
        except subprocess.TimeoutExpired as exc:
            message = (
                "MinerU conversion timed out after "
                f"{self.timeout_seconds} seconds."
            )
            raise MinerUConversionError(message) from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr or ""
            error_detail = stderr.strip()
            message = (
                "MinerU conversion failed with exit code "
                f"{exc.returncode}: {error_detail}"
            )
            raise MinerUConversionError(message) from exc

        if completed.stdout:
            logger.debug("MinerU stdout: %s", completed.stdout.strip())
        if completed.stderr:
            logger.debug("MinerU stderr: %s", completed.stderr.strip())
            # Check for errors in stderr even if return code is 0
            if "ERROR" in completed.stderr or "Error" in completed.stderr:
                error_lines = [line for line in completed.stderr.split('\n') 
                              if 'ERROR' in line or 'Error' in line or 'Traceback' in line]
                if error_lines:
                    error_summary = '\n'.join(error_lines[:5])  # First 5 error lines
                    logger.warning("MinerU stderr contains errors: %s", error_summary)

        # MinerU creates output in: {out_dir}/{docname}/vlm/{docname}.md
        # Search recursively for .md files
        markdown_files = list(out_dir.glob("**/*.md"))
        if not markdown_files:
            # List what files were actually created for debugging
            all_files = list(out_dir.rglob("*"))
            file_list = "\n".join([f"  - {f}" for f in all_files[:10] if f.is_file()])
            message = (
                f"MinerU output directory '{out_dir}' does not contain a Markdown file.\n"
                f"Return code: {completed.returncode}\n"
            )
            if completed.stderr:
                error_summary = completed.stderr.strip()[:500]
                message += f"Stderr: {error_summary}\n"
            if file_list:
                message += f"Files found in output directory:\n{file_list}"
            else:
                message += "No files found in output directory."
            raise MinerUConversionError(message)

        # Use the first markdown file found (typically there's only one)
        markdown_path = markdown_files[0]
        logger.info(f"Found MinerU Markdown at: {markdown_path}")
        
        try:
            markdown_text = markdown_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            markdown_text = markdown_path.read_text(
                encoding="utf-8",
                errors="ignore",
            )

        # Images are in the same directory as the markdown file
        images_dir = markdown_path.parent / "images"
        if not images_dir.exists():
            images_dir = None

        other_files = self._collect_other_files(
            out_dir,
            markdown_path,
            images_dir,
        )

        return MinerUConversionResult(
            input_path=src_path,
            output_dir=out_dir,
            markdown_path=markdown_path,
            markdown_text=markdown_text,
            images_dir=images_dir,
            other_files=other_files,
        )

    @staticmethod
    def _collect_other_files(
        output_dir: Path, markdown_path: Path, images_dir: Optional[Path]
    ) -> List[Path]:
        """Return non-Markdown, non-image artifacts for reference."""
        skip: Iterable[Path] = [markdown_path]
        if images_dir:
            skip = list(skip) + [images_dir]

        skip_set = {path.resolve() for path in skip}

        other_files: List[Path] = []
        for path in output_dir.iterdir():
            resolved = path.resolve()
            if resolved in skip_set:
                continue
            other_files.append(path)
        return other_files
