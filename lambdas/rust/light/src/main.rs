use aws_config::BehaviorVersion;
use aws_sdk_dynamodb::{
    operation::RequestId,
    types::AttributeValue,
    Client,
};
use lambda_runtime::{run, service_fn, Error, LambdaEvent};
use serde::{Deserialize, Serialize};
use std::env;
use std::time::{SystemTime, UNIX_EPOCH};

const WORKLOAD_TYPE: &str = "light";

// Architecture determined at compile time - const for zero runtime overhead
const ARCHITECTURE: &str = if cfg!(target_arch = "aarch64") {
    "aarch64"
} else {
    "x86_64"
};

#[derive(Deserialize)]
struct Request {}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SuccessResponse {
    success: bool,
    workload_type: String,
    architecture: String,
    memory_limit_mb: u32,
    items_written: usize,
    items_read: usize,
    write_request_id: String,
    read_request_id: String,
    all_data_matches: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ErrorResponse {
    success: bool,
    workload_type: String,
    error: String,
}

#[derive(Serialize)]
#[serde(untagged)]
enum Response {
    Success(SuccessResponse),
    Error(ErrorResponse),
}

/// Lambda handler - Light workload benchmark.
///
/// Performs a DynamoDB batch write (5 items) followed by a batch read to measure
/// baseline Lambda invocation and SDK initialization overhead with realistic
/// multi-item I/O patterns.
async fn function_handler(client: &Client, event: LambdaEvent<Request>) -> Result<Response, Error> {
    let (_payload, _context) = event.into_parts();

    let table_name = env::var("DYNAMODB_TABLE_NAME")
        .unwrap_or_else(|_| "benchmark-test-data".to_string());

    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0);

    let ttl = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| (d.as_secs() + 86400) as i64) // 24 hours from now (TTL)
        .unwrap_or(0);

    // Create 5 items with unique IDs
    let mut items = Vec::new();
    let mut expected_data = Vec::new();

    for i in 0..5 {
        let item_id = format!("test-{}-{}", timestamp, i);
        let data = format!("benchmark test data - rust {} - item {}", ARCHITECTURE, i);
        expected_data.push(data.clone());

        let mut item = std::collections::HashMap::new();
        item.insert("pk".to_string(), AttributeValue::S(item_id));
        item.insert("sk".to_string(), AttributeValue::S(WORKLOAD_TYPE.to_string()));
        item.insert("timestamp".to_string(), AttributeValue::N((timestamp + i).to_string()));
        item.insert("ttl".to_string(), AttributeValue::N(ttl.to_string()));
        item.insert("workload".to_string(), AttributeValue::S(WORKLOAD_TYPE.to_string()));
        item.insert("runtime".to_string(), AttributeValue::S("rust".to_string()));
        item.insert("architecture".to_string(), AttributeValue::S(ARCHITECTURE.to_string()));
        item.insert("data".to_string(), AttributeValue::S(data));

        items.push(item);
    }

    // Batch write all items
    use aws_sdk_dynamodb::types::WriteRequest;
    let write_requests: Vec<WriteRequest> = items.iter().map(|item| {
        WriteRequest::builder()
            .put_request(
                aws_sdk_dynamodb::types::PutRequest::builder()
                    .set_item(Some(item.clone()))
                    .build()
                    .unwrap()
            )
            .build()
    }).collect();

    let batch_write_result = client
        .batch_write_item()
        .request_items(&table_name, write_requests)
        .send()
        .await;

    let write_request_id = match batch_write_result {
        Ok(output) => output
            .request_id()
            .unwrap_or("unknown")
            .to_string(),
        Err(e) => {
            return Ok(Response::Error(ErrorResponse {
                success: false,
                workload_type: WORKLOAD_TYPE.to_string(),
                error: format!("DynamoDB batch write failed: {}", e),
            }));
        }
    };

    // Batch read back all items
    use aws_sdk_dynamodb::types::KeysAndAttributes;
    let keys: Vec<std::collections::HashMap<String, AttributeValue>> = (0..5).map(|i| {
        let mut key = std::collections::HashMap::new();
        let item_id = format!("test-{}-{}", timestamp, i);
        key.insert("pk".to_string(), AttributeValue::S(item_id));
        key.insert("sk".to_string(), AttributeValue::S(WORKLOAD_TYPE.to_string()));
        key
    }).collect();

    let keys_and_attrs = KeysAndAttributes::builder()
        .set_keys(Some(keys))
        .build()
        .map_err(|e| format!("Failed to build KeysAndAttributes: {}", e))?;

    let batch_get_result = client
        .batch_get_item()
        .request_items(&table_name, keys_and_attrs)
        .send()
        .await;

    let retrieved_items = match batch_get_result {
        Ok(output) => {
            let request_id = output
                .request_id()
                .unwrap_or("unknown")
                .to_string();

            let items = output.responses()
                .and_then(|r| r.get(&table_name))
                .map(|items| items.to_vec())
                .unwrap_or_default();

            if items.len() != 5 {
                return Ok(Response::Error(ErrorResponse {
                    success: false,
                    workload_type: WORKLOAD_TYPE.to_string(),
                    error: format!("Expected 5 items, got {}", items.len()),
                }));
            }

            (request_id, items)
        }
        Err(e) => {
            return Ok(Response::Error(ErrorResponse {
                success: false,
                workload_type: WORKLOAD_TYPE.to_string(),
                error: format!("DynamoDB batch read failed: {}", e),
            }));
        }
    };

    let (read_request_id, items) = retrieved_items;

    // Match items by ID (batch_get_item doesn't guarantee order)
    let mut items_by_id = std::collections::HashMap::new();
    for item in &items {
        let item_id = item
            .get("pk")
            .and_then(|v| v.as_s().ok())
            .map(|s| s.to_string())
            .unwrap_or_default();
        let retrieved_data = item
            .get("data")
            .and_then(|v| v.as_s().ok())
            .map(|s| s.to_string())
            .unwrap_or_default();
        items_by_id.insert(item_id, retrieved_data);
    }

    // Verify all data matches by item ID
    let mut all_data_matches = true;
    for i in 0..5 {
        let item_id = format!("test-{}-{}", timestamp, i);
        if let Some(retrieved_data) = items_by_id.get(&item_id) {
            if retrieved_data != &expected_data[i] {
                all_data_matches = false;
                break;
            }
        } else {
            all_data_matches = false;
            break;
        }
    }

    let memory_limit_mb: u32 = env::var("AWS_LAMBDA_FUNCTION_MEMORY_SIZE")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);

    Ok(Response::Success(SuccessResponse {
        success: true,
        workload_type: WORKLOAD_TYPE.to_string(),
        architecture: ARCHITECTURE.to_string(),
        memory_limit_mb,
        items_written: 5,
        items_read: items.len(),
        write_request_id,
        read_request_id,
        all_data_matches,
    }))
}

#[tokio::main]
async fn main() -> Result<(), Error> {
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::INFO)
        .with_target(false)
        .without_time()
        .init();

    // Initialize AWS SDK client once during init
    let config = aws_config::load_defaults(BehaviorVersion::latest()).await;
    let client = Client::new(&config);
    let shared_client = &client;

    run(service_fn(move |event: LambdaEvent<Request>| async move {
        function_handler(shared_client, event).await
    }))
    .await
}
