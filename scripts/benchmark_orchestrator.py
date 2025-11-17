#!/usr/bin/env python3
"""
Lambda ARM vs x86 Benchmark Orchestrator

Orchestrates benchmark execution across all deployed Lambda functions, testing
performance across different runtimes, architectures, workloads, and memory configurations.

Key Features:
- Forced cold starts via configuration updates
- Zero-overhead metrics collection via CloudWatch REPORT line parsing
- Parallel execution with configurable workers
- Complete test matrix tracking in DynamoDB
- Test and production modes for quick validation vs comprehensive analysis
"""

import base64
import json
import logging
import os
import re
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import boto3
from benchmark_utils import (
    CPU_INTENSIVE_ITERATIONS,
    MEMORY_CONFIGS,
    RESULTS_TABLE_NAME,
    calculate_statistics,
    make_config_id,
    map_decimal,
    to_decimal,
)
from botocore.config import Config
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

BOTO_CONFIG = Config(
    region_name=os.environ.get("AWS_REGION", "us-east-2"),  # Support EC2 execution and local
    retries={"max_attempts": 10, "mode": "standard"},
    max_pool_connections=50,  # High limit for parallel execution (up to 12 workers)
    read_timeout=250,  # Must exceed Lambda timeout (240s) to handle slow executions at low memory
    connect_timeout=20,
)

# Thread-local storage for boto3 clients (thread-safe for parallel execution)
thread_local = threading.local()


def get_lambda_client():
    """Get thread-local Lambda client for thread-safe parallel execution."""
    if not hasattr(thread_local, "lambda_client"):
        thread_local.lambda_client = boto3.client("lambda", config=BOTO_CONFIG)
    return thread_local.lambda_client


def get_dynamodb_resource():
    """Get thread-local DynamoDB resource for thread-safe parallel execution."""
    if not hasattr(thread_local, "dynamodb"):
        thread_local.dynamodb = boto3.resource("dynamodb", config=BOTO_CONFIG)
    return thread_local.dynamodb


def get_cloudformation_client():
    """Get thread-local CloudFormation client for thread-safe parallel execution."""
    if not hasattr(thread_local, "cfn_client"):
        thread_local.cfn_client = boto3.client("cloudformation", config=BOTO_CONFIG)
    return thread_local.cfn_client


AWS_REGION = (
    boto3.session.Session().region_name or "us-east-2"
)  # Changed from us-east-1 to match project default
STACK_NAME = "LambdaBenchmarkStack"

# =============================================================================
# Benchmark Constants
# =============================================================================

# Lambda Memory Configuration
LAMBDA_MEMORY_MIN_MB = 128  # AWS Lambda minimum memory
LAMBDA_MEMORY_MAX_MB = 10240  # AWS Lambda maximum memory
LAMBDA_MEMORY_TOGGLE_MB = 64  # Memory change for forced cold start toggle

# Timing Configuration
COLD_START_STABILIZATION_DELAY_SECONDS = (
    0.05  # Wait time after config update for Lambda environment teardown
)

# Retry Configuration
LAMBDA_INVOKE_MAX_RETRIES = 3  # Max retry attempts for throttled invocations
LAMBDA_INVOKE_BACKOFF_BASE_SECONDS = 1  # Base for exponential backoff (1s, 2s, 4s)


# =============================================================================
# Configuration
# =============================================================================


@dataclass(slots=True)
class BenchmarkConfig:
    """Configuration for benchmark execution."""

    cold_starts_per_config: int = 3
    warm_starts_per_config: int = 10
    memory_configs_to_test: list[int] | None = None
    max_workers: int = 12


TEST_CONFIG = BenchmarkConfig(
    cold_starts_per_config=2,
    warm_starts_per_config=2,
    memory_configs_to_test=None,  # Use per-workload MEMORY_CONFIGS from benchmark_utils
)

BALANCED_CONFIG = BenchmarkConfig(
    cold_starts_per_config=10,
    warm_starts_per_config=20,
    memory_configs_to_test=None,  # Use per-workload MEMORY_CONFIGS from benchmark_utils
)

