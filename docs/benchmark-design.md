# Benchmark Design Overview

This document explains the overall benchmark approach taken for this repository.

### Goal

The goal of this benchmark is to compare AWS Lambda performance across current runtimes and architectures at the end of 2025. The goal of this benchmark is to focus on realistic workload patterns.

In this benchmark we have three different single-threaded workloads that we compare between x86_64 and ARM64 (Graviton) CPU architecture on current AWS supported runtimes for Node, Python, and Rust. I expected Rust to and ARM to be be best cost/performance choices but wanted to confirm my suspicion with data.

This design extends the 2023 AWS blog work to current runtimes and operating systems, which can be found here: [Comparing AWS Lambda Arm vs. x86 Performance, Cost, and Analysis](https://aws.amazon.com/blogs/apn/comparing-aws-lambda-arm-vs-x86-performance-cost-and-analysis-2/). This blog post was published in October 2023, and I haven't seen many similar benchmarks posted publicly since. The goal here was to create a similar test at the end of 2025.

### Test matrix dimensions

The following dimensions are tested in this benchmark:
- runtime (Python, Node.js, and Rust across current AWS-supported versions)
  - Python: 3.14, 3.13, 3.12, 3.11
  - Node.js: 22, 20
  - Rust: provided.al2023 (officially supported as of [Nov 14, 2025](https://aws.amazon.com/blogs/compute/building-serverless-applications-with-rust-on-aws-lambda/))
- ARM64 and x86_64 CPU architectures
- workload type (CPU intensive, memory intensive, light I/O)
- cold start vs warm start execution
- memory size to observe performance scaling

### Memory (Power) scaling approach

Lambda scales CPU linearly with memory until approximately 1,769 MB. Then, at 1,769 MB, you get a full vCPU allocation.

CPU-intensive and light I/O workloads are single-threaded and not particularly demanding on memory, so after 1769 MB of additional memory, there is no additional useful compute capacity. We expect performance to plateau after that point. For those workloads, we test memory sizes up to and just above the 1 vCPU threshold to confirm that this is the case.

The memory-intensive workload is still single-threaded but allocates and sorts large arrays. Its performance is affected by memory bandwidth/availability and allocation effects. It is intentionally tested with various memory configurations because the additional memory size may potentially changes the performance outcomes for that workload.

### Workloads

- **CPU-intensive**: This test workload is just a simple hashing loop to measure raw compute throughput.

- **Memory-intensive**: This test workload creates a **fixed 100 MB array** allocation and sorts it to measure performance scaling across different Lambda memory configurations. Using a constant workload size isolates the impact of CPU/memory resources on performance, rather than conflating workload size with resource size. Initially, this test was designed to increase memory allocation size with Lambda power, but it made the benchmark results confusing as invocation time would increase as the Lambda became more powerful. This test is more difficult to have parity with in Rust vs Python.
  - **Memory representation for cross-language parity:**
    - **Python**: Uses `array.array('q')` to store signed 64-bit integers (8 bytes per element)
    - **Node.js**: Uses `Float64Array` for 64-bit floats (8 bytes per element)
    - **Rust**: Uses `Vec<i64>` for 64-bit signed integers (8 bytes per element)
    - **Rationale**: Python's plain `list` with `int` objects uses ~28+ bytes per element due to object overhead. Using `array.array` and `Float64Array` provides memory parity across runtimes, ensuring an "apples-to-apples" comparison, as much as possible, where all runtimes allocate exactly 100 MB of data.
  - **Performance optimizations:**
    - **Python**: Uses `random.getrandbits(30)` for faster random generation; `list.sort()` in-place; `array.tobytes()` for binary hashing
    - **Node.js**: `Float64Array` for native memory; pre-allocated arrays
    - **Rust**: `StdRng::from_entropy()` for non-deterministic random generation; `sort_unstable()` for performance
  - *Note:* Sorting is CPU-intensive (O(n log n) comparisons), so this workload stresses both memory bandwidth (accessing all elements during swaps/comparisons) and CPU (comparison operations). This isn't purely a memory test but a combination of memory access and CPU.

- **Light**: This test workload uses minimal compute and leverages the AWS SDK to perform a DynamoDB batch write (5 items) followed by a batch read. The batch read-after-write pattern is common in real-world applications and tests both serialization (write) and deserialization (read) paths of the AWS SDK, providing a more complete picture of SDK overhead and I/O latency with realistic multi-item operations.
  - **Python**: Uses runtime boto3 SDK (`batch_write_item` and `batch_get_item`)
  - **Node.js**: Uses runtime @aws-sdk/client-dynamodb (`BatchWriteItemCommand` and `BatchGetItemCommand`)
  - **Rust**: Uses aws-sdk-dynamodb crate (compiled into binary)

### Testing approach

Cold start measurements use the forced cold start technique from AJ Stuyvenberg's see [Cold Start Benchmarker](https://github.com/astuyve/cold-start-benchmarker). We change the power configuration of the Lambda, wait a few moments, and then run a cold start test to invoke the Lambda. By changing the power configuration, we invalidated any warm Lambda instances and force the new invocation to initialize the Lambda. 

This approach simulates a cold start scenario where a Lambda has already been deployed, but for which there are no available warm instances for the next invocation. As pointed out by [AJ](https://aaronstuyvenberg.com/posts/ice-cold-starts) and [Yan Cui](https://lumigo.io/blog/this-is-all-you-need-to-know-about-lambda-cold-starts/) there are actually 3 different cold start scenarios, but this is by far the most common cold start scenario encountered by production applications.

Thanks to this cold start approach, we can complete the benchmark much faster than if we had to redeploy a Lambda to force a cold start or wait for an extended period for it to cool down.

### Metrics

We record:
- execution duration
- billed duration
- max memory used
- cold start initialization time (only present on cold starts)
- client latency at the caller


Metrics are extracted from the CloudWatch REPORT line returned via LogType Tail. This has zero overhead on the workload functions. Lambda handlers contain only workload logic, not timing logic.


Implementation details for metrics parsing are in [`metrics-collection-implementation.md`](./metrics-collection-implementation.md).


### Storage and analysis

All raw and aggregate statistics are stored in DynamoDB. Storage format, item types, key structure, and aggregations are documented in [`dynamodb-schema.md`](./dynamodb-schema.md).

Analysis should always use aggregate statistics instead of scanning raw items to reduce the number of DynamoDB reads required for analysis 

### References

- AJ Stuyvenberg cold start benchmark: [cold-start-benchmarker](https://github.com/astuyve/cold-start-benchmarker)
- [Comparing AWS Lambda Arm vs. x86 Performance, Cost, and Analysis](https://aws.amazon.com/blogs/apn/comparing-aws-lambda-arm-vs-x86-performance-cost-and-analysis-2/)

### Related Docs

- [`dynamodb-schema.md`](./dynamodb-schema.md)
- [`handler-api-spec.md`](./handler-api-spec.md)
- [`metrics-collection-implementation.md`](./metrics-collection-implementation.md)