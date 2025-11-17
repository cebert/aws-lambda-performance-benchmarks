import { CfnOutput, RemovalPolicy } from "aws-cdk-lib";
import { Construct } from "constructs";

import {
  AttributeType,
  BillingMode,
  ProjectionType,
  StreamViewType,
  Table,
} from 'aws-cdk-lib/aws-dynamodb';

export interface ResultsTableProps {
  /**
   * Name of the DynamoDB table
   * @default 'BenchmarkResults'
   */
  readonly tableName?: string;

  /**
   * Whether to enable DynamoDB Streams
   * @default false
   */
  readonly enableStreams?: boolean;
}

/**
 * Construct for DynamoDB Table that stores Benchmark Results
 *
 * Stores test execution results with:
 * - Result items (raw invocation data)
 * - Aggregate items (pre-calculated statistics)
 * - Test Run items (execution metadata)
 *
 * For complete schema documentation, see: docs/dynamodb-schema.md
 *
 * GSI1 (ConfigIndex): Query all runs of a specific configuration
 * GSI2 (TestRunIndex): Query all items for a specific test run
 */
export class ResultsTable extends Construct {
  public readonly table: Table;

  constructor(scope: Construct, id: string, props?: ResultsTableProps) {
    super(scope, id);

    this.table = new Table(this, 'Table', {
      tableName: props?.tableName ?? 'BenchmarkResults',
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
      stream: props?.enableStreams ? StreamViewType.NEW_AND_OLD_IMAGES : undefined,
      removalPolicy: RemovalPolicy.DESTROY // Test data - can be deleted
    });

    // GSI1: Query by configuration across all test runs (trend analysis)
    // Projects only essential metrics to reduce storage costs (~70% reduction)
    this.table.addGlobalSecondaryIndex({
      indexName: 'ConfigIndex',
      partitionKey: {
        name: 'configId',
        type: AttributeType.STRING
      },
      sortKey: {
        name: 'timestamp',
        type: AttributeType.NUMBER
      },
      projectionType: ProjectionType.INCLUDE,
      nonKeyAttributes: [
        'billedDurationMs',
        'durationMs',
        'initDurationMs',
        'invocationNumber',
        'invocationType',
        'maxMemoryUsedMB',
        'memorySizeMB',
        'testRunId'
      ]
    });

    // GSI2: Query all results from a specific test run (primary visualization use case)
    // Essential for "show me all 11,400 samples from test run X"
    this.table.addGlobalSecondaryIndex({
      indexName: 'TestRunIndex',
      partitionKey: {
        name: 'testRunId',
        type: AttributeType.STRING
      },
      sortKey: {
        name: 'timestamp',
        type: AttributeType.NUMBER
      },
      projectionType: ProjectionType.INCLUDE,
      nonKeyAttributes: [
        'architecture',
        'billedDurationMs',
        'configId',
        'durationMs',
        'initDurationMs',
        'invocationNumber',
        'invocationType',
        'maxMemoryUsedMB',
        'memorySizeMB',
        'runtime',
        'workloadType'
      ]
    });

    new CfnOutput(this, 'TableName', {
      value: this.table.tableName,
      description: 'DynamoDB table name for benchmark results',
      exportName: 'BenchmarkResultsTableName'
    });

    new CfnOutput(this, 'TableArn', {
      value: this.table.tableArn,
      description: 'DynamoDB table ARN',
      exportName: 'BenchmarkResultsTableArn'
    });
  }
}
