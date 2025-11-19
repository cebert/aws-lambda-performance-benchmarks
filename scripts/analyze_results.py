#!/usr/bin/env python3
"""
Benchmark Results Analysis Script with Visualization

Analyzes aggregate statistics from DynamoDB and generates:
- Markdown reports with comparison tables
- Performance charts (ARM64 vs x86)
- Cold start analysis
- Cost analysis

Usage:
    python analyze_results.py <test_run_id>
    python analyze_results.py <test_run_id> --runtime python3.13
    python analyze_results.py <test_run_id> --workload cpu-intensive
"""

import argparse
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import boto3
import matplotlib.pyplot as plt
from benchmark_utils import (
    AWS_PRICING,
    DEFAULT_REGION,
    FAMILY_COLORS,
    RESULTS_TABLE_NAME,
    RUNTIME_COLORS,
    RUNTIME_FAMILIES,
    calculate_cost_per_million,
    calculate_cost_savings,
    calculate_invocation_cost,
    decimal_to_float,
    format_workload_name,
    get_field_name,
)
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

dynamodb = boto3.client("dynamodb")

# =============================================================================
# Chart Styling Configuration
# =============================================================================

# Chart styling constants
BAR_WIDTH_STANDARD = 0.35
BAR_WIDTH_NARROW = 0.25
FAMILY_SPACING = 1.0
CHART_DPI = 300

# =============================================================================
# DynamoDB Parsing Functions
# =============================================================================


def parse_test_matrix(matrix_item: dict[str, Any]) -> dict[str, Any]:
    """
    Parse test matrix from DynamoDB format to Python dict.

    Converts DynamoDB's verbose attribute-value format to a clean Python dictionary
    with lists of runtimes, architectures, workloads, and configurations.

    Args:
        matrix_item: Test matrix in DynamoDB format (with 'M', 'L', 'S' type markers)

    Returns:
        Dictionary with runtimes, architectures, workloadTypes, and configurations lists
    """
    return {
        "runtimes": [r["S"] for r in matrix_item["runtimes"]["L"]],
        "architectures": [a["S"] for a in matrix_item["architectures"]["L"]],
        "workloadTypes": [w["S"] for w in matrix_item["workloadTypes"]["L"]],
        "configurations": [
            {
                "runtime": config["M"]["runtime"]["S"],
                "architecture": config["M"]["architecture"]["S"],
                "workloadType": config["M"]["workloadType"]["S"],
                "memorySizes": [int(m["N"]) for m in config["M"]["memorySizes"]["L"]],
            }
            for config in matrix_item["configurations"]["L"]
        ],
    }


def get_test_run_info(test_run_id: str) -> dict[str, Any] | None:
    """
    Get test run metadata from DynamoDB.

    Retrieves the test-run item containing execution metadata like timestamp,
    status, mode, region, and the complete test matrix.

    Args:
        test_run_id: UUID of the test run

    Returns:
        Dictionary with test run metadata, or None if not found or error occurs
    """
    try:
        response = dynamodb.get_item(
            TableName=RESULTS_TABLE_NAME,
            Key={"pk": {"S": f"TESTRUN#{test_run_id}"}, "sk": {"S": f"TESTRUN#{test_run_id}"}},
        )
        if "Item" not in response:
            return None

        item = response["Item"]
        test_run_info = {
            "testRunId": item["testRunId"]["S"],
            "timestamp": int(item["timestamp"]["N"]),
            "status": item.get("status", {}).get("S", "unknown"),
            "mode": item.get("mode", {}).get("S", "unknown"),
            "region": item.get("region", {}).get("S", DEFAULT_REGION),
            "notes": item.get("notes", {}).get("S", ""),
            "totalConfigurations": int(item.get("totalConfigurations", {}).get("N", "0")),
            "totalInvocations": int(item.get("totalInvocations", {}).get("N", "0")),
            "coldStartsPerConfig": int(item.get("coldStartsPerConfig", {}).get("N", "0")),
            "warmStartsPerConfig": int(item.get("warmStartsPerConfig", {}).get("N", "0")),
        }

        # Parse test matrix if present
        if "testMatrix" in item:
            test_run_info["testMatrix"] = parse_test_matrix(item["testMatrix"]["M"])

        return test_run_info
    except ClientError as e:
        log.error(f"Failed to get test run info from DynamoDB: {e}")
        return None
    except Exception as e:
        log.error(f"Unexpected error getting test run info: {e}")
        return None


def parse_stats_value(value_dict: dict[str, Any]) -> Any:
    """
    Parse a DynamoDB attribute value that could be a Number, Boolean, or other type.

    This handles the mixed types in statistics maps (e.g., sampleCount is int/Number,
    outliersRemoved is bool/Boolean, other stats are float/Number).
    """
    if "N" in value_dict:
        return float(value_dict["N"])
    elif "BOOL" in value_dict:
        return value_dict["BOOL"]
    else:
        # Fallback for other types
        return value_dict


def parse_stats_map(item: dict[str, Any], preferred: str, fallback: str) -> dict[str, float]:
    """
    Parse statistics map from DynamoDB with field name fallback support.

    Centralizes the logic for parsing preferred vs fallback stats field names
    (e.g., durationMsStats vs durationStats) and converting DynamoDB format
    to Python-friendly dictionaries.

    Args:
        item: DynamoDB item containing statistics
        preferred: Preferred field name (new format, e.g., "durationMsStats")
        fallback: Fallback field name (old format, e.g., "durationStats")

    Returns:
        Dictionary with stats converted from Decimal to float, or empty dict if field not found
    """
    key = get_field_name(item, preferred, fallback)
    if not key or key not in item:
        return {}

    stats_map = {k: v for k, v in item[key]["M"].items()}
    return decimal_to_float({k: parse_stats_value(v) for k, v in stats_map.items()})


def get_all_aggregates(test_run_id: str) -> list[dict[str, Any]]:
    """
    Query all aggregate statistics for a test run.

    Returns aggregate items in a Python-friendly format.
    Cost: ~0.03 RCUs = $0.000004
    """
    response = dynamodb.query(
        TableName=RESULTS_TABLE_NAME,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :sk_prefix)",
        ExpressionAttributeValues={
            ":pk": {"S": f"TESTRUN#{test_run_id}"},
            ":sk_prefix": {"S": "AGGREGATE#"},
        },
    )

    aggregates = []
    for item in response["Items"]:
        agg = {
            "runtime": item["runtime"]["S"],
            "architecture": item["architecture"]["S"],
            "workloadType": item["workloadType"]["S"],
            "memorySizeMB": int(item["memorySizeMB"]["N"]),
            "invocationType": item["invocationType"]["S"],
            "sampleCount": int(item["sampleCount"]["N"]),
            "allSuccessful": item["allSuccessful"]["BOOL"],
            "failedCount": int(item["failedCount"]["N"]),
            "durationStats": parse_stats_map(item, "durationMsStats", "durationStats"),
            "billedDurationStats": parse_stats_map(
                item, "billedDurationMsStats", "billedDurationStats"
            ),
            "memoryStats": parse_stats_map(item, "memoryMBStats", "memoryStats"),
        }

        # Init duration stats only present for cold starts
        init_stats = parse_stats_map(item, "initDurationMsStats", "initDurationStats")
        if init_stats:
            agg["initDurationStats"] = init_stats

        aggregates.append(agg)

    return aggregates


def filter_aggregates(
    aggregates: list[dict[str, Any]],
    runtime: str | None = None,
    architecture: str | None = None,
    workload_type: str | None = None,
    invocation_type: str | None = None,
    memory_size_mb: int | None = None,
    only_successful: bool = False,
) -> list[dict[str, Any]]:
    """
    Filter aggregates by multiple dimensions.

    Args:
        aggregates: List of aggregate statistics
        runtime: Filter by runtime (e.g., "python3.13", "nodejs20")
        architecture: Filter by architecture ("arm64", "x86")
        workload_type: Filter by workload type ("cpu-intensive", "memory-intensive", "light")
        invocation_type: Filter by invocation type ("cold", "warm")
        memory_size_mb: Filter by memory size in MB
        only_successful: If True, only include aggregates where all samples succeeded

    Returns:
        Filtered list of aggregates
    """
    filtered = aggregates

    if runtime:
        filtered = [a for a in filtered if a["runtime"] == runtime]
    if architecture:
        filtered = [a for a in filtered if a["architecture"] == architecture]
    if workload_type:
        filtered = [a for a in filtered if a["workloadType"] == workload_type]
    if invocation_type:
        filtered = [a for a in filtered if a["invocationType"] == invocation_type]
    if memory_size_mb:
        filtered = [a for a in filtered if a["memorySizeMB"] == memory_size_mb]
    if only_successful:
        filtered = [a for a in filtered if a.get("allSuccessful", False)]

    return filtered


def create_output_directory(test_run_id: str, region: str, workloads: list[str]) -> Path:
    """
    Create output directory structure for analysis results.

    Creates a results directory with subdirectories for charts and tables organized
    by workload type. Directory name includes both test run ID and region.

    Args:
        test_run_id: UUID of the test run
        region: AWS region (included in directory name)
        workloads: List of workload types to create subdirectories for

    Returns:
        Path to the created results directory
    """
    results_dir = Path("results") / f"{test_run_id}-{region}"
    results_dir.mkdir(parents=True, exist_ok=True)

    # Create subdirectories for each workload type
    for workload in workloads:
        (results_dir / "charts" / workload).mkdir(parents=True, exist_ok=True)
        (results_dir / "tables" / workload).mkdir(parents=True, exist_ok=True)

    return results_dir


