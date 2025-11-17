import { CfnOutput, Duration, RemovalPolicy } from "aws-cdk-lib";
import { AttributeType, BillingMode, Table } from "aws-cdk-lib/aws-dynamodb";
import { Construct } from "constructs";

export interface TestDataTableProps {
  /**
   * Name of the DynamoDB table
   * @default 'BenchmarkTestData'
   */
  readonly tableName?: string;

  /**
   * TTL duration for auto-deleting test data
   * @default 24 hours
   */
  readonly ttlDuration?: Duration;
}

/**
 * Construct for the DynamoDB Table used for Light Workload Test Data storage
 *
 * IMPORTANT: This is SEPARATE from the BenchmarkResults table.
 * - BenchmarkResults: Stores actual benchmark test results (from orchestrator)
 * - TestDataTable: Just test data for put/get testing
 *
 * Schema:
 * - PK: test-${timestamp} (e.g., "test-1730234567890")
 * - SK: "light"
 * - ttl: Unix timestamp (auto-delete after 24 hours)
 * - workload: "light"
 * - data: Test payload
 */
export class TestDataTable extends Construct {
  public readonly table: Table;

  constructor(scope: Construct, id: string, props?: TestDataTableProps) {
    super(scope, id);

    this.table = new Table(this, 'Table', {
      tableName: props?.tableName ?? 'BenchmarkTestData',
      partitionKey: {
        name: 'pk',
        type: AttributeType.STRING
      },
      sortKey: {
        name: 'sk',
        type: AttributeType.STRING
      },
      billingMode: BillingMode.PAY_PER_REQUEST,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: false
      },
      timeToLiveAttribute: 'ttl', // Auto-delete items after TTL expires
      removalPolicy: RemovalPolicy.DESTROY
    });

    // Output table name for Lambda functions
    new CfnOutput(this, 'TableName', {
      value: this.table.tableName,
      description: 'DynamoDB table name for light workload test data',
      exportName: 'BenchmarkTestDataTableName'
    });

    new CfnOutput(this, 'TableArn', {
      value: this.table.tableArn,
      description: 'DynamoDB table ARN for test data',
      exportName: 'BenchmarkTestDataTableArn'
    });
  }
}