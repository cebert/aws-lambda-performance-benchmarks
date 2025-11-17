# Project Decision Log

**Project:** AWS Lambda ARM vs x86 Benchmark

This document tracks all significant architectural and technical decisions that affect the codebase structure, implementation approach, and benchmark methodology.

---

## Decision Summary

### Approved Decisions

- **D001:** Project Scope - Comprehensive ARM vs x86 benchmark
- **D002:** Infrastructure Tool - AWS CDK (TypeScript)
- **D003:** Workload Types - 3 single-threaded synthetic workloads
- **D004:** Testing Strategy - Forced cold starts + warm start testing
- **D005:** Data Storage - DynamoDB + CloudWatch
- **D006:** Analysis Tools - Python (pandas, matplotlib, scipy)
- **D007:** Security - CDK Nag for automated checks
- **D008:** Runtime Versions - Python 3.13/3.12/3.11, Node.js 22/20, Rust
- **D009:** [CRITICAL] Zero-Overhead Data Collection - CloudWatch REPORT parsing
- **D010:** Node.js Language - TypeScript with esbuild
- **D011:** [CRITICAL] AWS SDK Strategy - No SDK for CPU/Memory, runtime SDK for Light workload
- **D012:** Testing Strategy - No unit tests for benchmark code
- **D015:** [CRITICAL] Optimized Deployment Strategy - Dynamic memory configuration at runtime
- **D016:** [SUPERSEDED] Graduated Memory Allocation - Replaced by fixed 100 MB array (see D018)
- **D017:** Rust Runtime Support - Add Rust via cargo-lambda-cdk construct
- **D018:** [CRITICAL] Fixed Memory Workload - Memory-intensive uses constant 100 MB array

---

## D001: Project Scope

**Date:** 2025-10-25 | **Status:** Approved | **Updated:** 2025-11-14

**Decision:** Benchmark AWS Lambda ARM (Graviton) vs x86 performance across multiple runtimes, architectures, memory configurations, and workload types.

**Rationale:** Updates 2023 AWS blog measurements with current runtime versions.

---

## D002: Infrastructure as Code Tool

**Date:** 2025-10-25 | **Status:** Approved

**Decision:** Use AWS CDK (TypeScript) for all infrastructure.

**Rationale:** CDK provides type safety, reusable constructs, and programmatic
generation of resources.

---

## D003: Workload Types

**Date:** 2025-10-25 | **Status:** Approved | **Updated:** 2025-11-07

**Decision:** Implement 3 single-threaded synthetic workloads:

1. **CPU-Intensive** - SHA-256 hashing loop (pure compute, no I/O)
2. **Memory-Intensive** - Large array generation and sorting (tests memory scaling)
3. **Light** - DynamoDB batch write (5 items) + batch read (I/O-bound baseline)

**Rationale:** Single-threaded workloads provide clearest architecture comparison without multi-threading complexity. Covers key performance dimensions: CPU-bound, memory-bound, and I/O-bound operations.

**Related Files:**
- `cdk/lib/config/lambda-config.ts` - Workload definitions and memory configs
- `lambdas/python/cpu-intensive/handler.py` - CPU workload (NO SDK)
- `lambdas/python/memory-intensive/handler.py` - Memory workload (NO SDK)
- `lambdas/python/light/handler.py` - I/O workload (uses boto3)
- `lambdas/nodejs/{workload}/handler.ts` - Node.js equivalents

---

## D004: Cold vs Warm Start Testing Strategy

**Date:** 2025-10-25 | **Status:** Approved | **Updated:** 2025-11-14

**Decision:** Use forced cold starts via `UpdateFunctionConfiguration` API instead of waiting 15+ minutes between invocations.

**Implementation:**
- **Forced Cold Start:** Update function config with env var → wait for update → invoke
- **Warm Start:** Sequential invocations (function stays warm)
- **Time Savings:** Reduces full benchmark from 60-120 hours to ~2-2.5 hours

**Rationale:** Waiting 15+ minutes per cold start is impractical. Configuration update forces Lambda to reinitialize the execution environment.

**Credit:** Technique from AJ Stuyvenberg's cold-start-benchmarker

**Related Files:**
- `scripts/benchmark_orchestrator.py` - Implements forced cold start logic

---

## D005: Data Storage Strategy

**Date:** 2025-10-25 | **Status:** Approved | **Updated:** 2025-11-14

**Decision:**
- DynamoDB for results storage (three entity types: `result`, `aggregate`, `test-run`)
- CloudWatch Logs with 3-day retention
- No S3 backup

**Rationale:** DynamoDB pay-per-request is cost-effective for sporadic usage. Pre-calculated aggregates avoid expensive scans of raw results.