PRODUCTION_CONFIG = BenchmarkConfig(
    cold_starts_per_config=125,
    warm_starts_per_config=500,
    memory_configs_to_test=None,  # Use per-workload MEMORY_CONFIGS from benchmark_utils
)


# =============================================================================
# Utility Functions (Test Matrix and Parsing)
# =============================================================================


def build_test_matrix(test_configs: list[tuple[dict[str, str], int]]) -> dict[str, Any]:
    """
    Build structured test matrix from test configurations.

    Groups configurations by (runtime, architecture, workloadType) and aggregates
    memory sizes for each unique combination.
    """
    config_groups = defaultdict(list)
    runtimes = set()
    architectures = set()
    workload_types = set()

    for func_info, memory_mb in test_configs:
        runtime = func_info["runtime"]
        architecture = func_info["architecture"]
        workload_type = func_info["workloadType"]

        runtimes.add(runtime)
        architectures.add(architecture)
        workload_types.add(workload_type)

        key = (runtime, architecture, workload_type)
        if memory_mb not in config_groups[key]:
            config_groups[key].append(memory_mb)

    configurations = []
    for (runtime, architecture, workload_type), memory_sizes in sorted(config_groups.items()):
        configurations.append(
            {
                "runtime": runtime,
                "architecture": architecture,
                "workloadType": workload_type,
                "memorySizes": sorted(memory_sizes),
            }
        )

    return {
        "runtimes": sorted(runtimes),
        "architectures": sorted(architectures),
        "workloadTypes": sorted(workload_types),
        "configurations": configurations,
    }


def parse_function_name(name: str) -> tuple[str, str, str]:
    """
    Parse Lambda function name to extract runtime, architecture, and workload type.

    Supports naming patterns:
    - python{version}-{digit}-{arch}-{workload}  (e.g., python3-13-arm64-cpu-intensive)
    - {runtime}-{arch}-{workload}                (e.g., nodejs22-arm64-light, rust-arm64-cpu-intensive)

    Returns:
        Tuple of (runtime, architecture, workload_type)

    Raises:
        ValueError: If function name doesn't match expected pattern
    """
    pattern = r"^(python\d+-\d+|nodejs\d+|rust)-(arm64|x86)-([\w-]+)$"
    match = re.match(pattern, name)

    if not match:
        # Fallback to legacy parsing for backward compatibility
        parts = name.split("-")
        if name.startswith("python"):
            runtime = f"{parts[0]}.{parts[1]}"
            arch = parts[2]
            workload = "-".join(parts[3:])
        else:
            runtime = parts[0]
            arch = parts[1]
            workload = "-".join(parts[2:])
        return runtime, arch, workload

    runtime_raw, arch, workload = match.groups()
    runtime = runtime_raw.replace("-", ".") if "python" in runtime_raw else runtime_raw
    return runtime, arch, workload


def parse_cloudwatch_report(log_result: str) -> dict[str, Any]:
    """
    Parse CloudWatch REPORT line from Lambda log output.

    Extracts:
    - Duration (ms)
    - Billed Duration (ms)
    - Memory Used (MB)
    - Init Duration (ms, cold starts only)
    - Lambda Request ID
    """
    if not log_result:
        return {}

    log_text = base64.b64decode(log_result).decode("utf-8")

    report_match = re.search(r"REPORT RequestId:\s+([a-f0-9-]+).*", log_text)
    if not report_match:
        return {}

    report_line = report_match.group(0)
    result = {"lambda_request_id": report_match.group(1)}

    duration_match = re.search(r"Duration:\s+([\d.]+)\s+ms", report_line)
    if duration_match:
        result["duration_ms"] = float(duration_match.group(1))

    billed_match = re.search(r"Billed Duration:\s+(\d+)\s+ms", report_line)
    if billed_match:
        result["billed_duration_ms"] = int(billed_match.group(1))

    memory_match = re.search(r"Max Memory Used:\s+(\d+)\s+MB", report_line)
    if memory_match:
        result["memory_used_mb"] = int(memory_match.group(1))

    init_match = re.search(r"Init Duration:\s+([\d.]+)\s+ms", report_line)
    if init_match:
        result["init_duration_ms"] = float(init_match.group(1))

    return result


