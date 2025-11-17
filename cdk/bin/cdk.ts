import * as cdk from "aws-cdk-lib";
import { CdkStack } from "../lib/cdk-stack";

const app = new cdk.App();

const account = process.env.CDK_DEFAULT_ACCOUNT;
const region = process.env.CDK_DEFAULT_REGION || 'us-east-2';

if (!account) {
  throw new Error(
    'CDK_DEFAULT_ACCOUNT environment variable is required. ' +
      'Run: export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)'
  );
}

new CdkStack(app, 'LambdaBenchmarkStack', {
  description: 'AWS Lambda ARM vs x86 Performance Benchmark Test Deployed by CDK',
  env: {
    account,
    region
  },

  tags: {
    Project: 'LambdaARMvsx86Benchmark',
    Environment: 'benchmark',
    Production: 'false',
    Owner: 'chris.ebert',
    ManagedBy: 'CDK'
  }
});