**Related Files:**
- `cdk/lib/constructs/results-table.ts` - Table definition
- `docs/dynamodb-schema.md` - Schema
- `scripts/benchmark_orchestrator.py` - Writes results and aggregates

---

## D006: Analysis Tools

**Date:** 2025-10-25 | **Status:** Approved

**Decision:** Python data science stack (pandas, matplotlib/seaborn, plotly, scipy)

**Rationale:** Standard tooling for data manipulation and visualization.

---

## D007: Security

**Date:** 2025-10-25 | **Status:** Approved

**Decision:**
- CDK Nag for automated security checks
- IAM least privilege
- Encryption at rest
- No hardcoded secrets
- No VPC

**Rationale:** Standard AWS security practices.

---

## D008: Runtime Versions

**Date:** 2025-10-25 | **Status:** Approved | **Updated:** 2025-11-15

**Decision:**

- **Python:** 3.13, 3.12, 3.11
- **Node.js:** 22.x, 20.x
- **Rust:** provided.al2023 (added via D017)

**Research Source:** AWS Documentation via MCP aws-docs server

**Rationale:**

- **Python 3.13**: Latest runtime, AL2023, deprecation June 2029
- **Python 3.12**: LTS, AL2023, deprecation October 2028
- **Python 3.11**: LTS, AL2, deprecation June 2026 (baseline comparison)
- **Node.js 22**: Latest LTS, AL2023, deprecation April 2027
- **Node.js 20**: Active LTS, AL2023, deprecation April 2026

**Excluded:**

- Python 3.10: Redundant with 3.11 (both deprecate June 2026)
- Python 3.9: Deprecating December 2025 (too soon)
- Node.js 18: Already deprecated

**Key Finding:** All selected runtimes support both ARM64 and x86_64

---

## D009: Metrics Collection [CRITICAL]

**Date:** 2025-10-25 | **Status:** Approved | **Updated:** 2025-11-14

**Decision:** Parse CloudWatch REPORT logs for performance metrics instead of in-function instrumentation.

**Alternatives Considered:**
- In-function DynamoDB writes: Adds network latency overhead
- Custom timing logic: Adds CPU overhead
- AWS X-Ray: Adds overhead and complexity
- Lambda Telemetry API: Requires extension (adds init overhead)
- CloudWatch REPORT parsing: Selected (no overhead)

**Implementation:**
- Lambda functions run only the workload (no timing code)
- Orchestrator extracts metrics using `LogType='Tail'` parameter
- REPORT line parsed with regex to extract: duration, billed duration, memory used, init duration

**Metrics Collected:**
- `durationMs` - Execution time
- `billedDurationMs` - Rounded for billing
- `maxMemoryUsedMB` - Peak memory usage
- `initDurationMs` - Cold start init time (cold starts only)
- `lambdaRequestId` - Request ID

**Related Files:**
- `scripts/benchmark_orchestrator.py` - Implements LogType='Tail' extraction
- `lambdas/python/cpu-intensive/handler.py` - NO SDK imports (pure compute)
- `lambdas/python/memory-intensive/handler.py` - NO SDK imports (pure compute)
- `docs/metrics-collection-implementation.md` - Detailed REPORT parsing documentation

---

## D010: Node.js Language

**Date:** 2025-10-25 | **Status:** Approved

**Decision:** TypeScript for Node.js Lambda functions, bundled with esbuild.

**Configuration:**
- Target: ES2022
- Bundler: esbuild
- Exclude AWS SDK v3 from bundle (use runtime SDK)

---

## D011: AWS SDK Strategy [CRITICAL]

**Date:** 2025-10-25 | **Status:** Approved

**Decision:** No AWS SDK for CPU/Memory workloads. Runtime-provided SDK for Light workload.

**Implementation:**
- **CPU-Intensive:** No SDK imports (pure computation)
- **Memory-Intensive:** No SDK imports (pure memory operations)
- **Light:** Use runtime-provided SDK (boto3 for Python, exclude @aws-sdk from Node.js bundle)

**Rationale:** SDK initialization adds overhead that would contaminate CPU/Memory benchmarks.

**Reference:** SDK overhead data from Aaron Stuyvenberg: https://aaronstuyvenberg.com/posts/aws-sdk-comparison

**Related Files:**
- `lambdas/python/cpu-intensive/handler.py` - No SDK
- `lambdas/python/memory-intensive/handler.py` - No SDK
- `lambdas/python/light/handler.py` - boto3 only
- `lambdas/nodejs/light/handler.ts` - @aws-sdk/client-dynamodb only

---

## D012: Testing Strategy

**Date:** 2025-11-14 | **Status:** Approved

**Decision:** No unit tests for benchmark code.

**Rationale:** Simple, single-use measurement tool. Correctness verified by running actual benchmarks.

**Validation:** Run test mode benchmarks to verify infrastructure works correctly.

---