def build_workload_payload(workload_type: str, memory_mb: int) -> dict:
    """
    Build invocation payload based on workload type.

    Note: memory-intensive workload uses fixed 100 MB array (hardcoded in handlers),
    so no payload needed. Keeping function signature for consistency.
    """
    if workload_type == "cpu-intensive":
        return {"iterations": CPU_INTENSIVE_ITERATIONS}
    return {}


# =============================================================================
# AWS Infrastructure Functions (Read State)
# =============================================================================


def get_deployed_functions(name_filter: str | None = None) -> list[dict[str, str]]:
    """
    Get all deployed Lambda functions from CloudFormation stack.

    Queries CloudFormation stack resources to discover Lambda functions, then fetches
    configuration details for each. This approach avoids creating CloudFormation outputs.
    """
    log.info(f"Discovering functions from stack: {STACK_NAME}")

    cfn_client = get_cloudformation_client()
    lambda_client = get_lambda_client()

    # List all resources in the stack with pagination support
    function_names = set()
    next_token = None

    try:
        while True:
            if next_token:
                response = cfn_client.list_stack_resources(
                    StackName=STACK_NAME, NextToken=next_token
                )
            else:
                response = cfn_client.list_stack_resources(StackName=STACK_NAME)

            # Filter for Lambda functions (PhysicalResourceId is the function name)
            for resource in response["StackResourceSummaries"]:
                if resource["ResourceType"] == "AWS::Lambda::Function":
                    function_names.add(resource["PhysicalResourceId"])

            # Check for more pages
            next_token = response.get("NextToken")
            if not next_token:
                break

    except ClientError as e:
        log.error(f"Failed to list stack resources for {STACK_NAME}: {e}")
        return []

    # Warn if no functions found
    if not function_names:
        log.warning(f"No Lambda functions found in stack {STACK_NAME}")
        return []

    functions = []
    for name in sorted(function_names):
        if name_filter and name_filter not in name:
            continue

        response = lambda_client.get_function_configuration(FunctionName=name)
        runtime, arch, workload = parse_function_name(name)

        functions.append(
            {
                "name": name,
                "runtime": runtime,
                "architecture": arch,
                "workloadType": workload,
                "currentMemoryMB": response["MemorySize"],
                "timeout": response["Timeout"],
                "version": response["Version"],
            }
        )

    log.info(f"Found {len(functions)} functions")
    return functions


def get_memory_configs_for_workload(workload_type: str, config: BenchmarkConfig) -> list[int]:
    """
    Get memory configurations to test for a specific workload type.

    Memory ranges follow powers of 2 + 1769 MB (1 vCPU sweet spot):
    - cpu-intensive: Up to 8192 MB
    - memory-intensive: Up to 10240 MB (full Lambda memory range)
    - light: Up to 8192 MB
    """
    configs = MEMORY_CONFIGS.get(workload_type, [1769])

    if config.memory_configs_to_test:
        configs = [m for m in configs if m in config.memory_configs_to_test]

    return configs


# =============================================================================
# AWS Mutation Functions (Modify Resources)
# =============================================================================


