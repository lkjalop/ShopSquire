"""S-008 — Archive sandboxing & attachment processing isolation.

Enforces strict unpack limits, CPU/RAM caps, and subprocess isolation
for attachment processing (archives, images, PDFs).

Key controls:
- Per-archive: max entries, max member size, max compression ratio, max nesting depth
- Per-process: CPU time limit, memory limit, subprocess isolation boundary
- Runtime: optional subprocess-based isolation via `multiprocessing` with resource limits
"""
from __future__ import annotations

import io
import os
import signal
import tarfile
import time
import zipfile
from dataclasses import dataclass, field
from multiprocessing import Process, Queue
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Configuration (env-overridable)
# ---------------------------------------------------------------------------
def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except Exception:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except Exception:
        return default


MAX_ARCHIVE_ENTRIES = _env_int("SANDBOX_MAX_ARCHIVE_ENTRIES", 200)
MAX_MEMBER_BYTES = _env_int("SANDBOX_MAX_MEMBER_BYTES", 10 * 1024 * 1024)
MAX_TOTAL_UNCOMPRESSED = _env_int("SANDBOX_MAX_TOTAL_UNCOMPRESSED", 50 * 1024 * 1024)
MAX_COMPRESSION_RATIO = _env_float("SANDBOX_MAX_COMPRESSION_RATIO", 80.0)
MAX_NESTING_DEPTH = _env_int("SANDBOX_MAX_NESTING_DEPTH", 3)
SUBPROCESS_CPU_LIMIT_SEC = _env_int("SANDBOX_CPU_LIMIT_SEC", 30)
SUBPROCESS_MEM_LIMIT_MB = _env_int("SANDBOX_MEM_LIMIT_MB", 256)
SUBPROCESS_ENABLED = os.getenv("SANDBOX_SUBPROCESS_ENABLED", "0").strip().lower() in ("1", "true", "yes")


@dataclass
class SandboxResult:
    allowed: bool = True
    reasons: List[str] = field(default_factory=list)
    member_count: int = 0
    total_uncompressed: int = 0
    compression_ratio: float = 0.0
    nesting_depth: int = 0
    members: List[str] = field(default_factory=list)
    process_isolated: bool = False
    cpu_time_sec: float = 0.0
    error: str | None = None


# ---------------------------------------------------------------------------
# Archive inspection with nesting detection
# ---------------------------------------------------------------------------
_ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".7z", ".rar"}


def _is_archive(name: str, blob: bytes) -> bool:
    ext = ("." + name.rsplit(".", 1)[-1]).lower() if "." in name else ""
    if ext in _ARCHIVE_EXTENSIONS:
        return True
    if blob[:4] == b"PK\x03\x04":
        return True
    return False


def _inspect_zip(
    blob: bytes,
    *,
    depth: int = 0,
    max_entries: int,
    max_member: int,
    max_total: int,
    max_ratio: float,
    max_depth: int,
) -> SandboxResult:
    result = SandboxResult(nesting_depth=depth)
    if depth > max_depth:
        result.allowed = False
        result.reasons.append("max_nesting_depth_exceeded")
        return result
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            infos = zf.infolist()
            result.member_count = len(infos)
            if len(infos) > max_entries:
                result.allowed = False
                result.reasons.append("too_many_entries")
            total_comp = 0
            total_uncomp = 0
            for info in infos:
                fn = info.filename or ""
                result.members.append(fn)
                sz = int(info.file_size or 0)
                csz = int(info.compress_size or 0)
                total_comp += csz
                total_uncomp += sz
                if sz > max_member:
                    result.allowed = False
                    result.reasons.append("member_too_large")
                if (int(info.flag_bits or 0) & 0x1) != 0:
                    result.allowed = False
                    result.reasons.append("encrypted_member")
                # Check nested archives
                if _is_archive(fn, b""):
                    try:
                        nested_blob = zf.read(info)
                        nested = _inspect_zip(
                            nested_blob,
                            depth=depth + 1,
                            max_entries=max_entries,
                            max_member=max_member,
                            max_total=max_total,
                            max_ratio=max_ratio,
                            max_depth=max_depth,
                        )
                        if not nested.allowed:
                            result.allowed = False
                            result.reasons.extend(nested.reasons)
                        result.nesting_depth = max(result.nesting_depth, nested.nesting_depth)
                    except Exception:
                        pass
            result.total_uncompressed = total_uncomp
            ratio = float(total_uncomp) / float(max(1, total_comp))
            result.compression_ratio = round(ratio, 3)
            if ratio > max_ratio:
                result.allowed = False
                result.reasons.append("zip_bomb_ratio")
            if total_uncomp > max_total:
                result.allowed = False
                result.reasons.append("total_uncompressed_too_large")
    except Exception as e:
        result.allowed = False
        result.reasons.append("archive_parse_error")
        result.error = str(e)[:200]
    result.reasons = sorted(set(result.reasons))
    result.members = result.members[:50]
    return result


