"""
SystemMonitor - GPU load and VRAM for the desktop interface.

Reads NVIDIA's own command-line tool (nvidia-smi), which ships with the
driver. No extra packages, nothing leaves the machine. Results are cached
briefly so several open windows don't start several processes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from typing import Any, Optional

from core.logger import get_logger

logger = get_logger(__name__)

_CREATE_NO_WINDOW = 0x08000000
CACHE_SECONDS = 1.5


class SystemMonitor:
    def __init__(self) -> None:
        self._exe = shutil.which("nvidia-smi")
        self._lock = threading.Lock()
        self._cached: Optional[dict[str, Any]] = None
        self._cached_at = 0.0
        if not self._exe:
            logger.info("nvidia-smi not found - GPU meter disabled.")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._cached is not None and time.monotonic() - self._cached_at < CACHE_SECONDS:
                return self._cached
            self._cached = self._read()
            self._cached_at = time.monotonic()
            return self._cached

    def _read(self) -> dict[str, Any]:
        empty = {"gpu_percent": None, "vram_used_gb": None, "vram_total_gb": None}
        if not self._exe:
            return empty
        try:
            out = subprocess.run(
                [self._exe, "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3, creationflags=_CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            util, used, total = (float(v) for v in out.stdout.strip().splitlines()[0].split(","))
            return {"gpu_percent": round(util), "vram_used_gb": round(used / 1024, 2), "vram_total_gb": round(total / 1024, 2)}
        except Exception as exc:
            logger.debug("GPU query failed: %s", exc)
            return empty