def generate_summary_markdown(
    test_run_info: dict[str, Any] | None, aggregates: list[dict[str, Any]], output_dir: Path
) -> None:
    """
    Generate a summary markdown README file with test run info and table of contents.

    Creates a comprehensive README.md with:
    - Test run metadata (timestamp, status, mode, region, invocation counts)
    - Test matrix summary (runtimes, architectures, workloads tested)
    - Table of contents linking to all tables and charts

    Args:
        test_run_info: Test run metadata from DynamoDB (or None if unavailable)
        aggregates: List of aggregate statistics
        output_dir: Path to output directory for the README file
    """
    summary_path = output_dir / "README.md"

    with open(summary_path, "w") as f:
        f.write("# Benchmark Results Analysis\n\n")

        # Test run info
        if test_run_info:
            f.write("## Test Run Information\n\n")
            timestamp = datetime.fromtimestamp(test_run_info["timestamp"] / 1000).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            f.write(f"- **Test Run ID**: `{test_run_info['testRunId']}`\n")
            f.write(f"- **Timestamp**: {timestamp}\n")
            f.write(f"- **Status**: {test_run_info['status']}\n")
            f.write(f"- **Mode**: {test_run_info['mode']}\n")
            f.write(f"- **Region**: {test_run_info.get('region', 'unknown')}\n")
            if test_run_info.get("notes"):
                f.write(f"- **Notes**: {test_run_info['notes']}\n")
            f.write(f"- **Total Configurations**: {test_run_info['totalConfigurations']}\n")
            f.write(f"- **Total Invocations**: {test_run_info['totalInvocations']}\n")
            f.write(f"- **Cold Starts per Config**: {test_run_info['coldStartsPerConfig']}\n")
            f.write(f"- **Warm Starts per Config**: {test_run_info['warmStartsPerConfig']}\n")

            # Display test matrix if present
            if "testMatrix" in test_run_info:
                f.write("\n### Test Matrix\n\n")
                matrix = test_run_info["testMatrix"]
                f.write(f"- **Runtimes**: {', '.join(matrix['runtimes'])}\n")
                f.write(f"- **Architectures**: {', '.join(matrix['architectures'])}\n")
                f.write(f"- **Workload Types**: {', '.join(matrix['workloadTypes'])}\n")
                f.write(f"- **Total Configurations**: {len(matrix['configurations'])}\n")

                f.write(
                    "\n<details>\n<summary>Click to view full configuration matrix</summary>\n\n"
                )
                f.write("    | Runtime | Architecture | Workload | Memory Sizes (MB) |\n")
                f.write("    |---------|--------------|----------|-------------------|\n")
                for config in matrix["configurations"]:
                    memory_str = ", ".join(str(m) for m in config["memorySizes"])
                    f.write(
                        f"    | {config['runtime']} | {config['architecture']} | "
                        f"{config['workloadType']} | {memory_str} |\n"
                    )
                f.write("\n</details>\n\n")
            else:
                f.write("\n")
        else:
            f.write("## Test Run Information\n\n*Test run metadata not available*\n\n")

        # Summary stats
        f.write("## Summary Statistics\n\n")
        f.write(f"- **Total Aggregates**: {len(aggregates)}\n")

        runtimes = sorted({a["runtime"] for a in aggregates})
        workloads = sorted({a["workloadType"] for a in aggregates})
        architectures = sorted({a["architecture"] for a in aggregates})

        f.write(f"- **Runtimes Tested**: {', '.join(runtimes)}\n")
        f.write(f"- **Workload Types**: {', '.join(workloads)}\n")
        f.write(f"- **Architectures**: {', '.join(architectures)}\n\n")

        # Table of contents
        f.write("## Contents\n\n")
        f.write("### Comparison Tables\n\n")
        for workload in workloads:
            f.write(f"- [{format_workload_name(workload)}](tables/{workload}/)\n")
            f.write(f"  - [Cold Starts](tables/{workload}/cold.md)\n")
            f.write(f"  - [Warm Starts](tables/{workload}/warm.md)\n")
        f.write("\n### Charts\n\n")
        for workload in workloads:
            f.write(f"- [{format_workload_name(workload)}](charts/{workload}/)\n")
            f.write("  - Memory Scaling (cold & warm)\n")
            f.write("  - P99 Duration Scaling (cold & warm)\n")
            f.write("  - Cost Effectiveness (cold & warm)\n")
            f.write("  - Runtime Family P99 Comparison (warm)\n")
        f.write("- [Cold Start Analysis](charts/cold-start-analysis.png)\n\n")


def generate_comparison_table(
    aggregates: list[dict[str, Any]],
    workload: str,
    invocation_type: str,
    output_dir: Path,
    region: str = DEFAULT_REGION,
) -> None:
    """
    Generate markdown comparison tables for a specific workload and invocation type.

    Creates detailed markdown tables comparing ARM64 vs x86 performance with:
    - Performance comparison (duration, init time, P99, improvement percentages)
    - Cost analysis (cost per 1M invocations, savings percentages, winner indicators)
    - Init duration breakdown (for cold starts only)

    Tables are organized by runtime and memory configuration.

    Args:
        aggregates: List of aggregate statistics
        workload: Workload type (cpu-intensive, memory-intensive, light)
        invocation_type: 'cold' or 'warm'
        output_dir: Path to output directory
        region: AWS region for cost calculations (defaults to us-east-2)
    """
    filtered = filter_aggregates(
        aggregates, workload_type=workload, invocation_type=invocation_type, only_successful=True
    )

    if not filtered:
        return

    # Group by runtime and memory
    data = defaultdict(lambda: defaultdict(dict))
    for agg in filtered:
        runtime = agg["runtime"]
        memory = agg["memorySizeMB"]
        arch = agg["architecture"]
        data[runtime][memory][arch] = agg

    # Create markdown table
    table_path = output_dir / "tables" / workload / f"{invocation_type}.md"
    with open(table_path, "w") as f:
        f.write(f"# {format_workload_name(workload)} Starts\n\n")

        for runtime in sorted(data.keys()):
            f.write(f"## {runtime}\n\n")

            # Table header with performance columns including init time
            f.write("### Performance Comparison\n\n")
            f.write(
                "| Memory (MB) | ARM64 Duration (ms) | ARM64 Init (ms) | x86 Duration (ms) | x86 Init (ms) | Perf Improvement | ARM64 P99 (ms) | x86 P99 (ms) |\n"
            )
            f.write(
                "|------------:|--------------------:|----------------:|------------------:|--------------:|-----------------:|---------------:|-------------:|\n"
            )

            # Table rows
            for memory in sorted(data[runtime].keys()):
                arm_agg = data[runtime][memory].get("arm64")
                x86_agg = data[runtime][memory].get("x86")

                if arm_agg and x86_agg:
                    arm_mean = arm_agg["durationStats"]["mean"]
                    x86_mean = x86_agg["durationStats"]["mean"]
                    arm_p99 = arm_agg["durationStats"]["p99"]
                    x86_p99 = x86_agg["durationStats"]["p99"]

                    # Get init time (0 for warm starts, actual value for cold starts)
                    arm_init = arm_agg.get("initDurationStats", {}).get("mean", 0.0)
                    x86_init = x86_agg.get("initDurationStats", {}).get("mean", 0.0)

                    improvement = ((x86_mean - arm_mean) / x86_mean) * 100

                    f.write(
                        f"| {memory:>11} | {arm_mean:>19.2f} | {arm_init:>15.2f} | {x86_mean:>17.2f} | {x86_init:>13.2f} | "
                        f"{improvement:>+15.1f}% | {arm_p99:>14.2f} | {x86_p99:>12.2f} |\n"
                    )
                elif arm_agg:
                    arm_mean = arm_agg["durationStats"]["mean"]
                    arm_p99 = arm_agg["durationStats"]["p99"]
                    arm_init = arm_agg.get("initDurationStats", {}).get("mean", 0.0)
                    f.write(
                        f"| {memory:>11} | {arm_mean:>19.2f} | {arm_init:>15.2f} | {'N/A':>17} | {'N/A':>13} | "
                        f"{'N/A':>16} | {arm_p99:>14.2f} | {'N/A':>12} |\n"
                    )
                elif x86_agg:
                    x86_mean = x86_agg["durationStats"]["mean"]
                    x86_p99 = x86_agg["durationStats"]["p99"]
                    x86_init = x86_agg.get("initDurationStats", {}).get("mean", 0.0)
                    f.write(
                        f"| {memory:>11} | {'N/A':>19} | {'N/A':>15} | {x86_mean:>17.2f} | {x86_init:>13.2f} | "
                        f"{'N/A':>16} | {'N/A':>14} | {x86_p99:>12.2f} |\n"
                    )

            f.write("\n")

            # Add cost comparison table
            f.write(f"### Cost Analysis (Region: {region})\n\n")
            f.write("| Memory (MB) | ARM64 Cost/1M | x86 Cost/1M | Cost Savings | Winner |\n")
            f.write("|------------:|--------------:|------------:|-------------:|:------:|\n")

            for memory in sorted(data[runtime].keys()):
                arm_agg = data[runtime][memory].get("arm64")
                x86_agg = data[runtime][memory].get("x86")

                if arm_agg and x86_agg:
                    arm_billed = arm_agg["billedDurationStats"]["mean"]
                    x86_billed = x86_agg["billedDurationStats"]["mean"]

                    arm_cost = calculate_cost_per_million(arm_billed, memory, "arm64", region)
                    x86_cost = calculate_cost_per_million(x86_billed, memory, "x86", region)
                    savings = calculate_cost_savings(arm_cost, x86_cost)

                    # Determine winner (lowest cost for same workload)
                    winner = "🏆 ARM64" if arm_cost < x86_cost else "🏆 x86"

                    f.write(
                        f"| {memory:>11} | ${arm_cost:>12.4f} | ${x86_cost:>10.4f} | "
                        f"{savings['savings_percentage']:>+11.1f}% | {winner} |\n"
                    )
                elif arm_agg:
                    arm_billed = arm_agg["billedDurationStats"]["mean"]
                    arm_cost = calculate_cost_per_million(arm_billed, memory, "arm64", region)
                    f.write(
                        f"| {memory:>11} | ${arm_cost:>12.4f} | {'N/A':>11} | "
                        f"{'N/A':>12} | {'ARM64':^6} |\n"
                    )
                elif x86_agg:
                    x86_billed = x86_agg["billedDurationStats"]["mean"]
                    x86_cost = calculate_cost_per_million(x86_billed, memory, "x86", region)
                    f.write(
                        f"| {memory:>11} | {'N/A':>13} | ${x86_cost:>10.4f} | "
                        f"{'N/A':>12} | {'x86':^6} |\n"
                    )

            f.write("\n")

            # Add cold start init duration table if applicable
            if invocation_type == "cold":
                f.write(f"### {runtime} - Init Duration (Cold Starts)\n\n")
                f.write(
                    "| Memory (MB) | ARM64 Init (ms) | x86 Init (ms) | Improvement | ARM64 P99 (ms) | x86 P99 (ms) |\n"
                )
                f.write(
                    "|------------:|----------------:|--------------:|------------:|---------------:|-------------:|\n"
                )

                for memory in sorted(data[runtime].keys()):
                    arm_agg = data[runtime][memory].get("arm64")
                    x86_agg = data[runtime][memory].get("x86")

                    if arm_agg and x86_agg and "initDurationStats" in arm_agg:
                        arm_init = arm_agg["initDurationStats"]["mean"]
                        x86_init = x86_agg["initDurationStats"]["mean"]
                        arm_p99 = arm_agg["initDurationStats"]["p99"]
                        x86_p99 = x86_agg["initDurationStats"]["p99"]
                        improvement = ((x86_init - arm_init) / x86_init) * 100

                        f.write(
                            f"| {memory:>11} | {arm_init:>15.2f} | {x86_init:>13.2f} | "
                            f"{improvement:>+10.1f}% | {arm_p99:>14.2f} | {x86_p99:>12.2f} |\n"
                        )
                    elif arm_agg and "initDurationStats" in arm_agg:
                        arm_init = arm_agg["initDurationStats"]["mean"]
                        arm_p99 = arm_agg["initDurationStats"]["p99"]
                        f.write(
                            f"| {memory:>11} | {arm_init:>15.2f} | {'N/A':>13} | "
                            f"{'N/A':>11} | {arm_p99:>14.2f} | {'N/A':>12} |\n"
                        )
                    elif x86_agg and "initDurationStats" in x86_agg:
                        x86_init = x86_agg["initDurationStats"]["mean"]
                        x86_p99 = x86_agg["initDurationStats"]["p99"]
                        f.write(
                            f"| {memory:>11} | {'N/A':>15} | {x86_init:>13.2f} | "
                            f"{'N/A':>11} | {'N/A':>14} | {x86_p99:>12.2f} |\n"
                        )

                f.write("\n")


