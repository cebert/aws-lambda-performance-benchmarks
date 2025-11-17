# BenchmarkResults Table – Data Model & Access Patterns

This document explains the DynamoDB schema used to store test results and analyze test runs.

## Use Case

The `BenchmarkResults` DynamoDB table stores results for the Lambda ARM vs x86 benchmark suite.

This is a single-table, multi-entity database that is optimized for:

- Fast, cheap queries over aggregated statistics (avoids excessive reads).
- Occasional deep dives into raw invocation results.
- Tracking and comparing multiple benchmark runs over time.

Because this table is for test result data and isn't mission-critical or production data, we don't have backups enabled for this table.

## Core Access Patterns

The table is designed around these primary access patterns:

- **AP1 – Get test run summary + all aggregates for a run**  
  “Show me metadata and stats for test run X.”

- **AP2 – Get a single aggregate for a specific config in a run**  
  “Give me cold-start stats for `python3.13-arm64-cpu-512` in run X.”

- **AP3 – Get all raw results for a test run**  
  “Fetch all samples for run X so I can re-aggregate / debug.”

- **AP4 – Get all runs for a specific configuration**  
  “Show how `python3.13-arm64-cpu-512` has changed over time.”

- **AP5 – List all test runs**  
  “Show me all benchmark runs with their status, notes, and timestamps.”

- **AP6 (optional / advanced) – Detect missing aggregates for a run**  
  “Given the test matrix for run X, which aggregates are missing?”

The schema and GSIs exist to satisfy these patterns directly.

## Table Design Overview

### Single-Table, Multi-Entity

All entities share one table:

- `result` – individual invocation data
- `aggregate` – pre-calculated statistics per configuration
- `test-run` – metadata and test matrix for a run

Every item includes:

- `itemType ∈ {"result","aggregate","test-run"}` – required entity type declaration
- `testRunId` – UUID that ties all data for a run together

### Primary Key (Base Table)

The base table uses a generic primary key:
- **Partition key:** `pk`
- **Sort key:** `sk`

**Item key patterns:**

- **Test run items**
  - `pk = "TESTRUN#{testRunId}"`
  - `sk = "TESTRUN#{testRunId}"`

- **Aggregate items**
  - `pk = "TESTRUN#{testRunId}"`
  - `sk = "AGGREGATE#{configId}#{invocationType}"`

- **Result items**
  - `pk = "{testRunId}#{configId}"`
  - `sk = "{invocationType}#{invocationNumber}"`

> **Note**  
> Aggregates and the test-run item for a run share the same `pk`.  
> This allows a single query on `pk = "TESTRUN#{testRunId}"` to return:
> - One `test-run` item (metadata)
> - Many `aggregate` items (stats)

## Entity Definitions

### Test Run Item (`itemType = "test-run"`)

**Key pattern**

- `pk = "TESTRUN#{testRunId}"`
- `sk = "TESTRUN#{testRunId}"`

**Purpose**

- One item per benchmark run.
- Stores metadata and the **test matrix**.

**Typical attributes**

- Identity & timestamps:
  - `testRunId`
  - `timestamp` (start time)
  - `startTime`, `endTime` (optional)

- Status:
  - `status` – `"in_progress"`, `"completed"`, or `"failed"`
  - `failedInvocations` (optional)
  - `errorSummary` (optional)

- Run configuration:
  - `mode` – `"test"` or `"production"`
  - `totalConfigurations`
  - `totalInvocations`
  - `coldStartsPerConfig`
  - `warmStartsPerConfig`

- Documentation:
  - `notes` – human-readable description of what changed / why

- Test matrix (recommended):
  - High-level lists:
    - `runtimes`
    - `architectures`
    - `workloadTypes`
  - Detailed:
    - `configurations[]` with:
      - `runtime`
      - `architecture`
      - `workloadType`
      - `memorySizes[]`

The test matrix enables reconstruction of expected `(configId, invocationType)` aggregates and detection of missing data, and it supports partial runs (for example, filtered by runtime or memory).

