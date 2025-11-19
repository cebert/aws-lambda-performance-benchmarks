#!/usr/bin/env python3
"""
Shared utilities for benchmark orchestration and analysis.

This module contains constants, type definitions, and helper functions
used by both benchmark_orchestrator.py and analyze_results.py to avoid
code duplication.
"""

from decimal import Decimal
from typing import Any

# =============================================================================
# DynamoDB Configuration
# =============================================================================

RESULTS_TABLE_NAME = "BenchmarkResults"
DEFAULT_REGION = "us-east-2"

# =============================================================================
# Workload Types and Memory Configurations
# =============================================================================

# Memory configurations per workload type (MB)
# Follows powers of 2 + 1769 MB (1 vCPU sweet spot)
# cpu-intensive and light stop at 2048 MB (just above 1 vCPU) to verify plateau
# memory-intensive tests full range for bandwidth/allocation effects
MEMORY_CONFIGS = {
    "cpu-intensive": [128, 256, 512, 1024, 1769, 2048],
    "memory-intensive": [128, 256, 512, 1024, 1769, 2048, 4096, 8192, 10240],
    "light": [128, 256, 512, 1024, 1769, 2048],
}

# Valid workload types (derived from MEMORY_CONFIGS keys)
WORKLOAD_TYPES = list(MEMORY_CONFIGS.keys())

# Workload-specific constants
CPU_INTENSIVE_ITERATIONS = 500_000  # SHA-256 hashing iterations
MEMORY_INTENSIVE_ARRAY_SIZE_MB = 100  # Fixed array size for memory-intensive workload

# =============================================================================
# Runtime Configuration
# =============================================================================

# Maps runtime names to their family for grouping in charts
RUNTIME_FAMILIES = {
    "nodejs20": "Node.js",
    "nodejs22": "Node.js",
    "python3.11": "Python",
    "python3.12": "Python",
    "python3.13": "Python",
    "rust": "Rust",
    # Future runtimes:
    # "go1.x": "Go",
}

# Color schemes for runtime families
FAMILY_COLORS = {
    "Node.js": "#68a063",  # Green
    "Python": "#3776ab",  # Blue
    "Rust": "#ce422b",  # Orange-red
    "Go": "#00add8",  # Cyan (future)
}

# Individual runtime colors for charts
RUNTIME_COLORS = {
    "python3.14": "#e377c2",  # Magenta/Pink
    "python3.13": "#1f77b4",  # Blue
    "python3.12": "#2ca02c",  # Green
    "python3.11": "#17becf",  # Cyan/Teal
    "nodejs22": "#ff7f0e",  # Orange
    "nodejs20": "#9467bd",  # Purple
    "rust": "#d62728",  # Red (distinct from orange/teal)
}

# =============================================================================
# DynamoDB Field Names
# =============================================================================

# Field names in result items
RESULT_FIELDS = {
    "duration": "durationMs",
    "billed_duration": "billedDurationMs",
    "memory_used": "maxMemoryUsedMB",
    "init_duration": "initDurationMs",
    "lambda_request_id": "lambdaRequestId",
}

# Field names in aggregate items (statistics)
AGGREGATE_STATS_FIELDS = {
    "duration": "durationMsStats",
    "billed_duration": "billedDurationMsStats",
    "memory": "memoryMBStats",
    "init_duration": "initDurationMsStats",
}

# =============================================================================
# Decimal Conversion Utilities
# =============================================================================


def to_decimal(value: float | int | None) -> Decimal | None:
    """
    Convert numeric value to Decimal for DynamoDB storage.

    Args:
        value: Numeric value to convert

    Returns:
        Decimal representation or None if input is None
    """
    if value is None:
        return None
    return Decimal(str(value))


