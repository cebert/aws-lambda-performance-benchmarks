import { Duration, RemovalPolicy } from "aws-cdk-lib";
import { Table } from "aws-cdk-lib/aws-dynamodb";
import { Code, Function as LambdaFunction } from "aws-cdk-lib/aws-lambda";
import { LogGroup, RetentionDays } from "aws-cdk-lib/aws-logs";
import { RustFunction } from "cargo-lambda-cdk";
import { Construct } from "constructs";
import { LambdaFunctionConfig } from "../config/lambda-config";

export interface BenchmarkFunctionProps {
  /**
   * Function configuration
   */
  readonly config: LambdaFunctionConfig;

  /**
   * DynamoDB table for light workload test data (with TTL for auto-cleanup)
   * Only used by light workload functions
   */
  readonly testDataTable?: Table;
}

/**
 * Benchmark Lambda Function Construct
 *
 * Creates a Lambda function configured for benchmark testing with:
 * - Minimal cold start overhead
 * - Proper IAM permissions (DynamoDB read/write for light workload only)
 * - CloudWatch Logs with 3-day retention and auto-deletion
 * - Orchestrator discovers functions via CloudFormation list-stack-resources
 */
export class BenchmarkFunction extends Construct {
  public readonly function: LambdaFunction;

  constructor(scope: Construct, id: string, props: BenchmarkFunctionProps) {
    super(scope, id);

    const { config, testDataTable } = props;

    const isPython = config.runtime.id.startsWith('python');
    const isRust = config.runtime.id === 'rust';
    const isLightWorkload = config.workload.type === 'light';
    const dynamoTable = isLightWorkload ? testDataTable : undefined;

    const logGroup = new LogGroup(this, 'LogGroup', {
      logGroupName: `/aws/lambda/${config.functionName}`,
      retention: RetentionDays.THREE_DAYS,
      removalPolicy: RemovalPolicy.DESTROY
    });

    if (isRust) {
      // Use RustFunction construct for Rust runtime
      // cargo-lambda-cdk handles compilation and bundling automatically
      this.function = new RustFunction(this, 'Function', {
        functionName: config.functionName,
        manifestPath: `${config.codePath}/${config.workload.handlerDir}`,
        architecture: config.architecture.architecture,
        memorySize: config.initialMemoryMB,
        timeout: Duration.seconds(config.timeoutSeconds),
        logGroup,
        environment: dynamoTable
          ? { DYNAMODB_TABLE_NAME: dynamoTable.tableName }
          : undefined,
        description: `${config.workload.description} - ${config.runtime.id} ${config.architecture.id}`,
        bundling: {
          profile: 'release',
        }
      }) as unknown as LambdaFunction;
    } else {
      // Lambda with AWS runtime
      this.function = new LambdaFunction(this, 'Function', {
        functionName: config.functionName,
        runtime: config.runtime.runtime,
        handler: config.runtime.handler,
        code: Code.fromAsset(config.codePath, {
          exclude: [
            '*.test.*',
            'test_*',
            '__pycache__',
            '*.pyc',
            'node_modules',
            'coverage',
            '.pytest_cache',
            'htmlcov',
            ...(isPython ? ['*.ts', 'tsconfig.json'] : [])
          ]
        }),
        architecture: config.architecture.architecture,
        memorySize: config.initialMemoryMB,
        timeout: Duration.seconds(config.timeoutSeconds),
        logGroup,
        environment: dynamoTable
          ? { DYNAMODB_TABLE_NAME: dynamoTable.tableName }
          : undefined,
        description: `${config.workload.description} - ${config.runtime.id} ${config.architecture.id}`
      });
    }

    // The light workload performs write-then-read operation to test full SDK round-trip, so it needs DDB permissions
    if (isLightWorkload && testDataTable) {
      testDataTable.grantReadWriteData(this.function);
    }
  }
}