# =============================================================================
# New Chart Functions - Memory Scaling and Performance Analysis
# =============================================================================


def create_memory_scaling_chart(
    aggregates: list[dict[str, Any]],
    workload: str,
    invocation_type: str,
    output_dir: Path,
) -> None:
    """
    Create comprehensive memory scaling chart with ALL runtimes and architectures.

    This is the PRIMARY chart for comparing performance across configurations.
    X-axis: Memory (MB), Y-axis: Duration (ms), Lines: Each runtime+architecture combo

    Args:
        aggregates: List of aggregate statistics
        workload: Workload type (cpu-intensive, memory-intensive, light)
        invocation_type: 'cold' or 'warm'
        output_dir: Output directory for charts
    """
    filtered = filter_aggregates(
        aggregates, workload_type=workload, invocation_type=invocation_type, only_successful=True
    )

    if not filtered:
        return

    # Group data by runtime+architecture combination
    series_data = defaultdict(lambda: {"memory": [], "duration": [], "p99": []})

    for agg in filtered:
        key = f"{agg['runtime']}-{agg['architecture']}"
        series_data[key]["memory"].append(agg["memorySizeMB"])

        # For cold starts, include init time in total duration
        duration = agg["durationStats"]["mean"]
        p99 = agg["durationStats"]["p99"]

        if invocation_type == "cold" and "initDurationStats" in agg:
            duration += agg["initDurationStats"]["mean"]
            p99 += agg["initDurationStats"]["p99"]

        series_data[key]["duration"].append(duration)
        series_data[key]["p99"].append(p99)

    # Sort memory values for each series
    for key in series_data:
        # Combine and sort by memory
        combined = list(
            zip(
                series_data[key]["memory"],
                series_data[key]["duration"],
                series_data[key]["p99"],
                strict=False,
            )
        )
        combined.sort(key=lambda x: x[0])
        series_data[key]["memory"] = [x[0] for x in combined]
        series_data[key]["duration"] = [x[1] for x in combined]
        series_data[key]["p99"] = [x[2] for x in combined]

    fig, ax = plt.subplots(figsize=(14, 8))

    for key in sorted(series_data.keys()):
        runtime = key.rsplit("-", 1)[0]
        arch = key.rsplit("-", 1)[1]

        color = RUNTIME_COLORS.get(runtime, "#000000")
        linestyle = "-" if arch == "arm64" else "--"
        marker = "o" if arch == "arm64" else "s"

        ax.plot(
            series_data[key]["memory"],
            series_data[key]["duration"],
            label=key,
            color=color,
            linestyle=linestyle,
            marker=marker,
            linewidth=2.5 if arch == "arm64" else 2,
            markersize=7,
            alpha=0.8,
        )

    ax.set_xlabel("Memory Configuration (MB)", fontsize=13, fontweight="bold")
    y_label = (
        "Total Time (init+duration, ms)" if invocation_type == "cold" else "Mean Duration (ms)"
    )
    ax.set_ylabel(y_label, fontsize=13, fontweight="bold")
    subtitle = "(init+duration)" if invocation_type == "cold" else ""
    ax.set_title(
        f"Memory Scaling: {format_workload_name(workload)} - {invocation_type.title()} Starts {subtitle}\n"
        f"Solid lines = ARM64, Dashed lines = x86",
        fontsize=15,
        fontweight="bold",
    )
    ax.legend(bbox_to_anchor=(1.05, 1), loc="upper left", fontsize=9)
    ax.grid(alpha=0.3, which="both", linestyle=":")
    ax.set_xscale("log", base=2)  # Log scale for memory makes scaling clearer

    # Set custom tick labels to show actual MB values instead of powers of 2
    all_memory_values = sorted(
        set(mem for series in series_data.values() for mem in series["memory"])
    )
    ax.set_xticks(all_memory_values)
    ax.set_xticklabels([f"{int(m)}" for m in all_memory_values])

    plt.tight_layout()
    plt.savefig(
        output_dir / "charts" / workload / f"memory-scaling-{invocation_type}.png",
        dpi=CHART_DPI,
        bbox_inches="tight",
    )
    plt.close()