def force_cold_start(function_name: str, memory_mb: int) -> None:
    """
    Force a cold start by updating Lambda function configuration.

    Uses the "toggle technique" to force Lambda to tear down the execution environment.
    Reduces test time from 60-120 hours to ~10 hours by avoiding 15+ minute waits.
    """
    lambda_client = get_lambda_client()
    current_config = lambda_client.get_function_configuration(FunctionName=function_name)
    current_memory = current_config["MemorySize"]

    if current_memory == memory_mb:
        # Toggle memory to force cold start (Lambda tears down environment on config change)
        if memory_mb >= LAMBDA_MEMORY_MAX_MB:
            temp_memory = memory_mb - LAMBDA_MEMORY_TOGGLE_MB  # Decrement from max
        else:
            temp_memory = memory_mb + LAMBDA_MEMORY_TOGGLE_MB  # Normal toggle
        temp_memory = max(
            LAMBDA_MEMORY_MIN_MB, min(LAMBDA_MEMORY_MAX_MB, temp_memory)
        )  # Safety clamp

        lambda_client.update_function_configuration(
            FunctionName=function_name, MemorySize=temp_memory
        )

        waiter = lambda_client.get_waiter("function_updated")
        waiter.wait(FunctionName=function_name)
        time.sleep(COLD_START_STABILIZATION_DELAY_SECONDS)

    lambda_client.update_function_configuration(FunctionName=function_name, MemorySize=memory_mb)

    waiter = lambda_client.get_waiter("function_updated")
    waiter.wait(FunctionName=function_name)
    time.sleep(COLD_START_STABILIZATION_DELAY_SECONDS)


# =============================================================================
# Lambda Invocation Functions
# =============================================================================


def invoke_function_with_retry(
    function_name: str, payload: dict, max_attempts: int = LAMBDA_INVOKE_MAX_RETRIES
) -> dict:
    """
    Invoke Lambda function with exponential backoff retry.

    Retries on throttling (TooManyRequestsException) and service errors (5xx)
    with exponential backoff (1s, 2s, 4s).
    """
    lambda_client = get_lambda_client()
    for attempt in range(max_attempts):
        try:
            response = lambda_client.invoke(
                FunctionName=function_name,
                InvocationType="RequestResponse",
                Payload=json.dumps(payload),
                LogType="Tail",
            )
            return response
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")

            if (
                error_code in ["TooManyRequestsException", "ServiceException"]
                and attempt < max_attempts - 1
            ):
                backoff = LAMBDA_INVOKE_BACKOFF_BASE_SECONDS * (2**attempt)
                log.warning(
                    f"Throttled or service error, retrying in {backoff}s (attempt {attempt + 1}/{max_attempts})"
                )
                time.sleep(backoff)
            else:
                raise


def invoke_function(function_name: str, workload_type: str, memory_mb: int) -> dict[str, Any]:
    """
    Invoke Lambda function and capture performance metrics.

    Uses LogType='Tail' to receive CloudWatch REPORT line in response, enabling
    zero-overhead metrics collection without SDK imports in handlers.

    Returns AWS-reported metrics from CloudWatch REPORT line:
    - durationMs: Actual execution time
    - billedDurationMs: Rounded execution time (what you're charged for)
    - memoryUsedMB: Peak memory usage
    - initDurationMs: Initialization time (cold starts only)
    """
    payload = build_workload_payload(workload_type, memory_mb)
    response = invoke_function_with_retry(function_name, payload)
    result = json.loads(response["Payload"].read())

    metrics = {}
    if "FunctionError" not in response:
        metrics = parse_cloudwatch_report(response.get("LogResult", ""))

    lambda_request_id = metrics.get("lambda_request_id") or result.get("requestId", "unknown")

    return {
        "success": result.get("success", False),
        "result": result,
        "durationMs": metrics.get("duration_ms"),
        "billedDurationMs": metrics.get("billed_duration_ms"),
        "memoryUsedMB": metrics.get("memory_used_mb"),
        "initDurationMs": metrics.get("init_duration_ms"),
        "statusCode": response["StatusCode"],
        "lambdaRequestId": lambda_request_id,
    }


# =============================================================================
# DynamoDB Functions
# =============================================================================


