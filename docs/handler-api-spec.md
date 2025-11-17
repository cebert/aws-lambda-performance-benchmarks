# Lambda Handler API Specification

This document explains the request and response contracts used by the benchmark workloads. There's a design goal to
keep TypeScript, Python, and Rust handlers as similar as possible in terms of behavior so that we can compare results across runtimes.

## Invocation model

- Direct Lambda invocation with the AWS SDK
- No API Gateway wrapper and no `statusCode` envelopes
- Handlers receive a small JSON payload and return a small JSON object

## Discriminated response union

All handlers return one of two shapes. The `success` field specifies the variant.

**Success**

```json
{
   "success": true,
   "workloadType": "cpu-intensive"  |  "memory-intensive"  |  "light",
   // Additional workload-specific fields (see examples below)
}
```

**Error**

```json
{
   "success": false,
   "workloadType": "cpu-intensive"  |  "memory-intensive"  |  "light",
   "error": "string"  // human-readable message
}
```

## Request payload

Each workload type receives a minimal, flat JSON payload with workload-specific parameters.

**CPU-intensive workload:**

```json
{
   "iterations": 1000000  // SHA-256 hashing loop size
}
```

  

**Memory-intensive workload:**

```json
{}  // No parameters - uses fixed 100 MB array (hardcoded in handlers)
```

The memory-intensive workload uses a **fixed 100 MB array** across all Lambda memory configurations. This constant workload size:
- Enables clear performance plateau visualization (when does adding more CPU/memory stop helping?)
- Provides apples-to-apples comparison across Lambda memory configs
- Faster benchmark execution (no multi-GB arrays at high memory configs)
- Separates variables: constant work with variable resources reveals pure scaling behavior

All three runtime implementations (Python, Node.js, Rust) allocate exactly 100 MB of data using 8-byte elements.

**Light workload:**

```json
{} // No parameters needed
```


Rules

- Handlers must ignore unknown keys in the event payload.
- Choose safe defaults when parameters are unspecified so test mode can run without flags.
- The orchestrator does NOT pass `workloadType` or `memorySizeMB` in the event payload.

## Response examples by workload

### CPU-intensive workload

**Success response:**

```json
{
   "success": true,
   "workloadType": "cpu-intensive",
   "iterations": 1000000,
   "architecture": "x86_64", // or "aarch64" (Rust: "x86_64" or "aarch64")
   "pythonVersion": "3.13.0", // Python only
   "memoryLimitMB": 1769,
   "resultHash": "abc123..."  // Final SHA-256 hash (hex, 64 chars)
}
```

**Runtime-specific fields:**
- **Python**: Includes `pythonVersion` (e.g., "3.13.0")
- **Node.js**: No version field (runtime version is part of the function configuration)
- **Rust**: No version field (uses provided.al2023 runtime)

### Memory-intensive workload

**Success response:**

```json
{
   "success": true,
   "workloadType": "memory-intensive",
   "sizeMB": 100,
   "architecture": "arm64",
   "memoryLimitMB": 1769,
   "resultHash": "abc123..."  // SHA-256 hash of first 1000 sorted elements (hex, 64 chars)
}
```


### Light workload

**Success response:**

```json
{
   "success": true,
   "workloadType": "light",
   "architecture": "x64",
   "memoryLimitMB": 512,
   "itemsWritten": 5,  // Number of items written in batch
   "itemsRead": 5,     // Number of items read in batch
   "writeRequestId": "abc-def-123",  // DynamoDB batch write request ID
   "readRequestId": "xyz-uvw-456",   // DynamoDB batch read request ID
   "allDataMatches": true  // Verification that all written data matches read data
}
```

## Response field stability

The orchestrator extracts and stores these fields from handler responses:
-  `success` (boolean) - Required on all responses
-  `workloadType` (string) - Required on all responses
-  `error` (string) - Required on error responses

All other fields are workload-specific metadata and may vary by runtime/language.


## Related documentation
- [benchmark-design.md](./benchmark-design.md)
- [dynamodb-schema.md](./dynamodb-schema.md)
- [metrics-collection-implementation.md](./metrics-collection-implementation.md)
