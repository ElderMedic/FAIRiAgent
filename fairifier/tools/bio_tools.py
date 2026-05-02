"""Bioinformatics tools using containerized execution."""

from __future__ import annotations

import gzip
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import List, Optional

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Known biocontainer images — the agent can use the short alias (e.g. "samtools")
# and the tool resolves the full quay.io image automatically.
_BIO_TOOL_IMAGES = {
    "samtools": "quay.io/biocontainers/samtools:1.23.1--ha83d96e_0",
    "bcftools": "quay.io/biocontainers/bcftools:1.23.1--hb2cee57_0",
}


def _resolve_image(image: str) -> str:
    """If image is a short alias, resolve to the full quay.io image."""
    return _BIO_TOOL_IMAGES.get(image.lower(), image)


def _ensure_docker_image(image: str) -> bool:
    """Pull a Docker image if it is not already present. Returns True on success."""
    try:
        inspect = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True, text=True, timeout=15,
        )
        if inspect.returncode == 0:
            return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        pass

    logger.info("Pulling Docker image: %s", image)
    try:
        pull = subprocess.run(
            ["docker", "pull", image],
            capture_output=True, text=True, timeout=600,
        )
        if pull.returncode == 0:
            logger.info("Successfully pulled %s", image)
            return True
        logger.warning("Failed to pull %s: %s", image, pull.stderr.strip())
        return False
    except Exception as exc:
        logger.warning("Docker pull exception for %s: %s", image, exc)
        return False


@tool
def run_biocontainer_tool(
    image: str,
    command: List[str],
    host_path: str,
    workdir: str = "/data",
) -> str:
    """
    Run a bioinformatics tool inside a Docker container.

    Mounts the parent directory of host_path into the container at /data,
    so the file is accessible as /data/<filename>. Auto-pulls the image if missing.

    Use a short alias like "samtools" or "bcftools" for image — the tool
    resolves it to the correct quay.io image automatically.

    Args:
        image: Docker image or alias ("samtools" or "bcftools")
        command: Command + args, e.g. ["samtools", "stats", "/data/file.bam"]
        host_path: Absolute host path to the data file
        workdir: Working directory inside the container (default /data)

    Returns:
        stdout from the containerized command, or an error message.
    """
    host = Path(os.path.abspath(host_path))
    if not host.exists():
        return f"Error: host_path does not exist: {host}"

    mount_src = str(host.parent) if host.is_file() else str(host)
    resolved_image = _resolve_image(image)

    if not _ensure_docker_image(resolved_image):
        return f"Error: failed to pull Docker image {image}"

    docker_cmd = [
        "docker", "run", "--rm",
        "-v", f"{mount_src}:{workdir}",
        "-w", workdir,
        resolved_image,
    ] + command

    try:
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=300,
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"Error running tool (rc={e.returncode}): {e.stderr}\nOutput: {e.stdout}"
    except subprocess.TimeoutExpired:
        return "Error: tool execution timed out after 300s"
    except Exception as e:
        return f"Unexpected error: {str(e)}"


@tool
def decompress_gzip_tool(host_path: str) -> str:
    """
    Decompress a .gz file in-place, returning the path to the decompressed file.

    Args:
        host_path: Absolute path to the .gz file

    Returns:
        Path to the decompressed file, or an error message.
    """
    src = Path(os.path.abspath(host_path))
    if not src.exists():
        return f"Error: file does not exist: {src}"
    if src.suffix.lower() != ".gz":
        return f"Error: file does not have .gz extension: {src}"

    dest = src.with_suffix("")  # remove .gz
    try:
        with gzip.open(src, "rb") as f_in:
            with open(dest, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        return f"Decompressed {src.name} → {dest}"
    except Exception as e:
        return f"Error decompressing {src}: {str(e)}"


@tool
def extract_archive_tool(host_path: str) -> str:
    """
    Extract a .tar or .tar.gz archive to a temporary directory.

    Args:
        host_path: Absolute path to the archive

    Returns:
        JSON list of extracted file paths, or an error message.
    """
    src = Path(os.path.abspath(host_path))
    if not src.exists():
        return f"Error: file does not exist: {src}"

    suffix = src.suffix.lower()
    if suffix not in (".tar", ".gz") and not src.name.endswith(".tar.gz"):
        return f"Error: unsupported archive format: {src}"

    dest_dir = Path(tempfile.mkdtemp(prefix="fairifier_archive_"))
    try:
        mode = "r:gz" if src.name.endswith(".tar.gz") else "r"
        with tarfile.open(src, mode) as tf:
            tf.extractall(path=dest_dir)
        files = sorted(str(p) for p in dest_dir.rglob("*") if p.is_file())
        return f"Extracted {len(files)} files to {dest_dir}:\n" + "\n".join(files[:50])
    except Exception as e:
        return f"Error extracting {src}: {str(e)}"


def create_bio_tools() -> List:
    return [run_biocontainer_tool, decompress_gzip_tool, extract_archive_tool]