def store_result(
    function_info: dict[str, str],
    memory_mb: int,
    is_cold_start: bool,
    invocation_result: dict[str, Any],
    test_run_id: str,
    invocation_number: int,
) -> None:
    """Store individual benchmark result in DynamoDB with AWS-reported metrics."""
    dynamodb = get_dynamodb_resource()
    table = dynamodb.Table(RESULTS_TABLE_NAME)
    timestamp = int(time.time() * 1000)

    config_id = make_config_id(function_info, memory_mb)
    invocation_type = "cold" if is_cold_start else "warm"
    pk = f"{test_run_id}#{config_id}"
    sk = f"{invocation_type}#{invocation_number}"

    item = {
        "pk": pk,
        "sk": sk,
        "itemType": "result",
        "testRunId": test_run_id,
        "timestamp": timestamp,
        "configId": config_id,
        "runtime": function_info["runtime"],
        "architecture": function_info["architecture"],
        "workloadType": function_info["workloadType"],
        "memorySizeMB": memory_mb,
        "invocationType": invocation_type,
        "invocationNumber": invocation_number,
        "durationMs": to_decimal(invocation_result.get("durationMs")),
        "billedDurationMs": invocation_result.get("billedDurationMs"),
        "maxMemoryUsedMB": invocation_result.get("memoryUsedMB"),
        "functionName": function_info["name"],
        "functionVersion": function_info.get("version", "$LATEST"),
        "lambdaRequestId": invocation_result.get("lambdaRequestId", "unknown"),
        "success": invocation_result.get("success", False),
    }

    if is_cold_start and invocation_result.get("initDurationMs") is not None:
        item["initDurationMs"] = to_decimal(invocation_result.get("initDurationMs"))

    item = {k: v for k, v in item.items() if v is not None}

    table.put_item(Item=item)


def write_aggregate(
    function_info: dict[str, str],
    memory_mb: int,
    invocation_type: str,
    samples: list[dict[str, Any]],
    test_run_id: str,
) -> None:
    """
    Write aggregate statistics for a configuration to DynamoDB.

    Pre-calculates statistics (mean, median, percentiles) for fast analysis
    without querying individual result items. Only successful samples are used
    for statistical calculations.
    """
    dynamodb = get_dynamodb_resource()
    table = dynamodb.Table(RESULTS_TABLE_NAME)
    config_id = make_config_id(function_info, memory_mb)

    # Split samples into successful and failed
    successful_samples = [s for s in samples if s.get("success", False)]
    failed_count = len(samples) - len(successful_samples)
    all_successful = failed_count == 0

    # Extract metrics from successful samples only
    durations = [s["durationMs"] for s in successful_samples if s.get("durationMs") is not None]
    billed_durations = [
        s["billedDurationMs"] for s in successful_samples if s.get("billedDurationMs") is not None
    ]
    memory_usage = [
        s["memoryUsedMB"] for s in successful_samples if s.get("memoryUsedMB") is not None
    ]
    init_durations = [
        s["initDurationMs"] for s in successful_samples if s.get("initDurationMs") is not None
    ]

    timestamp = int(time.time() * 1000)

    item = {
        "pk": f"TESTRUN#{test_run_id}",
        "sk": f"AGGREGATE#{config_id}#{invocation_type}",
        "itemType": "aggregate",
        "testRunId": test_run_id,
        "configId": config_id,
        "timestamp": timestamp,
        "runtime": function_info["runtime"],
        "architecture": function_info["architecture"],
        "workloadType": function_info["workloadType"],
        "memorySizeMB": memory_mb,
        "invocationType": invocation_type,
        "sampleCount": len(successful_samples),
        "allSuccessful": all_successful,
        "failedCount": failed_count,
        "durationMsStats": map_decimal(calculate_statistics(durations)),
        "billedDurationMsStats": map_decimal(calculate_statistics(billed_durations)),
        "memoryMBStats": map_decimal(calculate_statistics(memory_usage)),
    }

    if invocation_type == "cold" and init_durations:
        item["initDurationMsStats"] = map_decimal(calculate_statistics(init_durations))

    table.put_item(Item=item)


