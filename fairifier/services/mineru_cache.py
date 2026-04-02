"""Shared MinerU conversion cache keyed by SHA-256 of the source file bytes.

Avoids re-running GPU-heavy MinerU when the same file is uploaded again (any user).
Cache entries are stored under ``mineru_cache_dir/<sha256_hex>/`` and marked complete
with ``.mineru_cache_complete`` after a successful copy.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Optional

logger = logging.getLogger(__name__)

_CACHE_COMPLETE = ".mineru_cache_complete"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute hex SHA-256 of file contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


@contextmanager
def _digest_lock(cache_root: Path, digest: str) -> Iterator[None]:
    """Serialize cache read/write for one digest (best-effort; Unix fcntl)."""
    cache_root.mkdir(parents=True, exist_ok=True)
    lock_path = cache_root / f"{digest}.lock"
    if sys.platform == "win32":
        yield
        return
    import fcntl

    with open(lock_path, "w", encoding="utf-8") as lock_f:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)


def _entry_dir(cache_root: Path, digest: str) -> Path:
    return cache_root / digest


def cache_entry_ready(entry: Path) -> bool:
    return entry.is_dir() and (entry / _CACHE_COMPLETE).is_file()


def _ignore_cache_marker(_dir: str, names: List[str]) -> List[str]:
    return [n for n in names if n == _CACHE_COMPLETE]


def try_get_cached_mineru_tree(
    cache_root: Path,
    digest: str,
    project_output_dir: Path,
    doc_stem: str,
) -> Optional[Path]:
    """If cache hit, copy cached MinerU tree into the project output dir.

    Returns the path to ``project_output_dir / f"mineru_{doc_stem}"`` on success,
    or ``None`` if there is no complete cache entry.
    """
    entry = _entry_dir(cache_root, digest)
    if not cache_entry_ready(entry):
        return None

    dest = project_output_dir / f"mineru_{doc_stem}"
    with _digest_lock(cache_root, digest):
        if not cache_entry_ready(entry):
            return None
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(entry, dest, ignore=_ignore_cache_marker)
        logger.info(
            "MinerU cache HIT: sha256=%s… → %s",
            digest[:16],
            dest,
        )
    return dest


def store_mineru_output_after_success(
    cache_root: Path,
    digest: str,
    mineru_output_dir: Path,
) -> None:
    """Persist a successful MinerU output directory into the shared cache."""
    src = mineru_output_dir.resolve()
    if not src.is_dir():
        logger.warning("MinerU cache store skipped: not a directory: %s", src)
        return

    entry = _entry_dir(cache_root, digest)
    tmp = cache_root / f"{digest}.tmp.{os.getpid()}.{time.time_ns()}"

    with _digest_lock(cache_root, digest):
        if cache_entry_ready(entry):
            return
        try:
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            shutil.copytree(src, tmp, dirs_exist_ok=True)
            (tmp / _CACHE_COMPLETE).write_text(
                f"sha256={digest}\nsource={src}\n",
                encoding="utf-8",
            )
            if entry.exists():
                shutil.rmtree(entry, ignore_errors=True)
            # Atomic rename on same volume; shutil.move falls back if needed (e.g. Windows).
            shutil.move(str(tmp), str(entry))
            logger.info(
                "MinerU cache STORE: sha256=%s… bytes from %s",
                digest[:16],
                src,
            )
        finally:
            if tmp.exists() and tmp != entry:
                shutil.rmtree(tmp, ignore_errors=True)
