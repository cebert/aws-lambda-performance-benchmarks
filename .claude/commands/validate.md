Validate that the Lambda benchmark infrastructure is built and deployed:

1. **Check CDK build**: Verify `cdk/dist/` exists and is up to date
2. **Check AWS credentials**: `aws sts get-caller-identity`
3. **Verify CloudFormation stack**:
   ```bash
   aws cloudformation describe-stacks --stack-name LambdaBenchmarkStack --query 'Stacks[0].StackStatus'
   ```
   (Should be `CREATE_COMPLETE` or `UPDATE_COMPLETE`)

4. **Count Lambda functions**:
   ```bash
   aws lambda list-functions --query 'Functions[?starts_with(FunctionName, `LambdaBenchmark`)].FunctionName' --output table
   ```
   (Should show 30 functions)

5. **Verify DynamoDB tables**:
   ```bash
   aws dynamodb list-tables --query 'TableNames[?contains(@, `Benchmark`)]'
   ```
   (Should show: BenchmarkResults, BenchmarkTestData)

If anything is missing or outdated, offer to:
- Run `npm run build` to build CDK
- Run `npm run deploy` to deploy/update stack