## D015: Dynamic Memory Configuration [CRITICAL]

**Date:** 2025-10-25 | **Status:** Approved | **Updated:** 2025-11-15

**Decision:** Deploy 36 base Lambda functions and use `UpdateFunctionConfiguration` API to change memory dynamically during testing.

**Approach:**
- Deploy base functions (one per runtime/architecture/workload combination)
- Test multiple memory sizes (6-12 per workload) by updating configuration between tests
- Parallelize across all functions

**Benefits:**
- Small number of deployed functions instead of ~1,000+
- Fast deployment (~5-10 minutes)
- Easy to add/remove memory configurations

**Trade-off:** ~5-10 seconds overhead per memory configuration update

**Related Files:**
- `cdk/lib/config/lambda-config.ts` - Defines base function configurations
- `cdk/lib/cdk-stack.ts` - Creates functions from config
- `scripts/benchmark_orchestrator.py` - Implements dynamic memory updates

---

## D016: Graduated Memory Allocation [HISTORICAL]

**Date:** 2025-11-14 | **Status:** SUPERSEDED by D018

**Note:** This decision has been replaced. See D018 for current approach (fixed 100 MB array).

**Decision:** Memory-intensive workload uses graduated allocation ratios based on Lambda memory configuration instead of a fixed percentage.

**Problem:** Initial implementation used a flat 40% ratio for all memory sizes, causing severe performance issues at small Lambda configurations (128-512 MB). Tests at 128 MB and 512 MB were taking 20+ minutes per invocation due to excessive garbage collection and memory swapping.

**Implementation:**

Graduated allocation strategy in `get_memory_intensive_size_mb()`:
- **128-256 MB**: 15% of Lambda memory (conservative to avoid GC thrashing)
- **512 MB**: 20% of Lambda memory (still conservative)
- **1024 MB**: 30% of Lambda memory (moderate stress)
- **1769-2048 MB**: 40% of Lambda memory (significant stress)
- **4096 MB+**: 60% of Lambda memory (aggressive stress testing)
- **Safety cap**: 70% maximum to prevent OOM errors

**Rationale:**
- Small Lambda configs need conservative ratios to complete in reasonable time
- Large Lambda configs benefit from aggressive ratios (60-70%) to properly stress memory subsystem
- Graduated approach better represents real-world usage patterns
- Percentage-based safety cap (70%) automatically scales with Lambda max memory

**Impact:**
- **128 MB**: Array size reduced from 51 MB → 19 MB (63% reduction)
- **512 MB**: Array size reduced from 205 MB → 102 MB (50% reduction)
- **4096 MB**: Array size increased from 1638 MB → 2458 MB (50% increase)
- **8192 MB**: Array size increased from 3277 MB → 4915 MB (50% increase)

**Related Files:**
- `scripts/benchmark_orchestrator.py` - Implements graduated allocation logic
- `docs/benchmark-design.md` - Documents workload allocation strategy
- `docs/handler-api-spec.md` - Documents payload size calculations

---

## D017: Rust Runtime Support

**Date:** 2025-11-15 | **Status:** Approved

**Decision:** Add Rust as a sixth runtime to the benchmark suite using the `cargo-lambda-cdk` construct library.

