use lambda_runtime::{run, service_fn, Error, LambdaEvent};
use rand::{Rng, SeedableRng};
use rand::rngs::StdRng;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::env;

// Fixed array size for consistent performance measurement across Lambda memory configs
const FIXED_ARRAY_SIZE_MB: u32 = 100;
const WORKLOAD_TYPE: &str = "memory-intensive";

// Architecture determined at compile time - const for zero runtime overhead
const ARCHITECTURE: &str = if cfg!(target_arch = "aarch64") {
    "aarch64"
} else {
    "x86_64"
};

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Request {
    // Event is currently unused but kept for API consistency
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Response {
    success: bool,
    workload_type: String,
    size_mb: u32,
    architecture: String,
    memory_limit_mb: u32,
    result_hash: String,
}

/// Lambda handler - Memory intensive workload benchmark.
///
/// Allocates and sorts a fixed 100 MB array to measure performance scaling
/// across different Lambda memory configurations. Uses constant workload size
/// to isolate the impact of CPU/memory resources on performance, rather than
/// conflating workload size with resource size.
async fn function_handler(event: LambdaEvent<Request>) -> Result<Response, Error> {
    let (_payload, _context) = event.into_parts();

    // Get memory limit from environment
    let memory_limit_mb: u32 = env::var("AWS_LAMBDA_FUNCTION_MEMORY_SIZE")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);

    // Perform memory-intensive work with fixed 100 MB array
    let result_hash = memory_intensive_workload(FIXED_ARRAY_SIZE_MB);

    Ok(Response {
        success: true,
        workload_type: WORKLOAD_TYPE.to_string(),
        size_mb: FIXED_ARRAY_SIZE_MB,
        architecture: ARCHITECTURE.to_string(),
        memory_limit_mb,
        result_hash,
    })
}

/// Allocates and sorts fixed 100 MB array to stress memory bandwidth.
///
/// Sort operation stresses both memory bandwidth (accessing all elements)
/// and CPU (comparison operations), providing comprehensive memory subsystem test.
fn memory_intensive_workload(size_mb: u32) -> String {
    // Calculate array size: size_mb MB worth of i64 integers (8 bytes each)
    // This matches Python's array.array('q') and Node.js Float64Array for memory parity
    let bytes = size_mb as u64 * 1024 * 1024;
    let count = (bytes / 8) as usize;

    // Pre-allocate with exact capacity to avoid reallocation
    let mut data = Vec::<i64>::with_capacity(count);

    // Generate NON-DETERMINISTIC random numbers (matches Python/Node.js behavior)
    // Python uses random.getrandbits(30), Node uses Math.random()
    // Both produce different results on each run - this is correct for benchmarking
    // as it prevents CPU caching optimizations across runs
    let mut rng = StdRng::from_entropy(); // Non-deterministic seed

    for _ in 0..count {
        data.push(rng.gen_range(0..1_073_741_824)); // 30-bit range like Python
    }

    // Sort the array (in-place, unstable for performance)
    data.sort_unstable();

    // Hash first 1000 elements for verification
    let sample_size = std::cmp::min(1000, data.len());

    // Serialize sample - should never fail, but if it does, we want to know
    let sample_json = serde_json::to_string(&data[..sample_size])
        .expect("Failed to serialize sample data for hashing");

    let mut hasher = Sha256::new();
    hasher.update(sample_json.as_bytes());
    hex::encode(hasher.finalize())
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