def create_nodejs_rust_comparison_chart(
    aggregates: list[dict[str, Any]],
    workload: str,
    invocation_type: str,
    output_dir: Path,
) -> None:
    """
    Create comparison chart showing only Node.js and Rust runtimes.

    This chart excludes Python runtimes to provide a clearer view of Node.js vs Rust
    performance without the visual clutter of 4 Python versions.
    """
    # Filter for only Node.js and Rust runtimes
    filtered = [
        agg
        for agg in filter_aggregates(
            aggregates, workload_type=workload, invocation_type=invocation_type, only_successful=True
        )
        if agg["runtime"].startswith("nodejs") or agg["runtime"] == "rust"
    ]

    if not filtered:
        return

    # Group by runtime + architecture
    series_data = defaultdict(lambda: {"memory": [], "duration": [], "p99": []})

    for agg in filtered:
        runtime = agg["runtime"]
        arch = agg["architecture"]
        memory_mb = agg["memorySizeMB"]

        key = f"{runtime}-{arch}"

        # Calculate total time (init + duration for cold, just duration for warm)
        if invocation_type == "cold":
            init_mean = agg["initDurationStats"]["mean"]
            duration_mean = agg["durationStats"]["mean"]
            total_time = init_mean + duration_mean
        else:
            total_time = agg["durationStats"]["mean"]

        p99 = agg["durationStats"].get("p99", 0)

        series_data[key]["memory"].append(memory_mb)
        series_data[key]["duration"].append(total_time)
        series_data[key]["p99"].append(p99)

    # Sort memory values for each series
    for key in series_data:
        combined = list(
            zip(
                series_data[key]["memory"],
                series_data[key]["duration"],
                series_data[key]["p99"],
                strict=False,
            )
        )
        combined.sort(key=lambda x: x[0])
        series_data[key]["memory"] = [x[0] for x in combined]
        series_data[key]["duration"] = [x[1] for x in combined]
        series_data[key]["p99"] = [x[2] for x in combined]

    fig, ax = plt.subplots(figsize=(14, 8))

    for key in sorted(series_data.keys()):
        runtime = key.rsplit("-", 1)[0]
        arch = key.rsplit("-", 1)[1]

        color = RUNTIME_COLORS.get(runtime, "#000000")
        linestyle = "-" if arch == "arm64" else "--"
        marker = "o" if arch == "arm64" else "s"

        ax.plot(
            series_data[key]["memory"],
            series_data[key]["duration"],
            label=key,
            color=color,
            linestyle=linestyle,
            marker=marker,
            linewidth=2.5 if arch == "arm64" else 2,
            markersize=7,
            alpha=0.8,
        )

    ax.set_xlabel("Memory Configuration (MB)", fontsize=13, fontweight="bold")
    y_label = (
        "Total Time (init+duration, ms)" if invocation_type == "cold" else "Mean Duration (ms)"
    )
    ax.set_ylabel(y_label, fontsize=13, fontweight="bold")
    subtitle = "(init+duration)" if invocation_type == "cold" else ""
    ax.set_title(
        f"Node.js & Rust Comparison: {format_workload_name(workload)} - {invocation_type.title()} Starts {subtitle}\n"
        f"Solid lines = ARM64, Dashed lines = x86",
        fontsize=15,
        fontweight="bold",
    )
    ax.legend(bbox_to_anchor=(1.05, 1), loc="upper left", fontsize=10)
    ax.grid(alpha=0.3, which="both", linestyle=":")
    ax.set_xscale("log", base=2)

    # Set custom tick labels
    all_memory_values = sorted(
        set(mem for series in series_data.values() for mem in series["memory"])
    )
    ax.set_xticks(all_memory_values)
    ax.set_xticklabels([f"{int(m)}" for m in all_memory_values])

    plt.tight_layout()
    chart_path = output_dir / "charts" / workload / f"nodejs-rust-comparison-{invocation_type}.png"
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(chart_path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close()


def create_python_comparison_chart(
    aggregates: list[dict[str, Any]],
    workload: str,
    invocation_type: str,
    output_dir: Path,
) -> None:
    """
    Create comparison chart showing only Python runtimes.

    With 4 Python versions (3.14, 3.13, 3.12, 3.11), this dedicated chart makes it
    easier to compare Python version performance across architectures.
    """
    # Filter for only Python runtimes
    filtered = [
        agg
        for agg in filter_aggregates(
            aggregates, workload_type=workload, invocation_type=invocation_type, only_successful=True
        )
        if agg["runtime"].startswith("python")
    ]

    if not filtered:
        return

    # Group by runtime + architecture
    series_data = defaultdict(lambda: {"memory": [], "duration": [], "p99": []})

    for agg in filtered:
        runtime = agg["runtime"]
        arch = agg["architecture"]
        memory_mb = agg["memorySizeMB"]

        key = f"{runtime}-{arch}"

        # Calculate total time (init + duration for cold, just duration for warm)
        if invocation_type == "cold":
            init_mean = agg["initDurationStats"]["mean"]
            duration_mean = agg["durationStats"]["mean"]
            total_time = init_mean + duration_mean
        else:
            total_time = agg["durationStats"]["mean"]

        p99 = agg["durationStats"].get("p99", 0)

        series_data[key]["memory"].append(memory_mb)
        series_data[key]["duration"].append(total_time)
        series_data[key]["p99"].append(p99)

    # Sort memory values for each series
    for key in series_data:
        combined = list(
            zip(
                series_data[key]["memory"],
                series_data[key]["duration"],
                series_data[key]["p99"],
                strict=False,
            )
        )
        combined.sort(key=lambda x: x[0])
        series_data[key]["memory"] = [x[0] for x in combined]
        series_data[key]["duration"] = [x[1] for x in combined]
        series_data[key]["p99"] = [x[2] for x in combined]

    fig, ax = plt.subplots(figsize=(14, 8))

    for key in sorted(series_data.keys()):
        runtime = key.rsplit("-", 1)[0]
        arch = key.rsplit("-", 1)[1]

        color = RUNTIME_COLORS.get(runtime, "#000000")
        linestyle = "-" if arch == "arm64" else "--"
        marker = "o" if arch == "arm64" else "s"

        ax.plot(
            series_data[key]["memory"],
            series_data[key]["duration"],
            label=key,
            color=color,
            linestyle=linestyle,
            marker=marker,
            linewidth=2.5 if arch == "arm64" else 2,
            markersize=7,
            alpha=0.8,
        )

    ax.set_xlabel("Memory Configuration (MB)", fontsize=13, fontweight="bold")
    y_label = (
        "Total Time (init+duration, ms)" if invocation_type == "cold" else "Mean Duration (ms)"
    )
    ax.set_ylabel(y_label, fontsize=13, fontweight="bold")
    subtitle = "(init+duration)" if invocation_type == "cold" else ""
    ax.set_title(
        f"Python Version Comparison: {format_workload_name(workload)} - {invocation_type.title()} Starts {subtitle}\n"
        f"Solid lines = ARM64, Dashed lines = x86",
        fontsize=15,
        fontweight="bold",
    )
    ax.legend(bbox_to_anchor=(1.05, 1), loc="upper left", fontsize=10)
    ax.grid(alpha=0.3, which="both", linestyle=":")
    ax.set_xscale("log", base=2)

    # Set custom tick labels
    all_memory_values = sorted(
        set(mem for series in series_data.values() for mem in series["memory"])
    )
    ax.set_xticks(all_memory_values)
    ax.set_xticklabels([f"{int(m)}" for m in all_memory_values])

    plt.tight_layout()
    chart_path = output_dir / "charts" / workload / f"python-comparison-{invocation_type}.png"
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(chart_path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close()


def create_nodejs_comparison_chart(
    aggregates: list[dict[str, Any]],
    workload: str,
    invocation_type: str,
    output_dir: Path,
) -> None:
    """
    Create comparison chart showing only Node.js runtimes.

    Focused view comparing Node.js 20 vs 22 across ARM64 and x86 architectures.
    """
    # Filter for only Node.js runtimes
    filtered = [
        agg
        for agg in filter_aggregates(
            aggregates, workload_type=workload, invocation_type=invocation_type, only_successful=True
        )
        if agg["runtime"].startswith("nodejs")
    ]

    if not filtered:
        return

    # Group by runtime + architecture
    series_data = defaultdict(lambda: {"memory": [], "duration": [], "p99": []})

    for agg in filtered:
        runtime = agg["runtime"]
        arch = agg["architecture"]
        memory_mb = agg["memorySizeMB"]

        key = f"{runtime}-{arch}"

        # Calculate total time (init + duration for cold, just duration for warm)
        if invocation_type == "cold":
            init_mean = agg["initDurationStats"]["mean"]
            duration_mean = agg["durationStats"]["mean"]
            total_time = init_mean + duration_mean
        else:
            total_time = agg["durationStats"]["mean"]

        p99 = agg["durationStats"].get("p99", 0)

        series_data[key]["memory"].append(memory_mb)
        series_data[key]["duration"].append(total_time)
        series_data[key]["p99"].append(p99)

    # Sort memory values for each series
    for key in series_data:
        combined = list(
            zip(
                series_data[key]["memory"],
                series_data[key]["duration"],
                series_data[key]["p99"],
                strict=False,
            )
        )
        combined.sort(key=lambda x: x[0])
        series_data[key]["memory"] = [x[0] for x in combined]
        series_data[key]["duration"] = [x[1] for x in combined]
        series_data[key]["p99"] = [x[2] for x in combined]

    fig, ax = plt.subplots(figsize=(14, 8))

    for key in sorted(series_data.keys()):
        runtime = key.rsplit("-", 1)[0]
        arch = key.rsplit("-", 1)[1]

        color = RUNTIME_COLORS.get(runtime, "#000000")
        linestyle = "-" if arch == "arm64" else "--"
        marker = "o" if arch == "arm64" else "s"

        ax.plot(
            series_data[key]["memory"],
            series_data[key]["duration"],
            label=key,
            color=color,
            linestyle=linestyle,
            marker=marker,
            linewidth=2.5 if arch == "arm64" else 2,
            markersize=7,
            alpha=0.8,
        )

    ax.set_xlabel("Memory Configuration (MB)", fontsize=13, fontweight="bold")
    y_label = (
        "Total Time (init+duration, ms)" if invocation_type == "cold" else "Mean Duration (ms)"
    )
    ax.set_ylabel(y_label, fontsize=13, fontweight="bold")
    subtitle = "(init+duration)" if invocation_type == "cold" else ""
    ax.set_title(
        f"Node.js Version Comparison: {format_workload_name(workload)} - {invocation_type.title()} Starts {subtitle}\n"
        f"Solid lines = ARM64, Dashed lines = x86",
        fontsize=15,
        fontweight="bold",
    )
    ax.legend(bbox_to_anchor=(1.05, 1), loc="upper left", fontsize=10)
    ax.grid(alpha=0.3, which="both", linestyle=":")
    ax.set_xscale("log", base=2)

    # Set custom tick labels
    all_memory_values = sorted(
        set(mem for series in series_data.values() for mem in series["memory"])
    )
    ax.set_xticks(all_memory_values)
    ax.set_xticklabels([f"{int(m)}" for m in all_memory_values])

    plt.tight_layout()
    chart_path = output_dir / "charts" / workload / f"nodejs-comparison-{invocation_type}.png"
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(chart_path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close()


def create_p99_scaling_chart(
    aggregates: list[dict[str, Any]],
    workload: str,
    invocation_type: str,
    output_dir: Path,
) -> None:
    """
    Create P99 duration scaling chart showing tail (worst-case) performance.

    Shows 99th percentile execution duration across memory configurations.
    """
    filtered = filter_aggregates(
        aggregates, workload_type=workload, invocation_type=invocation_type, only_successful=True
    )

    if not filtered:
        return

    # Group data by runtime+architecture combination
    series_data = defaultdict(lambda: {"memory": [], "p99": []})

    for agg in filtered:
        key = f"{agg['runtime']}-{agg['architecture']}"
        series_data[key]["memory"].append(agg["memorySizeMB"])

        # For cold starts, include init time in P99
        p99 = agg["durationStats"]["p99"]
        if invocation_type == "cold" and "initDurationStats" in agg:
            p99 += agg["initDurationStats"]["p99"]

        series_data[key]["p99"].append(p99)

    # Sort memory values for each series
    for key in series_data:
        combined = list(zip(series_data[key]["memory"], series_data[key]["p99"], strict=False))
        combined.sort(key=lambda x: x[0])
        series_data[key]["memory"] = [x[0] for x in combined]
        series_data[key]["p99"] = [x[1] for x in combined]

    fig, ax = plt.subplots(figsize=(14, 8))

    for key in sorted(series_data.keys()):
        runtime = key.rsplit("-", 1)[0]
        arch = key.rsplit("-", 1)[1]

        color = RUNTIME_COLORS.get(runtime, "#000000")
        linestyle = "-" if arch == "arm64" else "--"
        marker = "o" if arch == "arm64" else "s"

        ax.plot(
            series_data[key]["memory"],
            series_data[key]["p99"],
            label=key,
            color=color,
            linestyle=linestyle,
            marker=marker,
            linewidth=2.5 if arch == "arm64" else 2,
            markersize=7,
            alpha=0.8,
        )

    ax.set_xlabel("Memory Configuration (MB)", fontsize=13, fontweight="bold")
    y_label = (
        "P99 Total Time (init+duration, ms)" if invocation_type == "cold" else "P99 Duration (ms)"
    )
    ax.set_ylabel(y_label, fontsize=13, fontweight="bold")
    subtitle = "(init+duration)" if invocation_type == "cold" else ""
    ax.set_title(
        f"P99 Duration Scaling: {format_workload_name(workload)} - {invocation_type.title()} Starts {subtitle}\n"
        f"Solid lines = ARM64, Dashed lines = x86",
        fontsize=15,
        fontweight="bold",
    )
    ax.legend(bbox_to_anchor=(1.05, 1), loc="upper left", fontsize=9)
    ax.grid(alpha=0.3, which="both", linestyle=":")
    ax.set_xscale("log", base=2)

    # Set custom tick labels to show actual MB values instead of powers of 2
    all_memory_values = sorted(
        set(mem for series in series_data.values() for mem in series["memory"])
    )
    ax.set_xticks(all_memory_values)
    ax.set_xticklabels([f"{int(m)}" for m in all_memory_values])

    plt.tight_layout()
    plt.savefig(
        output_dir / "charts" / workload / f"p99-scaling-{invocation_type}.png",
        dpi=CHART_DPI,
        bbox_inches="tight",
    )
    plt.close()


def create_cost_effectiveness_chart(
    aggregates: list[dict[str, Any]],
    workload: str,
    invocation_type: str,
    output_dir: Path,
    region: str = DEFAULT_REGION,
) -> None:
    """
    Create cost-effectiveness chart showing cost per 1M invocations across memory configs.

    Shows TRUE cost including ARM's 20% pricing discount.
    """
    filtered = filter_aggregates(
        aggregates, workload_type=workload, invocation_type=invocation_type, only_successful=True
    )

    if not filtered:
        return

    # Group data by runtime+architecture combination
    series_data = defaultdict(lambda: {"memory": [], "cost": []})

    for agg in filtered:
        key = f"{agg['runtime']}-{agg['architecture']}"
        memory = agg["memorySizeMB"]
        billed_duration = agg["billedDurationStats"]["mean"]
        arch = agg["architecture"]

        cost_per_million = calculate_cost_per_million(billed_duration, memory, arch, region)

        series_data[key]["memory"].append(memory)
        series_data[key]["cost"].append(cost_per_million)

    # Sort memory values for each series
    for key in series_data:
        combined = list(zip(series_data[key]["memory"], series_data[key]["cost"], strict=False))
        combined.sort(key=lambda x: x[0])
        series_data[key]["memory"] = [x[0] for x in combined]
        series_data[key]["cost"] = [x[1] for x in combined]

    fig, ax = plt.subplots(figsize=(14, 8))

    for key in sorted(series_data.keys()):
        runtime = key.rsplit("-", 1)[0]
        arch = key.rsplit("-", 1)[1]

        color = RUNTIME_COLORS.get(runtime, "#000000")
        linestyle = "-" if arch == "arm64" else "--"
        marker = "o" if arch == "arm64" else "s"

        ax.plot(
            series_data[key]["memory"],
            series_data[key]["cost"],
            label=key,
            color=color,
            linestyle=linestyle,
            marker=marker,
            linewidth=2.5 if arch == "arm64" else 2,
            markersize=7,
            alpha=0.8,
        )

    ax.set_xlabel("Memory Configuration (MB)", fontsize=13, fontweight="bold")
    ax.set_ylabel("Cost per 1M Invocations ($)", fontsize=13, fontweight="bold")
    ax.set_title(
        f"Cost Effectiveness: {format_workload_name(workload)} - {invocation_type.title()} Starts\n"
        f"Solid lines = ARM64 (20% cheaper), Dashed lines = x86 | Region: {region}",
        fontsize=15,
        fontweight="bold",
    )
    ax.legend(bbox_to_anchor=(1.05, 1), loc="upper left", fontsize=9)
    ax.grid(alpha=0.3, which="both", linestyle=":")
    ax.set_xscale("log", base=2)

    # Set custom tick labels to show actual MB values instead of powers of 2
    all_memory_values = sorted(
        set(mem for series in series_data.values() for mem in series["memory"])
    )
    ax.set_xticks(all_memory_values)
    ax.set_xticklabels([f"{int(m)}" for m in all_memory_values])

    plt.tight_layout()
    plt.savefig(
        output_dir / "charts" / workload / f"cost-effectiveness-{invocation_type}.png",
        dpi=CHART_DPI,
        bbox_inches="tight",
    )
    plt.close()


def create_runtime_family_p99_chart(
    aggregates: list[dict[str, Any]],
    workload: str,
    output_dir: Path,
) -> None:
    """
    Create P99 duration chart clustered by runtime family (Node.js, Python, future: Rust).

    Shows P99 warm start duration for each runtime version, grouped by family.
    Extensible for adding new runtime families like Rust or Go.

    Args:
        aggregates: List of aggregate statistics
        workload: Workload type (cpu-intensive, memory-intensive, light)
        output_dir: Output directory for charts
    """
    # Filter for warm starts only (most production-relevant)
    filtered = filter_aggregates(aggregates, workload_type=workload, invocation_type="warm", only_successful=True)

    if not filtered:
        return

    # Group data by runtime family and architecture
    family_data = defaultdict(lambda: {"arm64": {}, "x86": {}})

    for agg in filtered:
        runtime = agg["runtime"]
        arch = agg["architecture"]

        # Get runtime family (e.g., "nodejs20" -> "Node.js")
        family = RUNTIME_FAMILIES.get(runtime, runtime)

        # Get P99 across all memory configs for this runtime
        if runtime not in family_data[family][arch]:
            family_data[family][arch][runtime] = []

        family_data[family][arch][runtime].append(agg["durationStats"]["p99"])

    # Calculate average P99 for each runtime (across memory configs)
    chart_data = defaultdict(lambda: {"arm64": [], "x86": [], "labels": []})

    for family in sorted(family_data.keys()):
        for runtime in sorted(
            set(list(family_data[family]["arm64"].keys()) + list(family_data[family]["x86"].keys()))
        ):
            chart_data[family]["labels"].append(runtime)

            # ARM64
            if runtime in family_data[family]["arm64"]:
                avg_p99_arm = sum(family_data[family]["arm64"][runtime]) / len(
                    family_data[family]["arm64"][runtime]
                )
                chart_data[family]["arm64"].append(avg_p99_arm)
            else:
                chart_data[family]["arm64"].append(0)

            # x86
            if runtime in family_data[family]["x86"]:
                avg_p99_x86 = sum(family_data[family]["x86"][runtime]) / len(
                    family_data[family]["x86"][runtime]
                )
                chart_data[family]["x86"].append(avg_p99_x86)
            else:
                chart_data[family]["x86"].append(0)

    if not chart_data:
        return

    fig, ax = plt.subplots(figsize=(14, 8))

    num_families = len(chart_data)
    bar_width = BAR_WIDTH_STANDARD

    current_x = 0
    xtick_positions = []
    xtick_labels = []

    for family_idx, (family, data) in enumerate(sorted(chart_data.items())):
        num_runtimes = len(data["labels"])

        # Calculate positions for this family's bars
        x_positions = [current_x + i for i in range(num_runtimes)]

        # Plot ARM64 bars
        arm64_bars = ax.bar(
            [x - bar_width / 2 for x in x_positions],
            data["arm64"],
            bar_width,
            label=f"{family} ARM64",
            color=FAMILY_COLORS.get(family, "#999999"),
            alpha=0.8,
            edgecolor="black",
            linewidth=1.5,
        )

        # Plot x86 bars
        x86_bars = ax.bar(
            [x + bar_width / 2 for x in x_positions],
            data["x86"],
            bar_width,
            label=f"{family} x86",
            color=FAMILY_COLORS.get(family, "#999999"),
            alpha=0.4,
            edgecolor="black",
            linewidth=1.5,
            hatch="//",
        )

        # Add value labels on bars
        for bars in [arm64_bars, x86_bars]:
            for bar in bars:
                height = bar.get_height()
                if height > 0:
                    ax.text(
                        bar.get_x() + bar.get_width() / 2.0,
                        height,
                        f"{height:.0f}",
                        ha="center",
                        va="bottom",
                        fontsize=8,
                        fontweight="bold",
                    )

        # Store tick positions and labels
        xtick_positions.extend(x_positions)
        xtick_labels.extend(data["labels"])

        if family_idx < num_families - 1:
            current_x += num_runtimes + FAMILY_SPACING
            ax.axvline(
                x=current_x - FAMILY_SPACING / 2,
                color="gray",
                linestyle="--",
                linewidth=1,
                alpha=0.5,
            )
        else:
            current_x += num_runtimes

    ax.set_xlabel("Runtime", fontsize=13, fontweight="bold")
    ax.set_ylabel("P99 Duration (ms)", fontsize=13, fontweight="bold")
    ax.set_title(
        f"P99 Duration by Runtime Family: {format_workload_name(workload)} (Warm Starts)\n"
        f"Solid = ARM64, Hatched = x86 | Averaged across all memory configurations",
        fontsize=15,
        fontweight="bold",
    )

    ax.set_xticks(xtick_positions)
    ax.set_xticklabels(xtick_labels, rotation=45, ha="right")
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(axis="y", alpha=0.3, linestyle=":")

    plt.tight_layout()
    plt.savefig(
        output_dir / "charts" / workload / "runtime-family-p99-warm.png",
        dpi=CHART_DPI,
        bbox_inches="tight",
    )
    plt.close()


# =============================================================================
# Original Chart Functions (Kept for backwards compatibility)
# =============================================================================


def create_architecture_comparison_chart(
    aggregates: list[dict[str, Any]], workload: str, invocation_type: str, output_dir: Path
) -> None:
    """Create a chart comparing ARM64 vs x86 performance across runtimes."""
    filtered = filter_aggregates(
        aggregates, workload_type=workload, invocation_type=invocation_type, only_successful=True
    )

    if not filtered:
        return

    # Group by runtime
    runtimes = sorted({a["runtime"] for a in filtered})

    # Calculate average improvements
    improvements = []
    for runtime in runtimes:
        runtime_data = filter_aggregates(filtered, runtime=runtime)
        runtime_improvements = []

        for agg in runtime_data:
            if agg["architecture"] == "arm64":
                # Find matching x86 config
                x86_match = next(
                    (
                        a
                        for a in runtime_data
                        if a["architecture"] == "x86" and a["memorySizeMB"] == agg["memorySizeMB"]
                    ),
                    None,
                )
                if x86_match:
                    arm_duration = agg["durationStats"]["mean"]
                    x86_duration = x86_match["durationStats"]["mean"]
                    improvement = ((x86_duration - arm_duration) / x86_duration) * 100
                    runtime_improvements.append(improvement)

        if runtime_improvements:
            improvements.append(sum(runtime_improvements) / len(runtime_improvements))
        else:
            improvements.append(0)

    # Create bar chart
    fig, ax = plt.subplots(figsize=(10, 6))
    colors = ["#28a745" if x > 0 else "#dc3545" for x in improvements]
    bars = ax.bar(runtimes, improvements, color=colors, alpha=0.7, edgecolor="black")

    # Add value labels on bars
    for bar in bars:
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            height,
            f"{height:+.1f}%",
            ha="center",
            va="bottom" if height > 0 else "top",
            fontsize=10,
            fontweight="bold",
        )

    ax.axhline(y=0, color="black", linestyle="-", linewidth=0.5)
    ax.set_xlabel("Runtime", fontsize=12, fontweight="bold")
    ax.set_ylabel("Performance Improvement (%)", fontsize=12, fontweight="bold")
    ax.set_title(
        f"ARM64 vs x86 Performance - {format_workload_name(workload)} "
        f"({invocation_type.title()} Start)",
        fontsize=14,
        fontweight="bold",
    )
    ax.grid(axis="y", alpha=0.3)

    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig(
        output_dir / "charts" / f"arch-comparison-{workload}-{invocation_type}.png", dpi=300
    )
    plt.close()


def create_runtime_comparison_chart(
    aggregates: list[dict[str, Any]], architecture: str, invocation_type: str, output_dir: Path
) -> None:
    """Create a chart comparing different runtimes for a specific architecture."""
    filtered = filter_aggregates(
        aggregates, architecture=architecture, invocation_type=invocation_type, only_successful=True
    )

    if not filtered:
        return

    # Group by workload and runtime
    workloads = sorted({a["workloadType"] for a in filtered})
    runtimes = sorted({a["runtime"] for a in filtered})

    # Calculate average duration for each runtime/workload combo
    data = defaultdict(list)
    for workload in workloads:
        for runtime in runtimes:
            runtime_data = filter_aggregates(filtered, runtime=runtime, workload_type=workload)
            if runtime_data:
                avg_duration = sum(a["durationStats"]["mean"] for a in runtime_data) / len(
                    runtime_data
                )
                data[workload].append(avg_duration)
            else:
                data[workload].append(0)

    fig, ax = plt.subplots(figsize=(12, 6))
    x = range(len(runtimes))
    width = BAR_WIDTH_NARROW
    multiplier = 0

    colors = ["#007bff", "#ffc107", "#dc3545"]
    for workload, values in data.items():
        offset = width * multiplier
        bars = ax.bar(
            [i + offset for i in x],
            values,
            width,
            label=format_workload_name(workload),
            color=colors[multiplier % len(colors)],
            alpha=0.8,
            edgecolor="black",
        )

        # Add value labels
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2.0,
                    height,
                    f"{height:.1f}",
                    ha="center",
                    va="bottom",
                    fontsize=8,
                )

        multiplier += 1

    ax.set_xlabel("Runtime", fontsize=12, fontweight="bold")
    ax.set_ylabel("Average Duration (ms)", fontsize=12, fontweight="bold")
    ax.set_title(
        f"Runtime Performance Comparison - {architecture.upper()} "
        f"({invocation_type.title()} Start)",
        fontsize=14,
        fontweight="bold",
    )
    ax.set_xticks([i + width for i in x])
    ax.set_xticklabels(runtimes, rotation=45, ha="right")
    ax.legend(loc="upper left")
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    plt.savefig(
        output_dir / "charts" / f"runtime-comparison-{architecture}-{invocation_type}.png",
        dpi=CHART_DPI,
    )
    plt.close()


def create_cold_start_analysis_chart(aggregates: list[dict[str, Any]], output_dir: Path) -> None:
    """Create a chart analyzing cold start initialization times."""
    cold_starts = filter_aggregates(aggregates, invocation_type="cold")

    if not cold_starts:
        return

    # Group by runtime and architecture
    data = defaultdict(lambda: defaultdict(list))
    for agg in cold_starts:
        if "initDurationStats" in agg:
            runtime = agg["runtime"]
            arch = agg["architecture"]
            init_mean = agg["initDurationStats"]["mean"]
            data[runtime][arch].append(init_mean)

    # Calculate averages
    runtimes = sorted(data.keys())
    arm64_inits = []
    x86_inits = []

    for runtime in runtimes:
        arm64_values = data[runtime].get("arm64", [])
        x86_values = data[runtime].get("x86", [])

        arm64_inits.append(sum(arm64_values) / len(arm64_values) if arm64_values else 0)
        x86_inits.append(sum(x86_values) / len(x86_values) if x86_values else 0)

    fig, ax = plt.subplots(figsize=(10, 6))
    x = range(len(runtimes))
    width = BAR_WIDTH_STANDARD

    bars1 = ax.bar(
        [i - width / 2 for i in x],
        arm64_inits,
        width,
        label="ARM64",
        color="#28a745",
        alpha=0.8,
        edgecolor="black",
    )
    bars2 = ax.bar(
        [i + width / 2 for i in x],
        x86_inits,
        width,
        label="x86",
        color="#007bff",
        alpha=0.8,
        edgecolor="black",
    )

    # Add value labels
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2.0,
                    height,
                    f"{height:.1f}",
                    ha="center",
                    va="bottom",
                    fontsize=9,
                )

    ax.set_xlabel("Runtime", fontsize=12, fontweight="bold")
    ax.set_ylabel("Average Init Duration (ms)", fontsize=12, fontweight="bold")
    ax.set_title("Cold Start Initialization Time Comparison", fontsize=14, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(runtimes, rotation=45, ha="right")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_dir / "charts" / "cold-start-analysis.png", dpi=300)
    plt.close()


