from __future__ import annotations

import json
import logging
import os
import platform
import time
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DEFAULT_TABLE = "benchmark-test-data"
dynamodb = boto3.client("dynamodb")


def lambda_handler(_event: dict[str, Any] | None, context) -> dict[str, Any]:
    """Lambda handler - Light workload benchmark.

    Performs a DynamoDB batch write (5 items) followed by a batch read to measure
    baseline Lambda invocation and SDK initialization overhead with realistic
    multi-item I/O patterns.
    """
    logger.info(json.dumps({
        "event": "handler_start",
        "workloadType": "light",
        "runtime": f"python{platform.python_version()}",
        "architecture": platform.machine(),
        "requestId": getattr(context, "aws_request_id", "unknown")
    }))

    try:
        write_result = _write_batch()

        # Batch read back the same items to verify round-trip
        read_result = _read_batch(write_result["itemIds"])

        # Match items by ID (batch_get_item doesn't guarantee order)
        all_match = all(
            read_result["items"].get(item["itemId"]) == item["data"]
            for item in write_result["items"]
        )

        logger.info(json.dumps({
            "event": "handler_success",
            "itemsWritten": len(write_result["items"]),
            "itemsRead": len(read_result["items"]),
            "writeRequestId": write_result["requestId"],
            "readRequestId": read_result["requestId"],
            "allDataMatches": all_match
        }))

        return {
            "success": True,
            "workloadType": "light",
            "architecture": platform.machine(),
            "pythonVersion": platform.python_version(),
            "memoryLimitMB": int(getattr(context, "memory_limit_in_mb", 0) or 0),
            "itemsWritten": len(write_result["items"]),
            "itemsRead": len(read_result["items"]),
            "writeRequestId": write_result["requestId"],
            "readRequestId": read_result["requestId"],
            "allDataMatches": all_match,
        }
    except Exception as e:
        logger.error(json.dumps({
            "event": "handler_error",
            "errorType": type(e).__name__,
            "errorMessage": str(e)
        }))
        return _fail(f"{type(e).__name__}: {e}")


def _write_batch() -> dict[str, Any]:
    """Batch write 5 test items to DynamoDB with 24-hour TTL."""
    table = os.environ.get("DYNAMODB_TABLE_NAME") or DEFAULT_TABLE
    now_ms = int(time.time() * 1000)
    arch = platform.machine()  # aarch64 or x86_64
    python_ver = platform.python_version()
    ttl = int(time.time()) + 86_400  # 24h in seconds

    # Create 5 items with unique IDs
    items = []
    for i in range(5):
        item_id = f"test-{now_ms}-{i}"
        data = f"benchmark test data - python{python_ver} {arch} - item {i}"
        items.append({
            "itemId": item_id,
            "data": data,
            "item": {
                "pk": {"S": item_id},
                "sk": {"S": "light"},
                "timestamp": {"N": str(now_ms + i)},
                "ttl": {"N": str(ttl)},
                "workload": {"S": "light"},
                "runtime": {"S": f"python{python_ver}"},
                "architecture": {"S": arch},
                "data": {"S": data},
            }
        })

    # Batch write all items
    request_items = {
        table: [{"PutRequest": {"Item": item["item"]}} for item in items]
    }
    resp = dynamodb.batch_write_item(RequestItems=request_items)

    return {
        "requestId": resp["ResponseMetadata"]["RequestId"],
        "itemIds": [item["itemId"] for item in items],
        "items": [{"itemId": item["itemId"], "data": item["data"]} for item in items]
    }


def _read_batch(item_ids: list[str]) -> dict[str, Any]:
    """Batch read 5 test items from DynamoDB to verify write."""
    table = os.environ.get("DYNAMODB_TABLE_NAME") or DEFAULT_TABLE

    # Batch read all items
    keys = [{"pk": {"S": item_id}, "sk": {"S": "light"}} for item_id in item_ids]
    resp = dynamodb.batch_get_item(
        RequestItems={
            table: {"Keys": keys}
        }
    )

    if table not in resp.get("Responses", {}):
        msg = f"No responses from table: {table}"
        raise ValueError(msg)

    items = resp["Responses"][table]
    if len(items) != len(item_ids):
        msg = f"Expected {len(item_ids)} items, got {len(items)}"
        raise ValueError(msg)

    # Create a map of itemId -> data for matching (batch_get_item doesn't guarantee order)
    items_by_id = {
        item.get("pk", {}).get("S", ""): item.get("data", {}).get("S", "")
        for item in items
    }

    return {
        "requestId": resp["ResponseMetadata"]["RequestId"],
        "items": items_by_id
    }


def _fail(msg: str) -> dict[str, Any]:
    """Return error response in standard format."""
    return {"success": False, "workloadType": "light", "error": msg}
