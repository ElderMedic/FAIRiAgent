"""Host resource metrics using the standard library (no extra packages).

Linux uses /proc and shutil.disk_usage. Other platforms try psutil if installed;
otherwise return conservative placeholders so the API still responds.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _resolve_nvidia_smi_binary() -> Optional[str]:
    """Return path to nvidia-smi if present (dev/prod PATH may omit /usr/bin)."""
    path = shutil.which("nvidia-smi")
    if path:
        return path
    fallback = "/usr/bin/nvidia-smi"
    return fallback if os.path.isfile(fallback) else None


def _parse_csv_float_cell(cell: str) -> float:
    """Parse a CSV cell that may include '%' or spaces (driver / locale quirks)."""
    s = cell.strip().replace("%", "").strip()
    return float(s)


def _cpu_percent_linux(interval: float = 0.15) -> float:
    """CPU usage from /proc/stat; matches common '100 - idle%' semantics."""

    def sample() -> Tuple[int, int]:
        with open("/proc/stat", encoding="utf-8") as f:
            line = f.readline()
        parts = line.split()
        if len(parts) < 5 or parts[0] != "cpu":
            raise OSError("unexpected /proc/stat format")
        nums = [int(x) for x in parts[1:]]
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
        total = sum(nums)
        return idle, total

    idle1, total1 = sample()
    time.sleep(interval)
    idle2, total2 = sample()
    idle_delta = idle2 - idle1
    total_delta = total2 - total1
    if total_delta <= 0:
        return 0.0
    return round(100.0 * (1.0 - idle_delta / total_delta), 1)


def _memory_linux() -> Tuple[float, float, float]:
    """Return (memory_pct, memory_used_gb, memory_total_gb) from /proc/meminfo."""
    data: dict[str, int] = {}
    with open("/proc/meminfo", encoding="utf-8") as f:
        for line in f:
            if ":" not in line:
                continue
            name, rest = line.split(":", 1)
            name = name.strip()
            kb = int(rest.split()[0])
            data[name] = kb
    total_kb = data.get("MemTotal", 0)
    if total_kb <= 0:
        return 0.0, 0.0, 0.0
    avail_kb = data.get("MemAvailable", data.get("MemFree", 0))
    used_kb = max(0, total_kb - avail_kb)
    pct = 100.0 * used_kb / total_kb
    return (
        round(pct, 1),
        round(used_kb / (1024**3), 1),
        round(total_kb / (1024**3), 1),
    )


def _disk_percent(path: str) -> float:
    usage = shutil.disk_usage(path)
    if usage.total <= 0:
        return 0.0
    return round(100.0 * usage.used / usage.total, 1)


def _disk_path_candidates() -> list[str]:
    paths = ["/", os.getcwd(), tempfile.gettempdir()]
    out: list[str] = []
    for p in paths:
        rp = os.path.realpath(p)
        if rp not in out:
            out.append(rp)
    return out


def _disk_percent_best_effort() -> float:
    for path in _disk_path_candidates():
        try:
            return _disk_percent(path)
        except OSError:
            continue
    return 0.0


def _via_psutil() -> Tuple[float, float, float, float, float]:
    import psutil

    cpu_pct = psutil.cpu_percent(interval=0.15)
    mem = psutil.virtual_memory()
    disk_pct = _disk_percent_best_effort()
    if disk_pct == 0.0:
        try:
            disk_pct = round(psutil.disk_usage("/").percent, 1)
        except OSError:
            pass
    return (
        round(float(cpu_pct), 1),
        round(float(mem.percent), 1),
        round(mem.used / (1024**3), 1),
        round(mem.total / (1024**3), 1),
        disk_pct,
    )


def collect_resource_metrics() -> Tuple[float, float, float, float, float]:
    """Return (cpu_pct, memory_pct, memory_used_gb, memory_total_gb, disk_pct)."""
    if sys.platform.startswith("linux"):
        try:
            cpu_pct = _cpu_percent_linux()
            mem_pct, used_gb, total_gb = _memory_linux()
            disk_pct = _disk_percent_best_effort()
            return cpu_pct, mem_pct, used_gb, total_gb, disk_pct
        except OSError:
            pass
    try:
        return _via_psutil()
    except ImportError:
        disk_pct = _disk_percent_best_effort()
        return 0.0, 0.0, 0.0, 0.0, disk_pct


def collect_nvidia_gpu_metrics() -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (gpu_util_pct, gpu_mem_used_gb, gpu_mem_total_gb) via nvidia-smi.

    Uses the driver-provided ``nvidia-smi`` binary (no Python GPU packages).
    Multiple GPUs: utilization is averaged; memory is summed across devices.

    Returns (None, None, None) when the binary is missing, the call fails, or the
    output cannot be parsed (e.g. API process runs without GPU / in a restricted
    container). Check server logs for ``nvidia-smi`` stderr lines.
    """
    nvidia_smi = _resolve_nvidia_smi_binary()
    if not nvidia_smi:
        logger.debug("GPU metrics: nvidia-smi not found on PATH or /usr/bin")
        return None, None, None

    try:
        proc = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("GPU metrics: nvidia-smi failed to run: %s", exc)
        return None, None, None

    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        logger.warning(
            "GPU metrics: nvidia-smi exit %s (stderr: %s)",
            proc.returncode,
            err[:500] if err else "(empty)",
        )
        if not out:
            return None, None, None

    utils: list[float] = []
    used_mib: list[float] = []
    total_mib: list[float] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            utils.append(_parse_csv_float_cell(parts[0]))
            used_mib.append(_parse_csv_float_cell(parts[1]))
            total_mib.append(_parse_csv_float_cell(parts[2]))
        except ValueError:
            nums = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", line)
            if len(nums) >= 3:
                try:
                    utils.append(float(nums[0]))
                    used_mib.append(float(nums[1]))
                    total_mib.append(float(nums[2]))
                except ValueError:
                    continue
            continue
    if not utils:
        logger.warning(
            "GPU metrics: could not parse nvidia-smi CSV (first lines: %s)",
            repr(out[:200]),
        )
        return None, None, None

    avg_util = round(sum(utils) / len(utils), 1)
    sum_used = sum(used_mib)
    sum_total = sum(total_mib)
    if sum_total <= 0:
        return avg_util, None, None
    used_gb = round(sum_used / 1024.0, 1)
    total_gb = round(sum_total / 1024.0, 1)
    return avg_util, used_gb, total_gb


def collect_resource_metrics_with_gpu() -> Tuple[
    float,
    float,
    float,
    float,
    float,
    Optional[float],
    Optional[float],
    Optional[float],
]:
    """Host metrics plus optional NVIDIA GPU stats (single thread pool call)."""
    c1, c2, c3, c4, c5 = collect_resource_metrics()
    g1, g2, g3 = collect_nvidia_gpu_metrics()
    return c1, c2, c3, c4, c5, g1, g2, g3