def create_memory_impact_chart(
    aggregates: list[dict[str, Any]], workload: str, runtime: str, output_dir: Path
) -> None:
    """Create a chart showing the impact of memory configuration on performance."""
    filtered = filter_aggregates(
        aggregates, workload_type=workload, runtime=runtime, invocation_type="warm", only_successful=True
    )

    if not filtered:
        return

    # Group by architecture and memory
    data = defaultdict(lambda: defaultdict(float))
    for agg in filtered:
        memory = agg["memorySizeMB"]
        arch = agg["architecture"]
        duration = agg["durationStats"]["mean"]
        data[arch][memory] = duration

    # Create line chart
    fig, ax = plt.subplots(figsize=(10, 6))

    for arch, color in [("arm64", "#28a745"), ("x86", "#007bff")]:
        if arch in data:
            memories = sorted(data[arch].keys())
            durations = [data[arch][m] for m in memories]

            ax.plot(
                memories,
                durations,
                marker="o",
                linewidth=2,
                markersize=8,
                label=arch.upper(),
                color=color,
            )

            # Add value labels
            for x, y in zip(memories, durations, strict=False):
                ax.annotate(
                    f"{y:.1f}",
                    xy=(x, y),
                    xytext=(0, 10),
                    textcoords="offset points",
                    ha="center",
                    fontsize=8,
                )

    ax.set_xlabel("Memory Configuration (MB)", fontsize=12, fontweight="bold")
    ax.set_ylabel("Duration (ms)", fontsize=12, fontweight="bold")
    ax.set_title(
        f"Memory Configuration Impact - {runtime} {format_workload_name(workload)}",
        fontsize=14,
        fontweight="bold",
    )
    ax.legend()
    ax.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_dir / "charts" / f"memory-impact-{workload}-{runtime}.png", dpi=300)
    plt.close()