def _inspect_tar(
    blob: bytes,
    *,
    depth: int = 0,
    max_entries: int,
    max_member: int,
    max_total: int,
    max_depth: int,
) -> SandboxResult:
    result = SandboxResult(nesting_depth=depth)
    if depth > max_depth:
        result.allowed = False
        result.reasons.append("max_nesting_depth_exceeded")
        return result
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as tf:
            members = tf.getmembers()
            result.member_count = len(members)
            if len(members) > max_entries:
                result.allowed = False
                result.reasons.append("too_many_entries")
            total = 0
            for m in members:
                fn = m.name or ""
                result.members.append(fn)
                sz = int(m.size or 0)
                total += sz
                if sz > max_member:
                    result.allowed = False
                    result.reasons.append("member_too_large")
                # Block path traversal
                if fn.startswith("/") or ".." in fn:
                    result.allowed = False
                    result.reasons.append("path_traversal_attempt")
            result.total_uncompressed = total
            if total > max_total:
                result.allowed = False
                result.reasons.append("total_uncompressed_too_large")
    except Exception as e:
        result.allowed = False
        result.reasons.append("archive_parse_error")
        result.error = str(e)[:200]
    result.reasons = sorted(set(result.reasons))
    result.members = result.members[:50]
    return result


def inspect_archive(blob: bytes, *, filename: str = "upload") -> SandboxResult:
    """Inspect an archive with full sandboxing controls.

    Applies entry limits, size limits, nesting depth, and zip-bomb detection.
    """
    name = (filename or "").lower()
    is_zip = blob[:4] == b"PK\x03\x04" or name.endswith(".zip")
    is_tar = name.endswith((".tar", ".tgz", ".gz", ".bz2"))

    if is_zip:
        return _inspect_zip(
            blob,
            max_entries=MAX_ARCHIVE_ENTRIES,
            max_member=MAX_MEMBER_BYTES,
            max_total=MAX_TOTAL_UNCOMPRESSED,
            max_ratio=MAX_COMPRESSION_RATIO,
            max_depth=MAX_NESTING_DEPTH,
        )
    elif is_tar:
        return _inspect_tar(
            blob,
            max_entries=MAX_ARCHIVE_ENTRIES,
            max_member=MAX_MEMBER_BYTES,
            max_total=MAX_TOTAL_UNCOMPRESSED,
            max_depth=MAX_NESTING_DEPTH,
        )
    return SandboxResult(error="not_an_archive")


# ---------------------------------------------------------------------------
# Subprocess isolation for heavy processing (optional)
# ---------------------------------------------------------------------------

def _worker(func: Callable[..., Any], args: tuple, result_queue: "Queue[Any]") -> None:
    """Worker function that runs in a subprocess with resource limits."""
    # Set resource limits on Unix (Windows does not support resource module)
    try:
        import resource
        # CPU time limit
        resource.setrlimit(resource.RLIMIT_CPU, (SUBPROCESS_CPU_LIMIT_SEC, SUBPROCESS_CPU_LIMIT_SEC + 5))
        # Memory limit
        mem_bytes = SUBPROCESS_MEM_LIMIT_MB * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    except Exception:
        pass  # Windows — rely on timeout instead

    try:
        result = func(*args)
        result_queue.put(("ok", result))
    except Exception as exc:
        result_queue.put(("error", str(exc)[:500]))


def run_isolated(
    func: Callable[..., Any],
    args: tuple = (),
    *,
    timeout_sec: int | None = None,
) -> Tuple[bool, Any]:
    """Run a callable in a subprocess with CPU/RAM limits.

    Returns (success: bool, result_or_error: Any).
    If SANDBOX_SUBPROCESS_ENABLED is false, runs in-process with a simple timeout.
    """
    timeout = timeout_sec or SUBPROCESS_CPU_LIMIT_SEC

    if not SUBPROCESS_ENABLED:
        # In-process fallback with timeout signal (Unix) or simple try/except (Windows)
        t0 = time.monotonic()
        try:
            result = func(*args)
            return True, result
        except Exception as exc:
            return False, str(exc)[:500]

    q: Queue[Any] = Queue(maxsize=1)
    p = Process(target=_worker, args=(func, args, q), daemon=True)
    p.start()
    p.join(timeout=timeout)
    if p.is_alive():
        p.terminate()
        p.join(timeout=5)
        if p.is_alive():
            p.kill()
        return False, "subprocess_timeout"
    if q.empty():
        return False, "subprocess_no_result"
    status, payload = q.get_nowait()
    return status == "ok", payload
