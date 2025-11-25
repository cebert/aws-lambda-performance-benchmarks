# Benchmark Results - November 2025

## Test Run Information

- **Date**: November 22, 2025
- **Mode**: Production
- **Region**: us-east-2
- **Total Configurations**: 294
- **Total Invocations**: 183,750
- **Cold Starts per Config**: 125
- **Warm Starts per Config**: 500

### Test Matrix

- **Runtimes**: nodejs20, nodejs22, python3.11, python3.12, python3.13, python3.14, rust
- **Architectures**: arm64, x86
- **Workload Types**: cpu-intensive, light, memory-intensive
- **Total Configurations**: 42

<details>
<summary>Click to view full configuration matrix</summary>

    | Runtime | Architecture | Workload | Memory Sizes (MB) |
    |---------|--------------|----------|-------------------|
    | nodejs20 | arm64 | cpu-intensive | 128, 256, 512, 1024, 1769, 2048 |
    | nodejs20 | arm64 | light | 128, 256, 512, 1024, 1769, 2048 |
    | nodejs20 | arm64 | memory-intensive | 128, 256, 512, 1024, 1769, 2048, 4096, 8192, 10240 |
    | nodejs20 | x86 | cpu-intensive | 128, 256, 512, 1024, 1769, 2048 |
    | nodejs20 | x86 | light | 128, 256, 512, 1024, 1769, 2048 |
    | nodejs20 | x86 | memory-intensive | 128, 256, 512, 1024, 1769, 2048, 4096, 8192, 10240 |
    | nodejs22 | arm64 | cpu-intensive | 128, 256, 512, 1024, 1769, 2048 |
    | nodejs22 | arm64 | light | 128, 256, 512, 1024, 1769, 2048 |
    | nodejs22 | arm64 | memory-intensive | 128, 256, 512, 1024, 1769, 2048, 4096, 8192, 10240 |
    | nodejs22 | x86 | cpu-intensive | 128, 256, 512, 1024, 1769, 2048 |
    | nodejs22 | x86 | light | 128, 256, 512, 1024, 1769, 2048 |
    | nodejs22 | x86 | memory-intensive | 128, 256, 512, 1024, 1769, 2048, 4096, 8192, 10240 |
    | python3.11 | arm64 | cpu-intensive | 128, 256, 512, 1024, 1769, 2048 |
    | python3.11 | arm64 | light | 128, 256, 512, 1024, 1769, 2048 |
    | python3.11 | arm64 | memory-intensive | 128, 256, 512, 1024, 1769, 2048, 4096, 8192, 10240 |
    | python3.11 | x86 | cpu-intensive | 128, 256, 512, 1024, 1769, 2048 |
    | python3.11 | x86 | light | 128, 256, 512, 1024, 1769, 2048 |
    | python3.11 | x86 | memory-intensive | 128, 256, 512, 1024, 1769, 2048, 4096, 8192, 10240 |
    | python3.12 | arm64 | cpu-intensive | 128, 256, 512, 1024, 1769, 2048 |
    | python3.12 | arm64 | light | 128, 256, 512, 1024, 1769, 2048 |
    | python3.12 | arm64 | memory-intensive | 128, 256, 512, 1024, 1769, 2048, 4096, 8192, 10240 |
    | python3.12 | x86 | cpu-intensive | 128, 256, 512, 1024, 1769, 2048 |
    | python3.12 | x86 | light | 128, 256, 512, 1024, 1769, 2048 |
    | python3.12 | x86 | memory-intensive | 128, 256, 512, 1024, 1769, 2048, 4096, 8192, 10240 |
    | python3.13 | arm64 | cpu-intensive | 128, 256, 512, 1024, 1769, 2048 |
    | python3.13 | arm64 | light | 128, 256, 512, 1024, 1769, 2048 |
    | python3.13 | arm64 | memory-intensive | 128, 256, 512, 1024, 1769, 2048, 4096, 8192, 10240 |
    | python3.13 | x86 | cpu-intensive | 128, 256, 512, 1024, 1769, 2048 |
    | python3.13 | x86 | light | 128, 256, 512, 1024, 1769, 2048 |
    | python3.13 | x86 | memory-intensive | 128, 256, 512, 1024, 1769, 2048, 4096, 8192, 10240 |
    | python3.14 | arm64 | cpu-intensive | 128, 256, 512, 1024, 1769, 2048 |
    | python3.14 | arm64 | light | 128, 256, 512, 1024, 1769, 2048 |
    | python3.14 | arm64 | memory-intensive | 128, 256, 512, 1024, 1769, 2048, 4096, 8192, 10240 |
    | python3.14 | x86 | cpu-intensive | 128, 256, 512, 1024, 1769, 2048 |
    | python3.14 | x86 | light | 128, 256, 512, 1024, 1769, 2048 |
    | python3.14 | x86 | memory-intensive | 128, 256, 512, 1024, 1769, 2048, 4096, 8192, 10240 |
    | rust | arm64 | cpu-intensive | 128, 256, 512, 1024, 1769, 2048 |
    | rust | arm64 | light | 128, 256, 512, 1024, 1769, 2048 |
    | rust | arm64 | memory-intensive | 128, 256, 512, 1024, 1769, 2048, 4096, 8192, 10240 |
    | rust | x86 | cpu-intensive | 128, 256, 512, 1024, 1769, 2048 |
    | rust | x86 | light | 128, 256, 512, 1024, 1769, 2048 |
    | rust | x86 | memory-intensive | 128, 256, 512, 1024, 1769, 2048, 4096, 8192, 10240 |

</details>

## Summary Statistics

- **Total Aggregates**: 583
- **Runtimes Tested**: nodejs22, nodejs20, python3.14, python3.13, python3.12, python3.11, rust
- **Workload Types**: cpu-intensive, light, memory-intensive
- **Architectures**: arm64, x86

## Contents

### Comparison Tables

- [CPU Intensive Workload](tables/cpu-intensive/)
  - [Cold Starts](tables/cpu-intensive/cold.md)
  - [Warm Starts](tables/cpu-intensive/warm.md)
- [Light Workload](tables/light/)
  - [Cold Starts](tables/light/cold.md)
  - [Warm Starts](tables/light/warm.md)
- [Memory Intensive Workload](tables/memory-intensive/)
  - [Cold Starts](tables/memory-intensive/cold.md)
  - [Warm Starts](tables/memory-intensive/warm.md)

### Charts

- [CPU Intensive Workload](charts/cpu-intensive/)
  - Memory Scaling (cold & warm)
  - P99 Duration Scaling (cold & warm)
  - Cost Effectiveness (cold & warm)
  - Runtime Family P99 Comparison (warm)
- [Light Workload](charts/light/)
  - Memory Scaling (cold & warm)
  - P99 Duration Scaling (cold & warm)
  - Cost Effectiveness (cold & warm)
  - Runtime Family P99 Comparison (warm)
- [Memory Intensive Workload](charts/memory-intensive/)
  - Memory Scaling (cold & warm)
  - P99 Duration Scaling (cold & warm)
  - Cost Effectiveness (cold & warm)
  - Runtime Family P99 Comparison (warm)
- [Cold Start Analysis](charts/cold-start-analysis.png)

