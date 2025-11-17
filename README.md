# AWS Lambda ARM vs x86 Benchmark

This repository contains a benchmark suite comparing AWS Lambda cost and performance on **x86_64** and **ARM (Graviton2 Neoverse N1)** CPU architectures as of late 2025. It is inspired by the 2023 AWS blog post [Comparing AWS Lambda Arm vs. x86 Performance, Cost, and Analysis](https://aws.amazon.com/blogs/apn/comparing-aws-lambda-arm-vs-x86-performance-cost-and-analysis-2/), which uses older, now-unsupported runtimes.

This benchmark reimplements similar **single-threaded workloads** in **Node.js, Python, and Rust** using **currently supported AWS runtimes**, with a focus on realistic but controlled workloads and repeatable measurement.

## Supported Runtimes

- **Python:** 3.13, 3.12, 3.11  
- **Node.js:** 22, 20  
- **Rust:** Custom runtime on al2023 (Amazon Linux 2023) + `rustc 1.91.0`

## Workloads

See [`docs/benchmark-design.md`](./docs/benchmark-design.md) for full details.

- **CPU-intensive**
  - SHA-256 hashing loop (500k iterations) to exercise raw compute performance.
  - No dependency on AWS SDKs.

- **Memory-intensive**
  - Allocates a fixed 100 MB data structure and sorts it as a memory-heavy workload.
  - No dependency on AWS SDKs.

- **Light (I/O)**
  - Writes 5 items to DynamoDB in a batch, then reads 5 items in a batch.
  - Uses the AWS SDK and represents a realistic, light “business logic + I/O” workload.

**Test Matrix:**

- 6 runtimes × 2 architectures (ARM64/x86_64) × 3 workloads = 36 Lambda functions
- 3 workload types: CPU-intensive (SHA-256 hashing), Memory-intensive (array sorting), Light (DynamoDB I/O)
- Multiple memory configurations (128 MB to 10240 MB)
- Cold start vs warm start measurements

**Architecture:**

- Zero-overhead metrics collection (CloudWatch REPORT parsing)
- Dynamic memory configuration (no redeployment needed)
- DynamoDB storage with pre-computed aggregates
- Parallel execution across all functions  

📖 Full design documentation in [`/docs`](./docs)

 
## Quick Start

### Prerequisites

- AWS account with credentials configured (`aws configure`)
- Node.js 18+
- Python 3.11+ (via `uv` - recommended)
- AWS CDK CLI: `npm install -g aws-cdk`
- UV package manager: https://docs.astral.sh/uv/getting-started/installation/
- For Rust handlers: cargo-lambda or Docker (automatic via CDK)
  

### Install

```bash
git  clone <this-repo>
cd  aws-lambda-performance-benchmakrs
npm  install && npm  run  build
```  

### Deploy
 
```bash
npm  run  deploy
```

Deploys 36 Lambda functions, 2 DynamoDB tables, and supporting infrastructure to `us-east-2` (configurable via `AWS_REGION`).

### Cleanup

```bash
cdk  destroy  LambdaBenchmarkStack
```

## Run Benchmarks

Choose a test mode based on your needs:

**Test mode** (quick validation - 2 cold + 2 warm per config, ~10 min):

```bash
npm  run  benchmark:test
```

**Balanced mode** (recommended for publication - 50 cold + 200 warm per config, ~$2-4):

```bash
uv  run  python  scripts/benchmark_orchestrator.py  --balanced
```

**Production mode** (maximum rigor - 100 cold + 500 warm per config, ~18-24 hours, ~$5-10):

```bash
uv  run  python  scripts/benchmark_orchestrator.py  --production
```

Each mode tests all 36 functions across multiple memory configurations. Higher modes provide better statistical confidence.

## Analyze Results

After running a benchmark, analyze the results:

```bash
# Analyze all results for a test run
uv  run  python  scripts/analyze_results.py <test-run-id>

# Filter by specific dimensions
uv  run  python  scripts/analyze_results.py <test-run-id> --runtime  python3.13
uv  run  python  scripts/analyze_results.py <test-run-id> --workload  cpu-intensive
uv  run  python  scripts/analyze_results.py <test-run-id> --architecture  arm64
```

**Output includes:**

- Performance comparisons (ARM vs x86, runtime vs runtime)
- Cold start vs warm start analysis
- Memory scaling charts
- Cost efficiency calculations
- Statistical summaries (mean, median, p50/p90/p95/p99) 

## Metrics Collected

For each invocation, the benchmark extracts from CloudWatch REPORT logs:
-  **Execution duration** (ms) - Actual function runtime
-  **Billed duration** (ms) - Rounded for AWS billing
-  **Max memory used** (MB) - Peak memory consumption
-  **Init duration** (ms) - Cold start initialization time (cold starts only)
-  **Client latency** (ms) - End-to-end time from orchestrator

Results are stored in DynamoDB with pre-computed aggregates (mean, median, p50/p90/p95/p99, std dev) for fast analysis.

**Zero overhead:** Metrics are parsed from CloudWatch logs, NOT measured in-function, ensuring no performance impact on benchmarks.

## Documentation

**Design & Architecture:**
- [`docs/benchmark-design.md`](./docs/benchmark-design.md) - Test matrix, workloads, orchestration
- [`DECISIONS.md`](./DECISIONS.md) - Architectural decision records (ADRs)

**Implementation:**
- [`docs/handler-api-spec.md`](./docs/handler-api-spec.md) - Lambda handler contract
- [`docs/metrics-collection-implementation.md`](./docs/metrics-collection-implementation.md) - CloudWatch REPORT parsing
- [`docs/dynamodb-schema.md`](./docs/dynamodb-schema.md) - Results storage schema

## Contributing

This is a research benchmark project. Feel free to fork it, or if you find issues or have suggestions:

1. Check existing [ADRs in DECISIONS.md](./DECISIONS.md) to understand design rationale
2. Review [benchmark-design.md](./docs/benchmark-design.md) for methodology
3. Open an issue with your findings or proposed changes

## Credits & References

-  **2023 AWS blog benchmark:** https://aws.amazon.com/blogs/apn/comparing-aws-lambda-arm-vs-x86-performance-cost-and-analysis-2/
-  **Forced cold start technique:** AJ Stuyvenberg - https://github.com/astuyve/cold-start-benchmarker
   - This approach helps us test cold start invocations much faster than having to re-deploy Lambdas or wait for all instances to become cold.
-  **Rust Lambda support:** https://aws.amazon.com/blogs/compute/building-serverless-applications-with-rust-on-aws-lambda/
-  **cargo-lambda-cdk:** https://github.com/cargo-lambda/cargo-lambda-cdk