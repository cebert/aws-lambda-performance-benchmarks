from __future__ import annotations

import array
import hashlib
import json
import logging
import platform
import random
from typing import Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Fixed array size for consistent performance measurement across Lambda memory configs
FIXED_ARRAY_SIZE_MB = 100


def lambda_handler(event: dict[str, Any] | None, context) -> dict[str, Any]:
    """Lambda handler - Memory intensive workload benchmark.

    Allocates and sorts a fixed 100 MB array to measure performance scaling
    across different Lambda memory configurations.
    """
    event = event or {}

    logger.info(json.dumps({
        "event": "handler_start",
        "workloadType": "memory-intensive",
        "runtime": f"python{platform.python_version()}",
        "architecture": platform.machine(),
        "requestId": getattr(context, "aws_request_id", "unknown")
    }))

    try:
        result_hash = _memory_sort(FIXED_ARRAY_SIZE_MB)

        logger.info(json.dumps({
            "event": "handler_success",
            "sizeMB": FIXED_ARRAY_SIZE_MB,
            "arrayElements": (FIXED_ARRAY_SIZE_MB * 1024 * 1024) // 8
        }))

        return {
            "success": True,
            "workloadType": "memory-intensive",
            "sizeMB": FIXED_ARRAY_SIZE_MB,
            "architecture": platform.machine(),
            "pythonVersion": platform.python_version(),
            "memoryLimitMB": int(getattr(context, "memory_limit_in_mb", 0) or 0),
            "resultHash": result_hash,
        }
    except Exception as e:
        logger.error(json.dumps({
            "event": "handler_error",
            "errorType": type(e).__name__,
            "errorMessage": str(e)
        }))
        return _fail(f"{type(e).__name__}: {e}")


def _memory_sort(size_mb: int) -> str:
    """Allocates and sorts fixed 100 MB array to stress memory bandwidth.

    Sort operation stresses both memory bandwidth (accessing all elements)
    and CPU (comparison operations), providing comprehensive memory subsystem test.
    """
    count = (size_mb * 1024 * 1024) // 8

    # 'q' = signed 64-bit integer (8 bytes), matching JavaScript's Float64Array
    data = array.array('q', (random.getrandbits(30) for _ in range(count)))

    sorted_data = array.array('q', sorted(data))

    sample = sorted_data[:1000]
    return hashlib.sha256(sample.tobytes()).hexdigest()


def _fail(msg: str) -> dict[str, Any]:
    return {"success": False, "workloadType": "memory-intensive", "error": msg}
