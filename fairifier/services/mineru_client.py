"""MinerU HTTP client wrapper for document conversion."""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .mineru_paths import (
    discover_structured_artifacts,
    find_markdown_in_tree,
    load_content_list_v2,
)


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
    parse_dir: Optional[Path] = None
    content_list_v2_path: Optional[Path] = None
    content_list_path: Optional[Path] = None
    middle_json_path: Optional[Path] = None
    structured_blocks: List[Dict[str, Any]] = field(default_factory=list)
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
        if self.parse_dir:
            data["parse_dir"] = str(self.parse_dir)
        if self.content_list_v2_path:
            data["content_list_v2_path"] = str(self.content_list_v2_path)
        if self.content_list_path:
            data["content_list_path"] = str(self.content_list_path)
        if self.middle_json_path:
            data["middle_json_path"] = str(self.middle_json_path)
        if self.structured_blocks:
            data["structured_block_count"] = str(len(self.structured_blocks))
        if self.other_files:
            serialized = [str(path) for path in self.other_files]
            data["other_files"] = json.dumps(serialized)
        return data


def structured_output_metadata(result: Any) -> Dict[str, Any]:
    """Extract structured MinerU artifact metadata for workflow state."""
    meta: Dict[str, Any] = {}
    for attr in (
        "parse_dir",
        "content_list_v2_path",
        "content_list_path",
        "middle_json_path",
    ):
        value = getattr(result, attr, None)
        if value is not None:
            meta[attr] = str(value)
    blocks = getattr(result, "structured_blocks", None) or []
    if blocks:
        meta["structured_block_count"] = len(blocks)
        meta["structured_blocks"] = blocks[:200]
    return meta


def mineru_client_from_config(config: Any) -> "MinerUClient":
    """Build a :class:`MinerUClient` from ``fairifier.config`` settings."""
    vlm_url = getattr(config, "mineru_vlm_url", None) or config.mineru_server_url
    return MinerUClient(
        cli_path=config.mineru_cli_path,
        server_url=vlm_url or "",
        api_url=getattr(config, "mineru_api_url", None),
        backend=config.mineru_backend,
        timeout_seconds=config.mineru_timeout_seconds,
        effort=getattr(config, "mineru_effort", None),
        image_analysis=getattr(config, "mineru_image_analysis", None),
        structured_output_enabled=getattr(
            config, "mineru_structured_output_enabled", True
        ),
    )


