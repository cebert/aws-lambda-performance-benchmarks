from __future__ import annotations

import hashlib
import json
import logging
import platform
from typing import Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DEFAULT_ITERATIONS: int = 1_000_000
MAX_ITERATIONS: int = 10_000_000


def lambda_handler(event: dict[str, Any] | None, context) -> dict[str, Any]:
    """Lambda handler - CPU intensive test executes SHA-256 hashing iterations to measure CPU performance.

    Executes repeated SHA-256 hashing in a tight loop to measure raw compute
    performance differences between architectures and runtimes.
    """
    event = event or {}

    logger.info(json.dumps({
        "event": "handler_start",
        "workloadType": "cpu-intensive",
        "runtime": f"python{platform.python_version()}",
        "architecture": platform.machine(),
        "requestId": getattr(context, "aws_request_id", "unknown")
    }))

    try:
        iterations = int(event.get("iterations", DEFAULT_ITERATIONS))
    except Exception:
        return _fail("invalid 'iterations' (must be an integer)")

    if iterations <= 0:
        return _fail("iterations must be > 0")
    if iterations > MAX_ITERATIONS:
        return _fail(f"iterations too high (max {MAX_ITERATIONS})")

    try:
        result_hex = _cpu_sha256(iterations)

        logger.info(json.dumps({
            "event": "handler_success",
            "iterations": iterations,
            "resultHashLength": len(result_hex)
        }))

        return {
            "success": True,
            "workloadType": "cpu-intensive",
            "iterations": iterations,
            "architecture": platform.machine(),
            "pythonVersion": platform.python_version(),
            "memoryLimitMB": int(getattr(context, "memory_limit_in_mb", 0) or 0),
            "resultHash": result_hex,  # 64-char hex
        }
    except Exception as e:
        logger.error(json.dumps({
            "event": "handler_error",
            "errorType": type(e).__name__,
            "errorMessage": str(e)
        }))
        return _fail(f"{type(e).__name__}: {e}")


def _cpu_sha256(iterations: int) -> str:
    """Chains SHA-256 hashes together for CPU stress testing."""
    sha256 = hashlib.sha256
    data = b"benchmark data for Lambda ARM vs x86 performance testing"
    for _ in range(iterations):
        data = sha256(data).digest()
    return data.hex()


def _fail(msg: str) -> dict[str, Any]:
    """Return error response in standard format."""
    return {"success": False, "workloadType": "cpu-intensive", "error": msg}