def create_cost_vs_performance_scatter(
    aggregates: list[dict[str, Any]],
    workload: str,
    invocation_type: str,
    output_dir: Path,
    region: str = DEFAULT_REGION,
) -> None:
    """
    Create scatter plot showing cost vs performance trade-offs.
    Bottom-left corner = best (fast and cheap).
    """
    filtered = filter_aggregates(
        aggregates, workload_type=workload, invocation_type=invocation_type, only_successful=True
    )

    if not filtered:
        return

    fig, ax = plt.subplots(figsize=(12, 8))

    # Plot each configuration as a point
    for agg in filtered:
        runtime = agg["runtime"]
        arch = agg["architecture"]
        memory = agg["memorySizeMB"]

        # Calculate cost per 1M invocations
        cost = calculate_invocation_cost(
            agg["billedDurationStats"]["mean"], memory, arch, region
        )
        cost_per_million = cost * 1_000_000

        # Get duration (include init for cold starts)
        duration = agg["durationStats"]["mean"]
        if invocation_type == "cold" and "initDurationStats" in agg:
            duration += agg["initDurationStats"]["mean"]

        # Get runtime family for coloring
        family = RUNTIME_FAMILIES.get(runtime, "Unknown")
        color = FAMILY_COLORS.get(family, "#999999")

        # Use different markers for architectures
        marker = "o" if arch == "arm64" else "s"
        alpha = 0.7 if arch == "arm64" else 0.5

        ax.scatter(
            duration,
            cost_per_million,
            color=color,
            marker=marker,
            s=100,
            alpha=alpha,
            edgecolors="black",
            linewidths=1,
            label=f"{family} {arch.upper()}" if agg == filtered[0] else "",
        )

        # Annotate with memory size (only for extreme values to avoid clutter)
        if memory in [128, 8192] or (memory == 1769 and duration < 100):
            ax.annotate(
                f"{memory}MB",
                (duration, cost_per_million),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=7,
                alpha=0.6,
            )

    # Create custom legend
    from matplotlib.lines import Line2D
    legend_elements = []
    for family in sorted(set(RUNTIME_FAMILIES.values())):
        if any(RUNTIME_FAMILIES.get(a["runtime"]) == family for a in filtered):
            color = FAMILY_COLORS.get(family, "#999999")
            legend_elements.append(Line2D([0], [0], marker="o", color="w",
                                         markerfacecolor=color, markersize=10,
                                         label=f"{family} ARM64", markeredgecolor="black"))
            legend_elements.append(Line2D([0], [0], marker="s", color="w",
                                         markerfacecolor=color, markersize=10, alpha=0.5,
                                         label=f"{family} x86", markeredgecolor="black"))

    ax.legend(handles=legend_elements, loc="upper right", fontsize=9)

    ax.set_xlabel("Duration (ms)" + (" [init + execution]" if invocation_type == "cold" else ""),
                  fontsize=12, fontweight="bold")
    ax.set_ylabel("Cost per 1M Invocations ($)", fontsize=12, fontweight="bold")
    ax.set_title(
        f"Cost vs Performance - {format_workload_name(workload)} ({invocation_type.title()} Starts)\n"
        f"Bottom-left corner = best value (fast and cheap)",
        fontsize=14,
        fontweight="bold",
    )
    ax.grid(alpha=0.3, linestyle=":")

    plt.tight_layout()
    chart_path = output_dir / "charts" / workload / f"cost-vs-performance-{invocation_type}.png"
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(chart_path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close()


def create_cost_savings_heatmap(
    aggregates: list[dict[str, Any]],
    workload: str,
    invocation_type: str,
    output_dir: Path,
    region: str = DEFAULT_REGION,
) -> None:
    """
    Create heatmap showing ARM64 vs x86 cost savings percentage.
    Positive values (green) = ARM64 is cheaper
    Negative values (red) = x86 is cheaper
    """
    filtered = filter_aggregates(
        aggregates, workload_type=workload, invocation_type=invocation_type, only_successful=True
    )

    if not filtered:
        return

    import numpy as np

    # Organize data: runtime x memory
    runtimes = sorted({a["runtime"] for a in filtered})
    memories = sorted({a["memorySizeMB"] for a in filtered})

    # Create matrix: rows=runtimes, cols=memories, values=% savings
    matrix = []
    for runtime in runtimes:
        row = []
        for memory in memories:
            # Get ARM64 and x86 costs for this config
            arm64_agg = next(
                (a for a in filtered
                 if a["runtime"] == runtime and a["memorySizeMB"] == memory and a["architecture"] == "arm64"),
                None,
            )
            x86_agg = next(
                (a for a in filtered
                 if a["runtime"] == runtime and a["memorySizeMB"] == memory and a["architecture"] == "x86"),
                None,
            )

            if arm64_agg and x86_agg:
                # Calculate costs
                arm64_cost = calculate_invocation_cost(
                    arm64_agg["billedDurationStats"]["mean"], memory, "arm64", region
                ) * 1_000_000
                x86_cost = calculate_invocation_cost(
                    x86_agg["billedDurationStats"]["mean"], memory, "x86", region
                ) * 1_000_000

                # Calculate savings: positive = ARM64 cheaper, negative = x86 cheaper
                savings_pct = ((x86_cost - arm64_cost) / x86_cost) * 100
                row.append(savings_pct)
            else:
                row.append(float("nan"))
        matrix.append(row)

    # Create heatmap
    fig, ax = plt.subplots(figsize=(14, 7))
    matrix_array = np.array(matrix)

    # Use diverging colormap: green for ARM64 wins, red for x86 wins
    im = ax.imshow(matrix_array, cmap="RdYlGn", aspect="auto", vmin=-30, vmax=30)

    # Set ticks
    ax.set_xticks(range(len(memories)))
    ax.set_yticks(range(len(runtimes)))
    ax.set_xticklabels([f"{m}MB" for m in memories], rotation=45, ha="right")
    ax.set_yticklabels(runtimes)

    # Add percentage values to cells
    for i in range(len(runtimes)):
        for j in range(len(memories)):
            if not np.isnan(matrix_array[i, j]):
                value = matrix_array[i, j]
                # Use white text on dark cells, black on light cells
                text_color = "white" if abs(value) > 15 else "black"
                ax.text(
                    j,
                    i,
                    f"{value:+.1f}%",
                    ha="center",
                    va="center",
                    color=text_color,
                    fontsize=9,
                    fontweight="bold" if abs(value) > 10 else "normal",
                )

    # Colorbar
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label("Cost Savings % (ARM64 vs x86)\nGreen = ARM64 cheaper",
                   rotation=270, labelpad=25, fontsize=10)

    ax.set_title(
        f"ARM64 vs x86 Cost Savings - {format_workload_name(workload)} ({invocation_type.title()} Starts)\n"
        f"Positive % (green) = ARM64 is cheaper | Negative % (red) = x86 is cheaper",
        fontsize=13,
        fontweight="bold",
        pad=20,
    )
    ax.set_xlabel("Memory Configuration", fontsize=12, fontweight="bold")
    ax.set_ylabel("Runtime", fontsize=12, fontweight="bold")

    plt.tight_layout()
    chart_path = output_dir / "charts" / workload / f"cost-savings-{invocation_type}.png"
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(chart_path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close()


def create_memory_scaling_efficiency_chart(
    aggregates: list[dict[str, Any]], workload: str, invocation_type: str, output_dir: Path
) -> None:
    """
    Chart showing performance gain per memory doubling.
    Higher = better scaling efficiency.
    """
    filtered = filter_aggregates(
        aggregates, workload_type=workload, invocation_type=invocation_type, only_successful=True
    )

    if not filtered:
        return

    fig, ax = plt.subplots(figsize=(14, 8))

    # Process each runtime/arch combo
    for runtime in sorted({a["runtime"] for a in filtered}):
        for arch in ["arm64", "x86"]:
            combo_data = filter_aggregates(filtered, runtime=runtime, architecture=arch)
            if not combo_data:
                continue

            # Sort by memory
            combo_data = sorted(combo_data, key=lambda x: x["memorySizeMB"])

            # Calculate efficiency between consecutive memory levels
            efficiencies = []
            memory_labels = []

            for i in range(len(combo_data) - 1):
                curr = combo_data[i]
                next_item = combo_data[i + 1]

                curr_dur = curr["durationStats"]["mean"]
                next_dur = next_item["durationStats"]["mean"]

                # Performance improvement (%)
                improvement = ((curr_dur - next_dur) / curr_dur) * 100

                # Memory multiplier
                memory_mult = next_item["memorySizeMB"] / curr["memorySizeMB"]

                # Efficiency = improvement per memory multiplier
                efficiency = improvement / memory_mult

                efficiencies.append(efficiency)
                memory_labels.append(f"{curr['memorySizeMB']}→{next_item['memorySizeMB']}")

            if efficiencies:
                label = f"{runtime} {arch}"
                color = RUNTIME_COLORS.get(runtime, "#999999")
                linestyle = "-" if arch == "arm64" else "--"

                ax.plot(
                    range(len(efficiencies)),
                    efficiencies,
                    marker="o",
                    label=label,
                    color=color,
                    linestyle=linestyle,
                    linewidth=2,
                    markersize=6,
                )

    ax.set_xticks(range(len(memory_labels)))
    ax.set_xticklabels(memory_labels, rotation=45, ha="right")
    ax.set_xlabel("Memory Transition (MB)", fontsize=12, fontweight="bold")
    ax.set_ylabel("Scaling Efficiency (%/x)", fontsize=12, fontweight="bold")
    ax.set_title(
        f"Memory Scaling Efficiency - {format_workload_name(workload)} ({invocation_type.title()})",
        fontsize=14,
        fontweight="bold",
    )
    ax.legend(bbox_to_anchor=(1.05, 1), loc="upper left", fontsize=9)
    ax.grid(alpha=0.3)
    ax.axhline(y=0, color="black", linestyle="-", linewidth=0.5)

    plt.tight_layout()
    chart_path = output_dir / "charts" / workload / f"scaling-efficiency-{invocation_type}.png"
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(chart_path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close()


def create_runtime_version_comparison_chart(
    aggregates: list[dict[str, Any]], output_dir: Path
) -> None:
    """Compare different versions of Node.js, Python, and Rust runtimes."""
    warm_aggs = filter_aggregates(aggregates, invocation_type="warm", only_successful=True)

    if not warm_aggs:
        return

    # Group by runtime family
    nodejs_runtimes = ["nodejs20", "nodejs22"]
    python_runtimes = ["python3.11", "python3.12", "python3.13"]
    rust_runtimes = ["rust"]

    for family_name, runtimes in [("Node.js", nodejs_runtimes), ("Python", python_runtimes), ("Rust", rust_runtimes)]:
        # Get all workloads and memory sizes for this family
        family_data = [a for a in warm_aggs if a["runtime"] in runtimes]
        if not family_data:
            continue

        workloads = sorted({a["workloadType"] for a in family_data})

        fig, axes = plt.subplots(1, len(workloads), figsize=(16, 6))
        if len(workloads) == 1:
            axes = [axes]

        for idx, workload in enumerate(workloads):
            ax = axes[idx]
            workload_data = [a for a in family_data if a["workloadType"] == workload]

            # For each runtime version, calculate average duration across all memory sizes/archs
            runtime_avgs = {}
            for runtime in runtimes:
                runtime_data = [a for a in workload_data if a["runtime"] == runtime]
                if runtime_data:
                    avg_dur = sum(a["durationStats"]["mean"] for a in runtime_data) / len(
                        runtime_data
                    )
                    runtime_avgs[runtime] = avg_dur

            if runtime_avgs:
                x = list(runtime_avgs.keys())
                y = list(runtime_avgs.values())

                bars = ax.bar(x, y, color=[RUNTIME_COLORS.get(r, "#999") for r in x])

                # Add value labels
                for bar in bars:
                    height = bar.get_height()
                    ax.text(
                        bar.get_x() + bar.get_width() / 2.0,
                        height,
                        f"{height:.1f}ms",
                        ha="center",
                        va="bottom",
                        fontsize=10,
                        fontweight="bold",
                    )

                ax.set_ylabel("Avg Duration (ms)", fontsize=10, fontweight="bold")
                ax.set_title(format_workload_name(workload), fontsize=12, fontweight="bold")
                ax.grid(axis="y", alpha=0.3)

        fig.suptitle(
            f"{family_name} Runtime Version Comparison (Warm Starts)", fontsize=14, fontweight="bold"
        )
        plt.tight_layout()
        chart_path = output_dir / "charts" / f"runtime-version-comparison-{family_name.lower()}.png"
        plt.savefig(chart_path, dpi=CHART_DPI, bbox_inches="tight")
        plt.close()


def create_performance_consistency_chart(
    aggregates: list[dict[str, Any]], workload: str, invocation_type: str, output_dir: Path
) -> None:
    """
    Chart showing performance consistency (P99/Mean ratio).
    Lower ratio = more consistent performance.
    """
    filtered = filter_aggregates(
        aggregates, workload_type=workload, invocation_type=invocation_type, only_successful=True
    )

    if not filtered:
        return

    fig, ax = plt.subplots(figsize=(14, 8))

    # Process each runtime/arch combo
    for runtime in sorted({a["runtime"] for a in filtered}):
        for arch in ["arm64", "x86"]:
            combo_data = filter_aggregates(filtered, runtime=runtime, architecture=arch)
            if not combo_data:
                continue

            # Sort by memory
            combo_data = sorted(combo_data, key=lambda x: x["memorySizeMB"])

            memories = []
            consistency_ratios = []

            for agg in combo_data:
                mean = agg["durationStats"].get("mean")
                p99 = agg["durationStats"].get("p99")

                if mean and p99 and mean > 0:
                    ratio = p99 / mean
                    memories.append(agg["memorySizeMB"])
                    consistency_ratios.append(ratio)

            if consistency_ratios:
                label = f"{runtime} {arch}"
                color = RUNTIME_COLORS.get(runtime, "#999999")
                linestyle = "-" if arch == "arm64" else "--"

                ax.plot(
                    memories,
                    consistency_ratios,
                    marker="o",
                    label=label,
                    color=color,
                    linestyle=linestyle,
                    linewidth=2,
                    markersize=6,
                )

    ax.set_xlabel("Memory (MB)", fontsize=12, fontweight="bold")
    ax.set_ylabel("Consistency Ratio (P99/Mean)", fontsize=12, fontweight="bold")
    ax.set_title(
        f"Performance Consistency - {format_workload_name(workload)} ({invocation_type.title()})\n(Lower is better)",
        fontsize=14,
        fontweight="bold",
    )
    ax.legend(bbox_to_anchor=(1.05, 1), loc="upper left", fontsize=9)
    ax.grid(alpha=0.3)
    ax.axhline(y=1.0, color="green", linestyle="--", linewidth=1, alpha=0.5, label="Perfect (1.0)")

    plt.tight_layout()
    chart_path = output_dir / "charts" / workload / f"consistency-{invocation_type}.png"
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(chart_path, dpi=CHART_DPI, bbox_inches="tight")
    plt.close()


def main() -> None:
    """Main entry point for benchmark results analysis."""
    parser = argparse.ArgumentParser(
        description="Analyze Lambda benchmark results and generate reports with visualizations"
    )
    parser.add_argument("test_run_id", help="UUID of the test run to analyze")
    parser.add_argument("--runtime", help="Filter by runtime (e.g., python3.13, nodejs20)")
    parser.add_argument(
        "--workload",
        help="Filter by workload type (cpu-intensive, memory-intensive, light)",
    )
    parser.add_argument("--architecture", help="Filter by architecture (arm64, x86)")

    args = parser.parse_args()

    log.info(f"Analyzing test run: {args.test_run_id}")
    log.info("=" * 80)

    # Get test run info
    test_run_info = get_test_run_info(args.test_run_id)

    # Fetch aggregates
    log.info("Fetching aggregate statistics from DynamoDB...")
    aggregates = get_all_aggregates(args.test_run_id)
    log.info(f"Retrieved {len(aggregates)} aggregate items")

    if not aggregates:
        log.error("No aggregates found for this test run.")
        sys.exit(1)

    # Apply filters if specified
    original_count = len(aggregates)
    if args.runtime or args.workload or args.architecture:
        aggregates = filter_aggregates(
            aggregates,
            runtime=args.runtime,
            workload_type=args.workload,
            architecture=args.architecture,
        )
        log.info(f"Filtered to {len(aggregates)} aggregates (from {original_count})")

    # Get region from test run info with fallback
    if test_run_info:
        region = test_run_info.get("region", DEFAULT_REGION)
    else:
        region = DEFAULT_REGION
        log.warning(f"Test run metadata not available, using default region: {DEFAULT_REGION}")

    # Use effective region for pricing if region not in pricing table
    effective_region = region if region in AWS_PRICING else DEFAULT_REGION
    if effective_region != region:
        log.warning(
            f"Region {region} not in pricing table, using {effective_region} for cost calculations"
        )

    # Get unique workloads
    workloads = sorted({a["workloadType"] for a in aggregates})

    # Create output directory with region in folder name
    log.info(f"Creating output directory: results/{args.test_run_id}-{region}/")
    output_dir = create_output_directory(args.test_run_id, region, workloads)

    # Generate summary
    log.info("Generating summary...")
    generate_summary_markdown(test_run_info, aggregates, output_dir)

    # Generate comparison tables
    log.info("Generating comparison tables with cost analysis...")
    for workload in workloads:
        for invocation_type in ["cold", "warm"]:
            generate_comparison_table(
                aggregates, workload, invocation_type, output_dir, effective_region
            )

    # Generate charts
    log.info("Generating charts...")
    log.info("  - Memory scaling charts (6 charts: all runtimes/architectures on one chart)")
    for workload in workloads:
        for invocation_type in ["cold", "warm"]:
            create_memory_scaling_chart(aggregates, workload, invocation_type, output_dir)

    log.info("  - Node.js & Rust comparison charts (6 charts: focused view without Python)")
    for workload in workloads:
        for invocation_type in ["cold", "warm"]:
            create_nodejs_rust_comparison_chart(aggregates, workload, invocation_type, output_dir)

    log.info("  - Python version comparison charts (6 charts: all Python versions)")
    for workload in workloads:
        for invocation_type in ["cold", "warm"]:
            create_python_comparison_chart(aggregates, workload, invocation_type, output_dir)

    log.info("  - Node.js version comparison charts (6 charts: Node.js 20 vs 22)")
    for workload in workloads:
        for invocation_type in ["cold", "warm"]:
            create_nodejs_comparison_chart(aggregates, workload, invocation_type, output_dir)

    log.info("  - P99 duration scaling charts (6 charts: cold and warm starts)")
    for workload in workloads:
        for invocation_type in ["cold", "warm"]:
            create_p99_scaling_chart(aggregates, workload, invocation_type, output_dir)

    log.info("  - Runtime family P99 charts (3 charts: clustered by Node.js vs Python)")
    for workload in workloads:
        create_runtime_family_p99_chart(aggregates, workload, output_dir)

    log.info("  - Cold start analysis")
    create_cold_start_analysis_chart(aggregates, output_dir)

    # New advanced analysis charts
    log.info("  - Cost vs Performance scatter plots (value analysis)")
    for workload in workloads:
        for invocation_type in ["cold", "warm"]:
            create_cost_vs_performance_scatter(aggregates, workload, invocation_type, output_dir, effective_region)

    log.info("  - Cost savings heatmaps (ARM64 vs x86 comparison)")
    for workload in workloads:
        for invocation_type in ["cold", "warm"]:
            create_cost_savings_heatmap(aggregates, workload, invocation_type, output_dir, effective_region)

    log.info("  - Memory scaling efficiency charts (diminishing returns analysis)")
    for workload in workloads:
        for invocation_type in ["cold", "warm"]:
            create_memory_scaling_efficiency_chart(aggregates, workload, invocation_type, output_dir)

    log.info("  - Runtime version comparison (Node.js 20 vs 22, Python 3.11-3.13)")
    create_runtime_version_comparison_chart(aggregates, output_dir)

    log.info("  - Performance consistency charts (P99/Mean ratio)")
    for workload in workloads:
        for invocation_type in ["cold", "warm"]:
            create_performance_consistency_chart(aggregates, workload, invocation_type, output_dir)

    # REMOVED: Architecture comparison charts - replaced by memory scaling charts
    # REMOVED: Runtime comparison charts - replaced by memory scaling charts
    # REMOVED: Old memory impact charts - replaced by memory scaling charts
    # The new memory scaling charts show all runtimes, architectures, and memory configs on one chart

    log.info("")
    log.info("=" * 80)
    log.info(f"Analysis complete! Results saved to: {output_dir.absolute()}")
    log.info(f"- Summary: {output_dir / 'README.md'}")
    log.info(f"- Tables: {output_dir / 'tables'}/")
    log.info(f"- Charts: {output_dir / 'charts'}/")
    log.info("=" * 80)


if __name__ == "__main__":
    main()
