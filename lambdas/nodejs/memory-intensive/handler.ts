import type { Context } from "aws-lambda";
import { createHash } from "crypto";

// Fixed array size for consistent performance measurement across Lambda memory configs
const FIXED_ARRAY_SIZE_MB = 100;

interface BenchmarkEvent {
  // Event is currently unused but kept for API consistency
}

interface BenchmarkSuccess {
  success: true;
  workloadType: 'memory-intensive';
  sizeMB: number;
  architecture: string;
  memoryLimitMB: number;
  resultHash: string;
}

interface BenchmarkError {
  success: false;
  workloadType: 'memory-intensive';
  error: string;
}

type BenchmarkResult = BenchmarkSuccess | BenchmarkError;

/**
 * Lambda handler - Memory intensive memory workload benchmark allocates and sorts a fixed 
 * 100 MB array to measure performance scaling across different Lambda memory configurations.
 */
export async function handler(_event: BenchmarkEvent, context: Context): Promise<BenchmarkResult> {
  console.log(
    JSON.stringify({
      event: 'handler_start',
      workloadType: 'memory-intensive',
      runtime: `nodejs${process.version}`,
      architecture: process.arch,
      requestId: context.awsRequestId
    })
  );

  try {
    const result = memoryIntensiveWorkload(FIXED_ARRAY_SIZE_MB);

    console.log(
      JSON.stringify({
        event: 'handler_success',
        sizeMB: FIXED_ARRAY_SIZE_MB,
        arrayElements: Math.floor((FIXED_ARRAY_SIZE_MB * 1024 * 1024) / 8)
      })
    );

    return {
      success: true,
      workloadType: 'memory-intensive',
      sizeMB: FIXED_ARRAY_SIZE_MB,
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
      workloadType: 'memory-intensive',
      error: error instanceof Error ? error.message : String(error)
    };
  }
}

/**
 * Allocates and sorts fixed 100 MB array to stress memory bandwidth
 *
 * Sort operation stresses both memory bandwidth (accessing all elements)
 * and CPU (comparison operations), providing comprehensive memory subsystem test.
 */
function memoryIntensiveWorkload(sizeMB: number): string {
  const arraySize = Math.floor((sizeMB * 1024 * 1024) / 8); // Float64 = 8 bytes

  // Use Float64Array for true 8-byte elements (memory parity with Python array.array('q') and Rust Vec<i64>)
  const randomNumberArray = new Float64Array(arraySize);
  for (let i = 0; i < arraySize; i++) {
    randomNumberArray[i] = Math.floor(Math.random() * 1_073_741_824);
  }

  randomNumberArray.sort();

  const sample = JSON.stringify(randomNumberArray.slice(0, 1000));
  const result = createHash('sha256').update(sample).digest('hex');
  return result;
}
