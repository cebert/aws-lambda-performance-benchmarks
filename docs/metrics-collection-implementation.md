# Metrics Collection Implementation

This document explains how benchmark timings are collected without modifying workload code and only using CloudWatch.

## Summary

- The orchestrator invokes functions with `LogType="Tail"`
- Lambda returns the last 4 KB of logs base64 encoded in `LogResult`
- The CloudWatch `REPORT` line contains the timing fields we need
- We parse the `REPORT` line locally and write metrics to DynamoDB
- Handlers contain only workload logic

No Telemetry API is required since we can just get this data from the logs.

## Fields we extract from the REPORT line

-  `Duration` in milliseconds (stored as `durationMs`)
-  `Billed Duration` in milliseconds (stored as `billedDurationMs`)
-  `Max Memory Used` in MB (stored as `maxMemoryUsedMB`)
-  `Init Duration` in milliseconds (stored as `initDurationMs`, present only on cold starts)

## Cold and warm detection

- Cold starts are produced by changing a function environment variable between invocations
- Warm starts reuse the same execution environment
-  `Init Duration` appears only on cold starts which gives a second signal that a sample was cold

The cold start technique is credited to AJ Stuyvenberg. See the repo linked below.

## Parse flow

1. Invoke with `LogType="Tail"`
2. Base64 decode `LogResult`
3. Find the single line that starts with `REPORT` and parse key values
4. Store parsed values with the associated `testRunId`, `configId`, and `invocationType`

Parsing should be tolerant to minor formatting differences across runtimes.

## Failure handling

- If the handler returns an error variant, still record the `REPORT` metrics and attach the error string on the result item
- If the invocation fails before a `REPORT` line is produced, record a result item with an explicit failure flag and no timing fields
- Do not retry failed invocations inside the metrics module. Retries are orchestrator policy

## Gotchas

-  `Init Duration` is only present on cold starts
-  `Billed Duration` is rounded up which is expected
- The `REPORT` line may include extra fields in some runtimes. Unknown fields can be ignored
- Do not log large payloads. The `LogResult` limit is 4 KB


## Implementation references

- [AJ Stuyvenberg cold start benchmarker](https://github.com/astuyve/cold-start-benchmarker)
- [benchmark-design.md](./benchmark-design.md)
- [dynamodb-schema.md](./dynamodb-schema.md)
- [handler-api-spec.md](./handler-api-spec.md)