def create_test_run_item(
    test_run_id: str,
    mode: str,
    total_configurations: int,
    cold_starts_per_config: int,
    warm_starts_per_config: int,
    test_matrix: dict[str, Any],
    notes: str = "",
) -> None:
    """
    Create test-run metadata item in DynamoDB.

    Stores execution metadata and complete test matrix for analysis scripts.
    """
    dynamodb = get_dynamodb_resource()
    table = dynamodb.Table(RESULTS_TABLE_NAME)
    timestamp = int(time.time() * 1000)
    total_invocations = total_configurations * (cold_starts_per_config + warm_starts_per_config)

    item = {
        "pk": f"TESTRUN#{test_run_id}",
        "sk": f"TESTRUN#{test_run_id}",
        "itemType": "test-run",
        "testRunId": test_run_id,
        "timestamp": timestamp,
        "status": "in_progress",
        "startTime": timestamp,
        "mode": mode,
        "region": AWS_REGION,
        "totalConfigurations": total_configurations,
        "totalInvocations": total_invocations,
        "coldStartsPerConfig": cold_starts_per_config,
        "warmStartsPerConfig": warm_starts_per_config,
        "failedInvocations": 0,
        "testMatrix": test_matrix,
    }

    if notes:
        item["notes"] = notes

    table.put_item(Item=item)


def update_test_run_status(
    test_run_id: str, status: str, failed_invocations: int = 0, error_summary: str | None = None
) -> None:
    """Update test-run item with final status and completion time."""
    dynamodb = get_dynamodb_resource()
    table = dynamodb.Table(RESULTS_TABLE_NAME)
    end_time = int(time.time() * 1000)

    update_expr = "SET #status = :status, endTime = :end_time, failedInvocations = :failed"
    expr_values = {":status": status, ":end_time": end_time, ":failed": failed_invocations}
    expr_names = {"#status": "status"}

    if error_summary:
        update_expr += ", errorSummary = :error"
        expr_values[":error"] = error_summary

    table.update_item(
        Key={"pk": f"TESTRUN#{test_run_id}", "sk": f"TESTRUN#{test_run_id}"},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )


# =============================================================================
# Orchestration Functions (High-Level Coordination)
# =============================================================================


def benchmark_function_single_memory(
    function_info: dict[str, str], memory_mb: int, config: BenchmarkConfig, test_run_id: str
) -> tuple[str, int, bool, str | None]:
    """
    Run complete benchmark for a single function at a specific memory configuration.

    Returns:
        Tuple of (function_name, memory_mb, success, error_message)
    """
    function_name = function_info["name"]
    workload_type = function_info["workloadType"]

    try:
        log.info(f"  {function_name} @ {memory_mb}MB - Starting")

        force_cold_start(function_name, memory_mb)

        cold_samples = []
        for i in range(config.cold_starts_per_config):
            result = invoke_function(function_name, workload_type, memory_mb)
            cold_samples.append(result)
            store_result(
                function_info, memory_mb, True, result, test_run_id, invocation_number=i + 1
            )

            if i < config.cold_starts_per_config - 1:
                force_cold_start(function_name, memory_mb)

        write_aggregate(function_info, memory_mb, "cold", cold_samples, test_run_id)

        warm_samples = []
        for i in range(config.warm_starts_per_config):
            result = invoke_function(function_name, workload_type, memory_mb)
            warm_samples.append(result)
            store_result(
                function_info, memory_mb, False, result, test_run_id, invocation_number=i + 1
            )

        write_aggregate(function_info, memory_mb, "warm", warm_samples, test_run_id)

        log.info(f"  {function_name} @ {memory_mb}MB - ✓ Complete")
        return (function_name, memory_mb, True, None)

    except Exception as e:
        error_msg = str(e)
        log.error(f"  {function_name} @ {memory_mb}MB - ✗ ERROR: {error_msg}")
        return (function_name, memory_mb, False, error_msg)


def benchmark_function_all_memory(
    function_info: dict[str, str], config: BenchmarkConfig, test_run_id: str
) -> list[tuple[str, int, bool, str | None]]:
    """
    Run benchmarks for a single function across ALL memory configurations.

    Tests all memory configurations sequentially to avoid ResourceConflictException
    from concurrent Lambda configuration updates.
    """
    memory_configs = get_memory_configs_for_workload(function_info["workloadType"], config)
    results = []

    for memory_mb in memory_configs:
        result = benchmark_function_single_memory(function_info, memory_mb, config, test_run_id)
        results.append(result)

    return results


