import type { Context } from "aws-lambda";
import { createHash } from "crypto";

const DEFAULT_ITERATIONS = 1_000_000;
const MAX_ITERATIONS = 10_000_000;

interface BenchmarkEvent {
  iterations?: number;
}

interface BenchmarkSuccess {
  success: true;
  workloadType: 'cpu-intensive';
  iterations: number;
  architecture: string;
  memoryLimitMB: number;
  resultHash: string;
}

interface BenchmarkError {
  success: false;
  workloadType: 'cpu-intensive';
  error: string;
}

type BenchmarkResult = BenchmarkSuccess | BenchmarkError;

/**
 * Lambda handler - CPU intensive test executes SHA-256 hashing iterations to measure CPU performance
 */
export async function handler(event: BenchmarkEvent, context: Context): Promise<BenchmarkResult> {
  console.log(
    JSON.stringify({
      event: 'handler_start',
      workloadType: 'cpu-intensive',
      runtime: `nodejs${process.version}`,
      architecture: process.arch,
      requestId: context.awsRequestId
    })
  );

  const iterations = event.iterations ?? DEFAULT_ITERATIONS;

  if (iterations > MAX_ITERATIONS) {
    return {
      success: false,
      workloadType: 'cpu-intensive',
      error: `iterations too high (max ${MAX_ITERATIONS})`
    };
  }

  try {
    const result = cpuIntensiveWorkload(iterations);

    console.log(
      JSON.stringify({
        event: 'handler_success',
        iterations,
        resultHashLength: result.length
      })
    );

    return {
      success: true,
      workloadType: 'cpu-intensive',
      iterations,
      architecture: process.arch,
      memoryLimitMB: parseInt(context.memoryLimitInMB, 10),
      resultHash: result.slice(0, 64)
    };
  } catch (error) {
    console.error(
      JSON.stringify({
        event: 'handler_error',
        errorType: error instanceof Error ? error.constructor.name : 'Unknown',
        errorMessage: error instanceof Error ? error.message : String(error)
      })
    );

    return {
      success: false,
      workloadType: 'cpu-intensive',
      error: error instanceof Error ? error.message : String(error)
    };
  }
}

/**
 * Chains SHA-256 hashes together for CPU stress testing
 */
function cpuIntensiveWorkload(iterations: number): string {
  let data = Buffer.from('benchmark data for Lambda ARM vs x86 performance testing');

  for (let i = 0; i < iterations; i++) {
    data = createHash('sha256').update(data).digest(); // Keep as Buffer (more efficient)
  }

  return data.toString('hex');
}