import { Architecture, Runtime } from "aws-cdk-lib/aws-lambda";

/**
 * Workload type definitions
 */
export type WorkloadType = 'cpu-intensive' | 'memory-intensive' | 'light';

/**
 * Runtime configuration with CDK Runtime and path
 */
export interface RuntimeConfig {
  readonly id: string; // e.g., "python3.13", "nodejs22"
  readonly runtime: Runtime;
  readonly handler: string; // e.g., "handler.lambda_handler", "handler.handler"
  readonly codePath: string; // e.g., "../lambdas/python", "../lambdas/nodejs"
}

/**
 * Architecture configuration
 */
export interface ArchitectureConfig {
  readonly id: string; // e.g., "arm64", "x86"
  readonly architecture: Architecture;
}

/**
 * Workload configuration
 */
export interface WorkloadConfig {
  readonly type: WorkloadType;
  readonly description: string;
  readonly handlerDir: string; // Subdirectory for handler (e.g., "cpu-intensive")
}

/**
 * Complete Lambda function configuration
 */
export interface LambdaFunctionConfig {
  readonly functionName: string;
  readonly runtime: RuntimeConfig;
  readonly architecture: ArchitectureConfig;
  readonly workload: WorkloadConfig;
  readonly codePath: string; // Full path to handler directory
  readonly initialMemoryMB: number;
  readonly timeoutSeconds: number;
}

/**
 * Supported Python runtimes
 */
export const PYTHON_RUNTIMES: RuntimeConfig[] = [
  {
    id: 'python3.14',
    runtime: Runtime.PYTHON_3_14,
    handler: 'handler.lambda_handler',
    codePath: '../lambdas/python',
  },
  {
    id: 'python3.13',
    runtime: Runtime.PYTHON_3_13,
    handler: 'handler.lambda_handler',
    codePath: '../lambdas/python',
  },
  {
    id: 'python3.12',
    runtime: Runtime.PYTHON_3_12,
    handler: 'handler.lambda_handler',
    codePath: '../lambdas/python',
  },
  {
    id: 'python3.11',
    runtime: Runtime.PYTHON_3_11,
    handler: 'handler.lambda_handler',
    codePath: '../lambdas/python',
  },
];

/**
 * Supported Node.js runtimes
 */
export const NODEJS_RUNTIMES: RuntimeConfig[] = [
  {
    id: 'nodejs22',
    runtime: Runtime.NODEJS_22_X,
    handler: 'handler.handler',
    codePath: '../lambdas/nodejs',
  },
  {
    id: 'nodejs20',
    runtime: Runtime.NODEJS_20_X,
    handler: 'handler.handler',
    codePath: '../lambdas/nodejs',
  },
];

/**
 * Supported Rust runtime
 * Uses custom runtime (provided.al2023) with binary "bootstrap"
 */
export const RUST_RUNTIMES: RuntimeConfig[] = [
  {
    id: 'rust',
    runtime: Runtime.PROVIDED_AL2023,
    handler: 'bootstrap', // Rust uses "bootstrap" binary, not a handler function
    codePath: '../lambdas/rust',
  },
];

/**
 * All supported runtimes
 */
export const ALL_RUNTIMES: RuntimeConfig[] = [...PYTHON_RUNTIMES, ...NODEJS_RUNTIMES, ...RUST_RUNTIMES];

/**
 * Supported architectures
 */
export const ARCHITECTURES: ArchitectureConfig[] = [
  {
    id: 'arm64',
    architecture: Architecture.ARM_64,
  },
  {
    id: 'x86',
    architecture: Architecture.X86_64,
  },
];

/**
 * Workload configurations
 *
 * Note: Memory configurations for testing are defined in scripts/benchmark_utils.py
 * The orchestrator dynamically changes memory via UpdateFunctionConfiguration API
 */
export const WORKLOADS: WorkloadConfig[] = [
  {
    type: 'cpu-intensive',
    description: 'CPU-intensive workload (SHA-256 hashing)',
    handlerDir: 'cpu-intensive',
  },
  {
    type: 'memory-intensive',
    description: 'Memory-intensive workload (large array sorting)',
    handlerDir: 'memory-intensive',
  },
  {
    type: 'light',
    description: 'Light I/O workload (DynamoDB write)',
    handlerDir: 'light',
  },
];

/**
 * Generate all 42 Lambda function configurations
 * (7 runtimes × 2 architectures × 3 workloads = 42 functions)
 * Runtimes: Python 3.14/3.13/3.12/3.11, Node.js 22/20, Rust
 */
export function generateLambdaConfigurations(): LambdaFunctionConfig[] {
  const configurations: LambdaFunctionConfig[] = [];

  for (const runtime of ALL_RUNTIMES) {
    for (const architecture of ARCHITECTURES) {
      for (const workload of WORKLOADS) {
        // Replace periods in runtime ID (e.g., python3.13 -> python3-13)
        const runtimeId = runtime.id.replace(/\./g, '-');
        const functionName = `${runtimeId}-${architecture.id}-${workload.type}`;

        const initialMemoryMB = 1769;
        const timeoutSeconds = 240;

        // Handler path includes subdirectory
        // Python: "cpu-intensive/handler.lambda_handler"
        // Node.js: "dist/cpu-intensive/handler.handler"
        // Rust: "bootstrap" (custom runtime binary)
        const codePath = runtime.codePath;
        const isNodeJs = runtime.id.startsWith('nodejs');
        const isRust = runtime.id === 'rust';

        const handlerPath = isRust
          ? 'bootstrap' // Rust uses bootstrap binary
          : isNodeJs
            ? `dist/${workload.handlerDir}/handler.${runtime.handler.split('.')[1]}`
            : `${workload.handlerDir}/handler.${runtime.handler.split('.')[1]}`;

        configurations.push({
          functionName,
          runtime: {
            ...runtime,
            handler: handlerPath,
          },
          architecture,
          workload,
          codePath,
          initialMemoryMB,
          timeoutSeconds,
        });
      }
    }
  }
  return configurations;
}

/**
 * Get total number of base Lambda functions deployed
 * (Does not include dynamic memory configurations - those are managed by orchestrator)
 */
export function getTotalFunctionsDeployed(): number {
  return ALL_RUNTIMES.length * ARCHITECTURES.length * WORKLOADS.length;
}