class MinerUClient:
    """Client for invoking MinerU via CLI (mineru-api orchestration + optional VLM URL)."""

    def __init__(
        self,
        cli_path: str,
        server_url: str,
        backend: str = "vlm-http-client",
        timeout_seconds: int = 1800,
        api_url: Optional[str] = None,
        effort: Optional[str] = None,
        image_analysis: Optional[bool] = None,
        structured_output_enabled: bool = True,
    ):
        self.cli_path = cli_path
        self.server_url = server_url
        self.api_url = api_url
        self.backend = backend
        self.timeout_seconds = timeout_seconds
        self.effort = effort
        self.image_analysis = image_analysis
        self.structured_output_enabled = structured_output_enabled

    def is_available(self) -> bool:
        """Return True if CLI is installed (VLM URL required for http-client backends)."""
        http_client = "http-client" in self.backend
        if http_client and not self.server_url:
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
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("MinerU availability check failed: %s", exc)
            return False

    def build_command(
        self,
        src_path: Path,
        out_dir: Path,
    ) -> List[str]:
        """Assemble the MinerU CLI command for the configured backend."""
        cmd = [
            self.cli_path,
            "-p",
            str(src_path),
            "-o",
            str(out_dir),
            "-b",
            self.backend,
        ]
        if self.api_url:
            cmd.extend(["--api-url", self.api_url])
        if "http-client" in self.backend and self.server_url:
            cmd.extend(["-u", self.server_url])
        if self.effort and "hybrid" in self.backend:
            cmd.extend(["--effort", self.effort])
        if self.image_analysis is not None and "hybrid" in self.backend:
            flag = "true" if self.image_analysis else "false"
            cmd.extend(["--image-analysis", flag])
        return cmd

    def convert_document(
        self,
        input_path: str | Path,
        output_dir: Optional[str | Path] = None,
    ) -> MinerUConversionResult:
        """
        Convert a document to Markdown using MinerU.

        Raises:
            MinerUConversionError: Raised when conversion fails or expected
                artifacts are missing.
        """
        if "http-client" in self.backend and not self.server_url:
            raise MinerUConversionError(
                "MinerU VLM URL is not configured (MINERU_SERVER_URL / MINERU_VLM_URL)."
            )

        src_path = Path(input_path).expanduser().resolve()
        if not src_path.exists():
            raise MinerUConversionError(f"Input file does not exist: {src_path}")

        if output_dir is None:
            tmp_dir = tempfile.mkdtemp(prefix="mineru_", dir=None)
            out_dir = Path(tmp_dir)
        else:
            out_dir = Path(output_dir).expanduser().resolve()
            out_dir.mkdir(parents=True, exist_ok=True)

        cmd = self.build_command(src_path, out_dir)
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
            message = (
                "MinerU conversion failed with exit code "
                f"{exc.returncode}: {stderr.strip()}"
            )
            raise MinerUConversionError(message) from exc

        if completed.stdout:
            logger.debug("MinerU stdout: %s", completed.stdout.strip())
        if completed.stderr:
            logger.debug("MinerU stderr: %s", completed.stderr.strip())
            if "ERROR" in completed.stderr or "Error" in completed.stderr:
                error_lines = [
                    line
                    for line in completed.stderr.split("\n")
                    if "ERROR" in line or "Error" in line or "Traceback" in line
                ]
                if error_lines:
                    logger.warning(
                        "MinerU stderr contains errors: %s",
                        "\n".join(error_lines[:5]),
                    )

        doc_stem = src_path.stem
        located = find_markdown_in_tree(out_dir, doc_stem)
        if not located:
            all_files = [f for f in out_dir.rglob("*") if f.is_file()][:10]
            file_list = "\n".join(f"  - {f}" for f in all_files)
            message = (
                f"MinerU output directory '{out_dir}' does not contain a Markdown file.\n"
                f"Return code: {completed.returncode}\n"
            )
            if completed.stderr:
                message += f"Stderr: {completed.stderr.strip()[:500]}\n"
            message += (
                f"Files found in output directory:\n{file_list}"
                if file_list
                else "No files found in output directory."
            )
            raise MinerUConversionError(message)

        markdown_path, images_dir = located
        logger.info("Found MinerU Markdown at: %s", markdown_path)

        try:
            markdown_text = markdown_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            markdown_text = markdown_path.read_text(encoding="utf-8", errors="ignore")

        parse_dir = markdown_path.parent
        artifacts = discover_structured_artifacts(parse_dir, doc_stem)
        structured_blocks: List[Dict[str, Any]] = []
        content_list_v2_path = artifacts.get("content_list_v2")
        content_list_path = artifacts.get("content_list")
        middle_json_path = artifacts.get("middle_json")

        if self.structured_output_enabled and content_list_v2_path:
            try:
                structured_blocks = load_content_list_v2(content_list_v2_path)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to load content_list_v2: %s", exc)

        other_files = self._collect_other_files(out_dir, markdown_path, images_dir)

        return MinerUConversionResult(
            input_path=src_path,
            output_dir=out_dir,
            markdown_path=markdown_path,
            markdown_text=markdown_text,
            images_dir=images_dir,
            parse_dir=parse_dir,
            content_list_v2_path=content_list_v2_path,
            content_list_path=content_list_path,
            middle_json_path=middle_json_path,
            structured_blocks=structured_blocks,
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