def run_benchmark(
    config: BenchmarkConfig = TEST_CONFIG,
    test_run_id: str | None = None,
    notes: str = "",
    name_filter: str | None = None,
) -> str:
    """
    Run full benchmark across all functions and configurations.

    Main orchestration function that discovers functions, builds test matrix,
    executes benchmarks in parallel, and tracks progress.

    Returns:
        Test run ID (UUID)
    """
    if test_run_id is None:
        test_run_id = str(uuid.uuid4())

    log.info("=" * 70)
    log.info("Lambda ARM vs x86 Benchmark Orchestrator")
    log.info("=" * 70)
    log.info(f"Test Run ID: {test_run_id}")
    log.info(f"Cold starts per config: {config.cold_starts_per_config}")
    log.info(f"Warm starts per config: {config.warm_starts_per_config}")
    log.info(f"Memory configs: {config.memory_configs_to_test or 'ALL'}")
    log.info(f"Parallel workers: {config.max_workers}")
    if name_filter:
        log.info(f"Function filter: {name_filter}")
    if notes:
        log.info(f"Notes: {notes}")
    log.info("")

    functions = get_deployed_functions(name_filter)

    test_configs = []
    for func in functions:
        memory_configs = get_memory_configs_for_workload(func["workloadType"], config)
        for memory_mb in memory_configs:
            test_configs.append((func, memory_mb))

    total_tests = len(test_configs)
    log.info(f"Total test configurations: {total_tests}")
    log.info("")

    test_matrix = build_test_matrix(test_configs)

    # Determine mode based on config
    if config.cold_starts_per_config >= 100:
        mode = "production"
    elif config.cold_starts_per_config >= 50:
        mode = "balanced"
    else:
        mode = "test"

    log.info("Creating test run item...")
    create_test_run_item(
        test_run_id=test_run_id,
        mode=mode,
        total_configurations=total_tests,
        cold_starts_per_config=config.cold_starts_per_config,
        warm_starts_per_config=config.warm_starts_per_config,
        test_matrix=test_matrix,
        notes=notes,
    )
    log.info("✓")
    log.info("")

    completed = 0
    failed = 0
    start_time = time.time()
    aborted = False
    progress_lock = threading.Lock()

    try:
        # Parallelize by FUNCTION to avoid ResourceConflictException
        with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
            future_to_function = {
                executor.submit(benchmark_function_all_memory, func, config, test_run_id): func
                for func in functions
            }

            for future in as_completed(future_to_function):
                func = future_to_function[future]

                try:
                    results = future.result()

                    with progress_lock:
                        for _function_name, _memory_mb, success, _error_msg in results:
                            if success:
                                completed += 1
                            else:
                                failed += 1

                            elapsed = time.time() - start_time
                            total_done = completed + failed
                            if total_done > 0:
                                avg_time = elapsed / total_done
                                remaining = (total_tests - total_done) * avg_time

                                log.info(
                                    f"Progress: {total_done}/{total_tests} ({100 * total_done / total_tests:.1f}%) "
                                    f"| Completed: {completed} | Failed: {failed} "
                                    f"| Est. remaining: {remaining / 60:.1f}min"
                                )

                except Exception as e:
                    memory_configs = get_memory_configs_for_workload(func["workloadType"], config)
                    with progress_lock:
                        failed += len(memory_configs)
                        log.error(f"Task failed for {func['name']}: {e}")

    except KeyboardInterrupt:
        log.warning("")
        log.warning("Benchmark aborted by user (KeyboardInterrupt)")
        aborted = True

    elapsed_time = time.time() - start_time
    log.info("")

    log.info("Updating test run status...")
    if aborted:
        update_test_run_status(
            test_run_id, status="failed", failed_invocations=failed, error_summary="aborted by user"
        )
        log.warning("⚠ Status: aborted by user")
    elif failed == 0:
        update_test_run_status(test_run_id, status="completed")
        log.info("✓ Status: completed")
    else:
        update_test_run_status(
            test_run_id,
            status="completed",
            failed_invocations=failed,
            error_summary=f"{failed} configuration(s) failed during benchmark execution",
        )
        log.warning(f"⚠ Status: completed with {failed} failures")
    log.info("")

    log.info("=" * 70)
    log.info("Benchmark complete!" if not aborted else "Benchmark aborted!")
    log.info(f"Test Run ID: {test_run_id}")
    log.info(f"Total time: {elapsed_time / 60:.1f} minutes")
    log.info(f"Completed: {completed}/{total_tests}")
    if failed > 0:
        log.info(f"Failed: {failed}")
    log.info(f"Results stored in DynamoDB table: {RESULTS_TABLE_NAME}")
    log.info("=" * 70)

    return test_run_id


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="AWS Lambda ARM vs x86 Benchmark Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick validation (2 cold + 2 warm, ~10 minutes)
  python benchmark_orchestrator.py --test

  # Publication-quality results (50 cold + 200 warm, ~6-8 hours)
  python benchmark_orchestrator.py --balanced

  # Maximum statistical rigor (100 cold + 500 warm, ~18-24 hours)
  python benchmark_orchestrator.py --production

  # With custom notes
  python benchmark_orchestrator.py --balanced --notes "Rust runtime comparison"

  # Test specific memory configs only
  python benchmark_orchestrator.py --test --mem 1769 2048

  # Test specific workload type
  python benchmark_orchestrator.py --test --filter cpu-intensive

  # Custom parallel workers
  python benchmark_orchestrator.py --balanced --workers 8
        """,
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--test",
        action="store_true",
        help="Run in TEST mode (2 cold + 2 warm starts, quick validation)",
    )
    mode_group.add_argument(
        "--balanced",
        action="store_true",
        help="Run in BALANCED mode (50 cold + 200 warm starts, publication-quality p99 statistics)",
    )
    mode_group.add_argument(
        "--production",
        action="store_true",
        help="Run in PRODUCTION mode (100 cold + 500 warm starts, maximum statistical rigor)",
    )

    parser.add_argument("--notes", type=str, default="", help="Optional notes about this test run")
    parser.add_argument(
        "--id",
        type=str,
        dest="test_run_id",
        help="Optional test run ID (reuse existing ID or provide custom ID)",
    )
    parser.add_argument(
        "--mem",
        type=int,
        nargs="+",
        dest="memory_sizes",
        help="Restrict to specific memory sizes (e.g., --mem 1769 2048)",
    )
    parser.add_argument(
        "--filter",
        type=str,
        dest="name_filter",
        help="Filter functions by name substring or workload type (e.g., cpu-intensive, python3.13)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=12,
        dest="max_workers",
        help="Number of functions to test in parallel (default: 12)",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Auto-confirm prompts (useful for automated/non-interactive execution)",
    )

    args = parser.parse_args()

    if args.production:
        log.warning("WARNING: Running in PRODUCTION mode with maximum iteration counts!")
        log.warning("This will take 18-24 hours and cost ~$5-10 in Lambda invocations.")
        if not args.yes:
            response = input("Continue? (yes/no): ")
            if response.lower() != "yes":
                log.info("Aborted.")
                exit(0)
        config = PRODUCTION_CONFIG
    elif args.balanced:
        log.info("Running in BALANCED mode (publication-quality statistics)")
        log.info("Estimated time: 6-8 hours, estimated cost: ~$2-4")
        if not args.yes:
            response = input("Continue? (yes/no): ")
            if response.lower() != "yes":
                log.info("Aborted.")
                exit(0)
        config = BALANCED_CONFIG
    else:
        log.info("Running in TEST mode with minimal iteration counts")
        config = TEST_CONFIG

    if args.memory_sizes:
        config.memory_configs_to_test = args.memory_sizes
        log.info(f"Restricting to memory sizes: {args.memory_sizes}")

    if args.max_workers:
        config.max_workers = args.max_workers

    run_benchmark(
        config=config, test_run_id=args.test_run_id, notes=args.notes, name_filter=args.name_filter
    )
