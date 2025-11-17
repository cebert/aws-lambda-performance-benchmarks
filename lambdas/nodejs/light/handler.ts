import { BatchGetItemCommand, BatchWriteItemCommand, DynamoDBClient } from "@aws-sdk/client-dynamodb";
import type { Context } from "aws-lambda";

const dynamoClient = new DynamoDBClient({});

interface BenchmarkSuccess {
  success: true;
  workloadType: 'light';
  architecture: string;
  memoryLimitMB: number;
  itemsWritten: number;
  itemsRead: number;
  writeRequestId: string;
  readRequestId: string;
  allDataMatches: boolean;
}

interface BenchmarkError {
  success: false;
  workloadType: 'light';
  error: string;
}

type BenchmarkResult = BenchmarkSuccess | BenchmarkError;

/**
 * Lambda handler - Light test performs a DynamoDB batch write (5 items) followed by a batch read to measure
 * baseline Lambda invocation and SDK initialization overhead with realistic
 * multi-item I/O patterns. Returns simple object for direct Lambda invocation.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function handler(_event: any, context: Context): Promise<BenchmarkResult> {
  console.log(
    JSON.stringify({
      event: 'handler_start',
      workloadType: 'light',
      runtime: `nodejs${process.version}`,
      architecture: process.arch,
      requestId: context.awsRequestId
    })
  );

  try {
    const result = await lightWorkload();

    console.log(
      JSON.stringify({
        event: 'handler_success',
        itemsWritten: result.itemsWritten,
        itemsRead: result.itemsRead,
        writeRequestId: result.writeRequestId,
        readRequestId: result.readRequestId,
        allDataMatches: result.allDataMatches
      })
    );

    return {
      success: true,
      workloadType: 'light',
      architecture: process.arch,
      memoryLimitMB: parseInt(context.memoryLimitInMB, 10),
      itemsWritten: result.itemsWritten,
      itemsRead: result.itemsRead,
      writeRequestId: result.writeRequestId,
      readRequestId: result.readRequestId,
      allDataMatches: result.allDataMatches
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
      workloadType: 'light',
      error: error instanceof Error ? error.message : String(error)
    };
  }
}

async function lightWorkload(): Promise<{
  writeRequestId: string;
  readRequestId: string;
  itemsWritten: number;
  itemsRead: number;
  allDataMatches: boolean;
}> {
  const table = process.env.DYNAMODB_TABLE_NAME || 'benchmark-test-data';

  const timestamp = Date.now();
  const arch = process.arch;
  const nodeVersion = process.version;
  const ttlTimestamp = Math.floor(Date.now() / 1000) + 86400; // 24 hours from now

  const items = [];
  for (let i = 0; i < 5; i++) {
    const itemId = `test-${timestamp}-${i}`;
    const data = `benchmark test data - nodejs${nodeVersion} ${arch} - item ${i}`;
    items.push({
      itemId,
      data,
      item: {
        pk: { S: itemId },
        sk: { S: 'light' },
        timestamp: { N: (timestamp + i).toString() },
        ttl: { N: ttlTimestamp.toString() },
        workload: { S: 'light' },
        runtime: { S: `nodejs${nodeVersion}` },
        architecture: { S: arch },
        data: { S: data }
      }
    });
  }

  const batchWriteCommand = new BatchWriteItemCommand({
    RequestItems: {
      [table]: items.map(item => ({
        PutRequest: {
          Item: item.item
        }
      }))
    }
  });

  const writeResponse = await dynamoClient.send(batchWriteCommand);

  const batchGetCommand = new BatchGetItemCommand({
    RequestItems: {
      [table]: {
        Keys: items.map(item => ({
          pk: { S: item.itemId },
          sk: { S: 'light' }
        }))
      }
    }
  });

  const readResponse = await dynamoClient.send(batchGetCommand);

  if (!readResponse.Responses || !readResponse.Responses[table]) {
    throw new Error(`No responses from table: ${table}`);
  }

  const retrievedItems = readResponse.Responses[table];
  if (retrievedItems.length !== items.length) {
    throw new Error(`Expected ${items.length} items, got ${retrievedItems.length}`);
  }

  const itemsById = new Map<string, string>();
  for (const retrievedItem of retrievedItems) {
    const itemId = retrievedItem.pk?.S || '';
    const data = retrievedItem.data?.S || '';
    itemsById.set(itemId, data);
  }

  const allDataMatches = items.every(item => {
    const retrievedData = itemsById.get(item.itemId);
    return retrievedData === item.data;
  });

  return {
    writeRequestId: writeResponse.$metadata.requestId || 'unknown',
    readRequestId: readResponse.$metadata.requestId || 'unknown',
    itemsWritten: items.length,
    itemsRead: retrievedItems.length,
    allDataMatches
  };
}