def decimal_to_float(value: Any) -> Any:
    """
    Recursively convert Decimal values to float for display.

    Handles DynamoDB responses that use Decimal for numeric values.

    Args:
        value: Value to convert (can be dict, list, Decimal, or primitive)

    Returns:
        Value with all Decimals converted to floats
    """
    if isinstance(value, dict):
        return {k: decimal_to_float(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [decimal_to_float(v) for v in value]
    elif isinstance(value, Decimal):
        return float(value)
    else:
        return value


def map_decimal(d: dict[str, float | int | bool]) -> dict[str, Any]:
    """
    Convert float values to Decimal for DynamoDB, preserving int and bool types.

    IMPORTANT: Must check bool BEFORE int, as bool is a subclass of int in Python!

    Args:
        d: Dictionary with numeric values

    Returns:
        Dictionary with floats converted to Decimal, ints and bools preserved
    """
    result = {}
    for k, v in d.items():
        if isinstance(v, bool) or isinstance(v, int):  # Check bool FIRST (bool is subclass of int!)
            result[k] = v
        elif isinstance(v, (float,)):
            result[k] = Decimal(str(v))
        else:
            result[k] = v
    return result


# =============================================================================
# Field Name Helpers
# =============================================================================


def get_field_name(item: dict, preferred: str, fallback: str) -> str | None:
    """
    Get field name with fallback for backward compatibility.

    Useful when field names change over time and you need to support
    reading both old and new formats.

    Args:
        item: DynamoDB item
        preferred: Preferred field name (new format)
        fallback: Fallback field name (old format)

    Returns:
        Field name to use, or None if neither field exists
    """
    if preferred in item:
        return preferred
    if fallback in item:
        return fallback
    return None


# =============================================================================
# Cost Calculation
# =============================================================================

# AWS Lambda pricing by region (GB-seconds and requests)
# Tiered pricing: first tier for most benchmarks (we won't exceed 6-7.5B GB-sec/month in testing)
AWS_PRICING = {
    "us-east-2": {  # Ohio
        "x86": {
            "gb_second": 0.0000166667,  # First 6B GB-sec/month
            "request": 0.20 / 1_000_000,  # $0.20 per 1M requests
        },
        "arm64": {
            "gb_second": 0.0000133334,  # First 7.5B GB-sec/month (20% cheaper)
            "request": 0.20 / 1_000_000,  # $0.20 per 1M requests
        },
    },
    "us-east-1": {  # N. Virginia (same as Ohio)
        "x86": {
            "gb_second": 0.0000166667,
            "request": 0.20 / 1_000_000,
        },
        "arm64": {
            "gb_second": 0.0000133334,
            "request": 0.20 / 1_000_000,
        },
    },
}


def calculate_invocation_cost(
    billed_duration_ms: float, memory_mb: int, architecture: str, region: str = DEFAULT_REGION
) -> float:
    """
    Calculate the cost of a single Lambda invocation.

    Args:
        billed_duration_ms: Billed duration in milliseconds
        memory_mb: Allocated memory in MB
        architecture: 'arm64' or 'x86'
        region: AWS region (defaults to us-east-2)

    Returns:
        Cost in dollars for this invocation
    """
    pricing = AWS_PRICING.get(region, AWS_PRICING[DEFAULT_REGION])
    arch_pricing = pricing.get(architecture, pricing["x86"])

    # Convert to GB-seconds
    gb_seconds = (memory_mb / 1024) * (billed_duration_ms / 1000)

    # Calculate cost
    compute_cost = gb_seconds * arch_pricing["gb_second"]
    request_cost = arch_pricing["request"]

    return compute_cost + request_cost


def calculate_cost_per_million(
    avg_billed_duration_ms: float, memory_mb: int, architecture: str, region: str = DEFAULT_REGION
) -> float:
    """
    Calculate cost per 1 million invocations.

    Args:
        avg_billed_duration_ms: Average billed duration in milliseconds
        memory_mb: Allocated memory in MB
        architecture: 'arm64' or 'x86'
        region: AWS region

    Returns:
        Cost in dollars for 1 million invocations
    """
    single_invocation_cost = calculate_invocation_cost(
        avg_billed_duration_ms, memory_mb, architecture, region
    )
    return single_invocation_cost * 1_000_000


def calculate_cost_savings(arm_cost: float, x86_cost: float) -> dict[str, float]:
    """
    Calculate cost savings of ARM vs x86.

    Args:
        arm_cost: Cost for ARM configuration
        x86_cost: Cost for x86 configuration

    Returns:
        Dictionary with savings percentage and absolute savings
    """
    savings_pct = ((x86_cost - arm_cost) / x86_cost * 100) if x86_cost > 0 else 0
    savings_abs = x86_cost - arm_cost

    return {
        "savings_percentage": round(savings_pct, 2),
        "savings_absolute": round(savings_abs, 2),
    }


# =============================================================================
# Statistics Utilities
# =============================================================================


def percentile(sorted_vals: list[float], p: float) -> float:
    """
    Calculate percentile using linear interpolation between ranks.

    Args:
        sorted_vals: List of values sorted in ascending order
        p: Percentile to calculate (0.0 to 1.0)

    Returns:
        Percentile value
    """
    if not sorted_vals:
        return 0.0

    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]

    rank = p * (n - 1)
    lower_idx = int(rank)
    upper_idx = min(lower_idx + 1, n - 1)
    fraction = rank - lower_idx

    return sorted_vals[lower_idx] + fraction * (sorted_vals[upper_idx] - sorted_vals[lower_idx])


def calculate_statistics(values: list[float], remove_outliers: bool = True) -> dict[str, Any]:
    """
    Calculate comprehensive statistics for a list of values.

    Optionally removes outliers (min and max) when there are at least 5 samples
    to reduce impact of network jitter and cold start variations.

    Args:
        values: List of numeric values
        remove_outliers: If True and >= 5 samples, removes min and max values

    Returns:
        Dictionary with mean, median, mode, min, max, stdev, percentiles, sample count
    """
    if not values:
        return {}

    import statistics
    from collections import Counter

    sorted_values = sorted(values)
    n = len(sorted_values)

    original_min = min(values)
    original_max = max(values)

    calc_values = sorted_values[1:-1] if remove_outliers and n >= 5 else values

    rounded_values = [round(v, 2) for v in calc_values]
    mode_value = (
        Counter(rounded_values).most_common(1)[0][0] if rounded_values else sorted_values[0]
    )

    sorted_calc = sorted(calc_values)

    return {
        "mean": round(statistics.mean(calc_values), 2),
        "median": round(statistics.median(calc_values), 2),
        "mode": mode_value,
        "min": round(original_min, 2),
        "max": round(original_max, 2),
        "stdev": round(statistics.stdev(calc_values), 2) if len(calc_values) > 1 else 0.0,
        "p50": round(percentile(sorted_calc, 0.50), 2),
        "p90": round(percentile(sorted_calc, 0.90), 2),
        "p95": round(percentile(sorted_calc, 0.95), 2),
        "p99": round(percentile(sorted_calc, 0.99), 2),
        "sampleCount": n,
        "outliersRemoved": remove_outliers and n >= 5,
    }


# =============================================================================
# Display Formatting
# =============================================================================


def format_workload_name(workload: str) -> str:
    """
    Format workload name for display with proper capitalization.

    Args:
        workload: Workload type (e.g., "cpu-intensive", "memory-intensive", "light")

    Returns:
        Formatted name (e.g., "CPU Intensive Workload")
    """
    name_map = {
        "cpu-intensive": "CPU Intensive Workload",
        "memory-intensive": "Memory Intensive Workload",
        "light": "Light Workload",
    }
    return name_map.get(workload, workload.replace("-", " ").title() + " Workload")


# =============================================================================
# Configuration ID Generation
# =============================================================================


def make_config_id(function_info: dict[str, str], memory_mb: int) -> str:
    """
    Generate unique configuration identifier.

    Format: {runtime}-{architecture}-{workloadType}-{memorySizeMB}

    Args:
        function_info: Dictionary with runtime, architecture, workloadType
        memory_mb: Memory allocation in MB

    Returns:
        Configuration ID string (e.g., "python3.13-arm64-cpu-intensive-1769")

    Example:
        >>> make_config_id({"runtime": "python3.13", "architecture": "arm64", "workloadType": "cpu-intensive"}, 1769)
        'python3.13-arm64-cpu-intensive-1769'
    """
    return f"{function_info['runtime']}-{function_info['architecture']}-{function_info['workloadType']}-{memory_mb}"


def parse_config_id(config_id: str) -> dict[str, Any]:
    """
    Parse configuration ID back into components.

    Expected format: {runtime}-{architecture}-{workloadType}-{memorySizeMB}

    Args:
        config_id: Configuration ID string (e.g., "python3.13-arm64-cpu-intensive-1769")

    Returns:
        Dictionary with runtime, architecture, workloadType, memorySizeMB

    Raises:
        ValueError: If config_id format is invalid

    Example:
        >>> parse_config_id("python3.13-arm64-cpu-intensive-1769")
        {'runtime': 'python3.13', 'architecture': 'arm64', 'workloadType': 'cpu-intensive', 'memorySizeMB': 1769}
    """
    parts = config_id.rsplit("-", 1)  # Split from right to handle hyphenated workload types
    if len(parts) != 2:
        raise ValueError(f"Invalid config_id format: {config_id}")

    # Parse the left part (runtime-architecture-workloadType)
    left_parts = parts[0].rsplit("-", 2)  # Get last 3 components
    if len(left_parts) < 3:
        raise ValueError(f"Invalid config_id format: {config_id}")

    # For python runtimes: python3.13-arm64-cpu-intensive
    # For nodejs: nodejs22-arm64-cpu-intensive
    if len(left_parts) == 3:
        runtime, arch, workload = left_parts
    else:
        # Multi-part runtime or workload - reconstruct
        # This handles edge cases like multi-word workloads
        runtime = left_parts[0]
        arch = left_parts[-2]
        workload = left_parts[-1]

    return {
        "runtime": runtime,
        "architecture": arch,
        "workloadType": workload,
        "memorySizeMB": int(parts[1]),
    }