### Aggregate Item (`itemType = "aggregate"`)

**Key pattern**

- `pk = "TESTRUN#{testRunId}"`
- `sk = "AGGREGATE#{configId}#{invocationType}"`

**Purpose**

- One item per `(testRunId, configId, invocationType)`.
- Stores pre-calculated statistics for fast, low-cost analysis.

**Typical attributes**

- Identity:
  - `testRunId`
  - `configId`
  - `invocationType` – `"cold" | "warm"`
  - `timestamp` (when the aggregate was created)

- Configuration dimensions:
  - `runtime`
  - `architecture`
  - `workloadType`
  - `memorySizeMB`

- Sample metadata:
  - `sampleCount`
  - `failedCount`
  - `allSuccessful`

- Statistics objects (names can evolve):
  - `durationMsStats`
  - `billedDurationMsStats`
  - `memoryMBStats`
  - `initDurationMsStats` (cold only)

Each stats object typically includes a combination of: mean, median, min, max, percentiles (`p90`, `p95`, `p99`), `sampleCount`, and optional flags such as `outliersRemoved`.

### Result Item (`itemType = "result"`)

**Key pattern**

- `pk = "{testRunId}#{configId}"`
- `sk = "{invocationType}#{invocationNumber}"`

**Purpose**

- Raw per-invocation data used for deep debugging or re-computing stats.

**Typical attributes**

- Identity:
  - `testRunId`
  - `configId`
  - `invocationType` – `"cold" | "warm"`
  - `invocationNumber` – integer
  - `timestamp`

- Metrics:
  - Duration metrics (for example, `durationMs`, `billedDurationMs`)
  - Memory usage (for example, `maxMemoryUsedMB`)
  - Optional cold-start metric: `initDurationMs`
  - Any additional metrics captured (for example, client latency)

- Lambda metadata:
  - `functionName`
  - `lambdaRequestId` (or equivalent request ID)

## Global Secondary Indexes

### ConfigIndex (GSI1)

**Schema**

- **Partition key:** `configId`
- **Sort key:** `timestamp`

**Supports**

- AP4 – Get all runs for a specific configuration

**Typical questions**

- “Show all runs where `python3.13-arm64-cpu-512` was tested.”
- “Get the most recent N runs for this configuration.”

---

### TestRunIndex (GSI2)

**Schema**

- **Partition key:** `testRunId`
- **Sort key:** `timestamp`

**Supports**

- AP3 – Get all raw results for a test run

**Typical questions**

- “Fetch all samples for run `abc-123`.”
- “Recompute stats for run `abc-123` using custom logic.”

---

## Access Patterns and How to Query

The table below summarizes which part of the model to use for each access pattern.

| Access pattern                                             | Target                       | Key condition / usage                                                                          |
|------------------------------------------------------------|------------------------------|------------------------------------------------------------------------------------------------|
| AP1 – Test run summary + all aggregates for a run          | Base table                   | `pk = "TESTRUN#{testRunId}"`. Filter `itemType` = `test-run` / `aggregate`.                    |
| AP2 – Single aggregate for `(testRunId, configId, type)`   | Base table (GetItem)         | `pk = "TESTRUN#{testRunId}"`, `sk = "AGGREGATE#{configId}#{invocationType}"`.                  |
| AP3 – All raw results for a test run                       | TestRunIndex (GSI2)          | `testRunId = {testRunId}`; use `timestamp` sort key as needed.                                 |
| AP4 – All runs for a given configuration                   | ConfigIndex (GSI1)           | `configId = {configId}`; sort / filter by `timestamp`.                                         |
| AP5 – List all test runs                                   | Base table (Scan)            | Filter on `itemType = "test-run"`, then sort by `timestamp`.                                   |
| AP6 – Detect missing aggregates for a run                  | Base table + primary-key gets| 1) Read `test-run` item; 2) for each expected `(configId, type)` perform GetItem on aggregate. |