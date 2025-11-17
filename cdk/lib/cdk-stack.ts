import * as cdk from "aws-cdk-lib";
import { AwsSolutionsChecks, NagSuppressions } from "cdk-nag";
import { Construct } from "constructs";
import { generateLambdaConfigurations, getTotalFunctionsDeployed } from "./config/lambda-config";
import { BenchmarkFunction } from "./constructs/benchmark-function";
import { ResultsTable } from "./constructs/results-table";
import { TestDataTable } from "./constructs/test-data-table";

/**
 * Main stack for Lambda ARM vs x86 benchmark infrastructure
 *
 * Simplified Design:
 * - Deploys base Lambda functions
 * - Self-contained handlers with inlined workload code (zero import overhead)
 * - Single-threaded workloads only for simplicity
 * - Uses UpdateFunctionConfiguration API to change memory dynamically during testing
 *
 * This stack deploys:
 * - Lambda functions (base configurations)
 * - 2 DynamoDB tables:
 *   - BenchmarkResults: Actual test results from orchestrator
 *   - BenchmarkTestData: Disposable data from light workload tests (with TTL)
 * - IAM roles and permissions
 * - CloudWatch log groups
 */
export class CdkStack extends cdk.Stack {
  public readonly resultsTable: ResultsTable;
  public readonly testDataTable: TestDataTable;
  public readonly benchmarkFunctions: BenchmarkFunction[];

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    cdk.Aspects.of(this).add(new AwsSolutionsChecks({ verbose: true }));

    this.resultsTable = new ResultsTable(this, 'ResultsTable', {
      tableName: 'BenchmarkResults',
      enableStreams: false
    });

    this.testDataTable = new TestDataTable(this, 'TestDataTable', {
      tableName: 'BenchmarkTestData'
    });

    const configurations = generateLambdaConfigurations();
    this.benchmarkFunctions = [];

    for (const config of configurations) {
      const benchmarkFunction = new BenchmarkFunction(this, config.functionName, {
        config,
        testDataTable: this.testDataTable.table,
      });
      this.benchmarkFunctions.push(benchmarkFunction);
    }

    this.addNagSuppressions();

    new cdk.CfnOutput(this, 'TotalFunctionsDeployed', {
      value: getTotalFunctionsDeployed().toString(),
      description: 'Total Lambda functions (memory configs managed dynamically by orchestrator)'
    });
  }

  /**
   * Add CDK Nag suppressions for benchmark-specific requirements
   */
  private addNagSuppressions(): void {
    NagSuppressions.addStackSuppressions(this, [
      {
        id: 'AwsSolutions-L1',
        reason: 'Using specific Lambda runtime versions for benchmark comparison'
      },
      {
        id: 'AwsSolutions-IAM4',
        reason: 'Using AWS managed policies for Lambda basic execution role'
      },
      {
        id: 'AwsSolutions-IAM5',
        reason: 'Wildcard permissions required for CloudWatch Logs and DynamoDB table access'
      }
    ]);
    NagSuppressions.addStackSuppressions(this, [
      {
        id: 'AwsSolutions-L2',
        reason: 'VPC not required for benchmark - measuring baseline Lambda performance'
      }
    ]);
    NagSuppressions.addStackSuppressions(this, [
      {
        id: 'AwsSolutions-L3',
        reason: 'DLQ not required for benchmark - all failures logged to CloudWatch'
      }
    ]);
    NagSuppressions.addStackSuppressions(this, [
      {
        id: 'AwsSolutions-L4',
        reason: 'Reserved concurrency not set - testing realistic on-demand performance'
      }
    ]);
  }
}