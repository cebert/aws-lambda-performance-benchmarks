# AWS Lambda ARM vs x86 Performance Benchmark

## Project Overview

This project is a comprehensive performance benchmark comparing AWS Lambda ARM (Graviton2/3) vs x86 architectures across modern runtimes (Python 3.13/3.12/3.11, Node.js 22/20, Rust). It extends the [2023 AWS blog post](https://aws.amazon.com/blogs/apn/comparing-aws-lambda-arm-vs-x86-performance-cost-and-analysis-2/) with current runtime versions and best practices.

**Rust Support:** AWS officially announced Rust Lambda support on November 14, 2025. This benchmark uses the [`cargo-lambda-cdk`](https://github.com/cargo-lambda/cargo-lambda-cdk) construct library for deployment. See [AWS blog post](https://aws.amazon.com/blogs/compute/building-serverless-applications-with-rust-on-aws-lambda/) for details.

**Key Innovation:** Forced cold start technique (memory toggling) dramatically reduces test execution time compared to waiting for natural cold starts.

**Infrastructure:**
- 36 Lambda functions (6 runtimes × 2 architectures × 3 workloads)
  - Python: 3.13, 3.12, 3.11
  - Node.js: 22, 20
  - Rust: provided.al2023 runtime with cargo-lambda
- DynamoDB tables for results storage and test data (with TTL)
- CloudWatch Logs with short retention for cost optimization


---

## Quick Start Commands

### Deploy Infrastructure (idempotent)
```bash
# Full deployment from root
npm run deploy

# Or deploy from CDK directory
cd cdk
npm ci && npm run build
cdk bootstrap  # First time only
cdk deploy LambdaBenchmarkStack --require-approval never
```

### Run Benchmarks

**IMPORTANT:** Always ask user for confirmation before running benchmarks. Show:
- Mode (test vs balanced vs production)
- Configuration details (cold/warm starts, memory sizes)
- Estimated duration and cost

**Test Mode** (quick validation - 2 cold + 2 warm, ~10 min):
```bash
uv run python scripts/benchmark_orchestrator.py --test
```

**Balanced Mode** (publication-quality - 50 cold + 200 warm, ~6-8 hours, ~$2-4):
```bash
uv run python scripts/benchmark_orchestrator.py --balanced
```

**Production Mode** (maximum rigor - 100 cold + 500 warm, ~18-24 hours, ~$5-10):
```bash
uv run python scripts/benchmark_orchestrator.py --production
```

Configuration details in `scripts/benchmark_orchestrator.py` (TEST_CONFIG, BALANCED_CONFIG, PRODUCTION_CONFIG) and `scripts/benchmark_utils.py` (MEMORY_CONFIGS).

**EC2 Execution (Recommended for Balanced/Production):**
For Balanced (~1 hour) and Production (several hours) modes, AWS SSO tokens may expire mid-test. Use EC2 instance with IAM instance profile to avoid credential expiration:

```bash
# Launch EC2 that auto-runs benchmark and terminates when complete
uv run python scripts/run_benchmark_on_ec2.py --mode balanced
uv run python scripts/run_benchmark_on_ec2.py --mode production
uv run python scripts/run_benchmark_on_ec2.py --mode production --s3-bucket my-results
```

Benefits: No SSO token expiration, immune to laptop sleep/network issues, auto-terminates.

### Analyze Results
```bash
uv run python scripts/analyze_results.py <test-run-id>
uv run python scripts/analyze_results.py <test-run-id> --runtime python3.13
uv run python scripts/analyze_results.py <test-run-id> --workload cpu-intensive
```

---

## Critical Invariants

1. **Zero-overhead metrics collection**: CPU/Memory workloads MUST NOT import AWS SDK. All metrics extracted from CloudWatch REPORT line using `LogType='Tail'`.
2. **Forced cold starts**: Achieved by toggling memory size via `UpdateFunctionConfiguration`, NOT by waiting for natural cold starts.
3. **Dynamic memory configuration**: Memory settings changed at runtime via `UpdateFunctionConfiguration` API, NOT by deploying separate functions.
4. **Benchmark purity**: Only Light workload (DynamoDB) imports AWS SDK; CPU/Memory workloads are pure computation.
5. **Function discovery**: Orchestrator discovers functions via `list_stack_resources()`, not CloudFormation outputs.

**Configuration Authority:**
- Lambda configs: `cdk/lib/config/lambda-config.ts` (runtimes, architectures, workloads)
- Memory configs: `scripts/benchmark_utils.py` (`MEMORY_CONFIGS` dict)
- Memory-intensive workload: Fixed 100 MB array (constant across all Lambda memory sizes)

---

## Project Structure

**Infrastructure (`cdk/`):**
- `lib/config/lambda-config.ts` - 36 function configs (6 runtimes × 2 architectures × 3 workloads)
- `lib/constructs/` - Lambda, DynamoDB table constructs
- `lib/cdk-stack.ts` - Main CDK stack

**Lambda Handlers (`lambdas/`):**
- `python/` - Python 3.13/3.12/3.11 handlers
- `nodejs/` - Node.js 22/20 handlers (TypeScript)
- `rust/` - Rust handlers (provided.al2023)
- Each runtime has 3 workloads: `cpu-intensive` (SHA-256), `memory-intensive` (array sort), `light` (DynamoDB I/O)
- **Important:** Only Light workload imports AWS SDK; CPU/Memory are pure computation

**Orchestration & Analysis (`scripts/`):**
- `benchmark_orchestrator.py` - Test execution, forced cold starts, metrics collection
- `benchmark_utils.py` - Shared constants (MEMORY_CONFIGS), DynamoDB helpers
- `analyze_results.py` - Results analysis and visualization

**Documentation (`docs/`):**
- `benchmark-design.md` - Architecture, test matrix, workload descriptions
- `handler-api-spec.md` - Lambda handler contract
- `metrics-collection-implementation.md` - CloudWatch REPORT parsing
- `dynamodb-schema.md` - DynamoDB schema (result/aggregate/test-run entities)

---

## Documentation

**Start Here:**
- [README.md](README.md) - User-facing quick start
- [DECISIONS.md](DECISIONS.md) - Architectural decision records (ADRs)
- [docs/benchmark-design.md](docs/benchmark-design.md) - Test matrix, workloads, forced cold starts, orchestration

**Critical ADRs (Read Before Changes):**
- **D009**: Zero-Overhead Data Collection (CloudWatch REPORT parsing, no SDK in CPU/Memory handlers)
- **D011**: AWS SDK Strategy (SDK only in Light workload)
- **D015**: Optimized Deployment (36 functions with dynamic memory vs 1,368 static)
- **D016**: Fixed Memory Allocation (Memory-intensive uses constant 100 MB array)

---

## Common Development Tasks

**Build & Deploy:**
```bash
npm run build       # Build TypeScript (lambdas/nodejs and CDK)
npm run deploy      # Deploy CDK stack
npm run lint        # All linters (TypeScript + Python)
npm run lint:ts:fix # Auto-fix TypeScript
npm run lint:py:fix # Auto-fix Python (ruff)
```

**Add Runtime/Workload:**
1. Add to `cdk/lib/config/lambda-config.ts` (PYTHON_RUNTIMES, NODEJS_RUNTIMES, RUST_RUNTIMES, or WORKLOADS)
2. Create handler: `lambdas/<runtime>/<workload>/handler.{py,ts}` or `src/main.rs`
3. Update `scripts/benchmark_utils.py` (MEMORY_CONFIGS) if needed
4. Deploy and update documentation (see table below)

**Note:** Rust handlers use `cargo-lambda-cdk` which compiles during CDK synthesis. Requires cargo-lambda or Docker.

---

## Documentation Updates

**Update docs when changing:**

| Change | Update Files |
|--------|-------------|
| **Runtimes/workloads** | `lambda-config.ts`, `CLAUDE.md`, `README.md`, `benchmark-design.md`, `handler-api-spec.md` |
| **Memory configs** | `benchmark_utils.py`, `benchmark_orchestrator.py`, `benchmark-design.md` |
| **Orchestration** | `benchmark-design.md`, `CLAUDE.md` (invariants) |
| **DynamoDB schema** | `dynamodb-schema.md` |
| **Architecture** | Add ADR to `DECISIONS.md` with status, rationale, impact |

---

## AWS Configuration & Troubleshooting

**Region:** `us-east-2` (set via `CDK_DEFAULT_REGION` or `AWS_REGION`)

**Resources:** 36 Lambda functions, 2 DynamoDB tables (BenchmarkResults, BenchmarkTestData), CloudWatch Logs, IAM roles

**Common Issues:**
```bash
# Lambda invocation issues - check logs
aws logs tail /aws/lambda/<function-name> --follow

# Missing Python dependencies
uv sync --all-extras

# Deployment failures - clean redeploy
cdk destroy LambdaBenchmarkStack && npm run deploy

# Python linting (C401, SIM113 warnings expected)
npm run lint:py:fix
```

---

## References

- [2023 AWS Lambda ARM vs x86 Blog Post](https://aws.amazon.com/blogs/apn/comparing-aws-lambda-arm-vs-x86-performance-cost-and-analysis-2/) - Original benchmark this extends
- [AJ Stuyvenberg's cold-start-benchmarker](https://github.com/astuyve/cold-start-benchmarker) - Forced cold start technique
- [AWS Lambda Rust Support](https://aws.amazon.com/blogs/compute/building-serverless-applications-with-rust-on-aws-lambda/) - Nov 2025 announcement
- [AWS Graviton Performance](https://aws.amazon.com/ec2/graviton/)