**Context:** AWS officially announced Rust Lambda support on November 14, 2025, providing native Rust runtime support via the `provided.al2023` runtime. The [`cargo-lambda-cdk`](https://github.com/cargo-lambda/cargo-lambda-cdk) library provides CDK constructs that automatically compile Rust code using cargo-lambda during synthesis.

**Implementation:**
- **Runtime**: `provided.al2023` with bootstrap binary
- **Build tool**: cargo-lambda (automatic via cargo-lambda-cdk)
- **CDK integration**: `RustFunction` construct from cargo-lambda-cdk
- **Workspace structure**: Rust workspace with 3 binary crates (cpu-intensive, memory-intensive, light)
- **Total functions**: 36 (6 runtimes × 2 architectures × 3 workloads)

**Workload implementations:**
- **CPU-intensive**: SHA-256 hashing loop using `sha2` crate (NO AWS SDK)
- **Memory-intensive**: `Vec<i64>` array generation with `StdRng::from_entropy()` (non-deterministic) and `sort_unstable()` (NO AWS SDK)
- **Light**: DynamoDB batch write + batch read using `aws-sdk-dynamodb` crate (compiled into binary)

**Rationale:**
- Rust is increasingly used for Lambda functions due to performance and memory efficiency
- Official AWS support makes Rust a first-class Lambda runtime
- Adds systems programming language perspective to benchmark
- cargo-lambda-cdk provides seamless CDK integration with automatic compilation

**References:**
- [AWS Blog: Building serverless applications with Rust on AWS Lambda](https://aws.amazon.com/blogs/compute/building-serverless-applications-with-rust-on-aws-lambda/)
- [cargo-lambda-cdk GitHub](https://github.com/cargo-lambda/cargo-lambda-cdk)

**Related Files:**
- `cdk/lib/config/lambda-config.ts` - Added RUST_RUNTIMES configuration
- `cdk/lib/constructs/benchmark-function.ts` - Added RustFunction handling
- `cdk/package.json` - Added cargo-lambda-cdk dependency
- `lambdas/rust/Cargo.toml` - Rust workspace configuration
- `lambdas/rust/{workload}/src/main.rs` - Rust handler implementations
- `docs/benchmark-design.md` - Updated with Rust implementation details

---

## D018: Fixed Memory Workload (Supersedes D016)

**Status:** Approved
**Date:** 2025-11-16
**Stakeholders:** Benchmark design team

**Context:**

The original D016 design used graduated memory allocation ratios (15%-60% of Lambda memory) for the memory-intensive workload. This approach had a critical flaw: it conflated two variables (workload size AND resource size), making results difficult to interpret. As Lambda memory increased, the workload became exponentially larger, causing:

1. **Unclear results**: Did performance improve due to more CPU/memory, or degrade due to larger workload?
2. **Extreme execution times**: Python at 8192 MB allocated 4.9 GB arrays, taking 10+ minutes per invocation
3. **No clear plateau**: Impossible to visualize when adding more resources stops helping

**Decision:**

Use a **fixed 100 MB array** for the memory-intensive workload across ALL Lambda memory configurations (128 MB to 10240 MB).

**Implementation:**
- Python: `FIXED_ARRAY_SIZE_MB = 100` (hardcoded in handler)
- Node.js: `FIXED_ARRAY_SIZE_MB = 100` (hardcoded in handler)
- Rust: `FIXED_ARRAY_SIZE_MB = 100` (hardcoded in handler)
- Orchestrator: No longer calculates `sizeMB`, passes empty payload `{}`
- Remove `get_memory_intensive_size_mb()` function entirely

**Rationale:**

1. **Separates variables**: Constant workload + variable resources = pure scaling measurement
2. **Clear plateau visualization**: Shows exactly when 1 vCPU (1769 MB) stops improving performance
3. **Faster benchmarks**: No more 5GB arrays; all configs complete in reasonable time
4. **Apples-to-apples comparison**: Same work across all memory configs reveals resource efficiency

**Benefits:**
- ~10x faster benchmark execution for high-memory configs
- Clearer performance plateau graphs
- Easier to answer: "What's the optimal Lambda memory for sorting 100 MB?"
- Simpler code (no graduated ratio calculations)

**Trade-offs:**
- No longer tests "can this runtime handle massive arrays at high memory?"
- Fixed 100 MB may not stress 10240 MB Lambda's full capabilities
- Accepted: This benchmark focuses on **resource scaling**, not **workload scaling**

**Impact:**

**Code Changes:**
- `lambdas/python/memory-intensive/handler.py` - Use `FIXED_ARRAY_SIZE_MB`, remove validation
- `lambdas/nodejs/memory-intensive/handler.ts` - Use `FIXED_ARRAY_SIZE_MB`, remove validation
- `lambdas/rust/memory-intensive/src/main.rs` - Use `FIXED_ARRAY_SIZE_MB`, remove validation
- `scripts/benchmark_orchestrator.py` - Remove `get_memory_intensive_size_mb()`
- `scripts/benchmark_utils.py` - Replace `MEMORY_INTENSIVE_MAX_RATIO` with `MEMORY_INTENSIVE_ARRAY_SIZE_MB`

**Documentation Updates:**
- `docs/benchmark-design.md` - Replace graduated allocation section with fixed 100 MB rationale
- `docs/handler-api-spec.md` - Update memory-intensive payload spec (now `{}`)
- `CLAUDE.md` - Update project overview and invariants

**Migration:**
- New test results NOT comparable with D016 results (different workload sizes)
- Start fresh test runs after deploying D018 changes
- Archive D016 results separately if comparing approaches

**References:**
- Inspired by observation that benchmark slowed down as memory increased (counter-intuitive)
- Standard practice: fixed workload for performance scaling analysis

**Related Decisions:**
- Supersedes D016 (Graduated Memory Allocation)
- Complements D009 (Zero-Overhead Data Collection)
- Complements D015 (Dynamic Memory Configuration)

**Related Files:**
- All `lambdas/*/memory-intensive/` handler files
- `scripts/benchmark_orchestrator.py`
- `scripts/benchmark_utils.py`
- `docs/benchmark-design.md`
- `docs/handler-api-spec.md`

---

**End of Decision Log**

Last updated: 2025-11-16

For non-architectural decisions (budget, publication, etc.), see PROJECT_STATUS.md or README.md.
