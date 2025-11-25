use lambda_runtime::{run, service_fn, Error, LambdaEvent};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::env;

const DEFAULT_ITERATIONS: u32 = 500_000;
const WORKLOAD_TYPE: &str = "cpu-intensive";

// Architecture determined at compile time - const for zero runtime overhead
const ARCHITECTURE: &str = if cfg!(target_arch = "aarch64") {
    "aarch64"
} else {
    "x86_64"
};

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Request {
    #[serde(default = "default_iterations")]
    iterations: u32,
}

fn default_iterations() -> u32 {
    DEFAULT_ITERATIONS
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Response {
    success: bool,
    workload_type: String,
    iterations: u32,
    architecture: String,
    memory_limit_mb: u32,
    result_hash: String,
}

/// Lambda handler - CPU intensive test executes SHA-256 hashing iterations to measure CPU performance.
///
/// Executes repeated SHA-256 hashing in a tight loop to measure raw compute
/// performance differences between architectures and runtimes.
async fn function_handler(event: LambdaEvent<Request>) -> Result<Response, Error> {
    let (payload, _context) = event.into_parts();

    let iterations = payload.iterations;

    let result_hash = cpu_intensive_workload(iterations);

    let memory_limit_mb = env::var("AWS_LAMBDA_FUNCTION_MEMORY_SIZE")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);

    Ok(Response {
        success: true,
        workload_type: WORKLOAD_TYPE.to_string(),
        iterations,
        architecture: ARCHITECTURE.to_string(),
        memory_limit_mb,
        result_hash,
    })
}

/// Chains SHA-256 hashes together for CPU stress testing.
///
/// Match Python/Node.js implementation exactly:
/// - Start with same benchmark string
/// - Chain hash output as next input
/// - No extra work (no iteration counter)
///
/// Optimized to:
/// - Reuse hasher via Digest::reset() instead of allocating new one each iteration
/// - Use fixed-size array [u8; 32] instead of Vec allocation each iteration
fn cpu_intensive_workload(iterations: u32) -> String {
    // First iteration: hash the seed string
    let mut hasher = Sha256::new();
    hasher.update(b"benchmark data for Lambda ARM vs x86 performance testing");
    let mut hash: [u8; 32] = hasher.finalize_reset().into();

    // Remaining iterations: chain hashes, reusing the hasher
    for _ in 1..iterations {
        hasher.update(&hash);
        hash = hasher.finalize_reset().into();
    }

    hex::encode(hash)
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::INFO)
        .with_target(false)
        .without_time()
        .init();

    run(service_fn(function_handler)).await
}
