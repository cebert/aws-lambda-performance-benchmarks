# Security Policy

## Project Scope

This is a **benchmark and research project** designed to measure AWS Lambda performance across different architectures and runtimes. It is not intended for production use and does not handle sensitive data beyond AWS credentials needed for deployment and testing.

## Security Considerations

### AWS Credentials

- **Never commit AWS credentials** to this repository
- Use AWS IAM best practices (least privilege, temporary credentials)
- Review `.gitignore` to ensure credentials files are excluded
- Use AWS SSO or IAM roles where possible

### Deployment Security

- This project deploys AWS Lambda functions and DynamoDB tables to **your AWS account**
- Review the infrastructure code in `cdk/` before deploying
- Be aware of AWS costs associated with deployment and benchmarking
- Use a **non-production AWS account** for testing

### Code Execution

- Lambda handlers execute compute-intensive workloads (hashing, sorting, I/O)
- Review handler code in `lambdas/` before deployment
- Functions have minimal IAM permissions (DynamoDB access for Light workload only)

## Known Non-Issues

The following are **not considered security vulnerabilities** for this project:

- **No authentication/authorization:** Benchmark is for research, not production
- **Public DynamoDB access via functions:** Expected behavior for benchmark
- **No data encryption beyond AWS defaults:** Benchmark data is non-sensitive
- **No input validation in some areas:** Controlled benchmark environment

## Reporting a Security Issue

If you discover a security vulnerability (e.g., credentials exposure, malicious code injection), please:

1. **Do NOT** open a public issue
2. Email the maintainer directly or open a **draft security advisory** via GitHub
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

## Supported Versions

This project follows a rolling release model. Only the latest `main` branch is actively maintained.

| Version | Supported          |
| ------- | ------------------ |
| main    | :white_check_mark: |
| older   | :x:                |

## Responsible Disclosure

We appreciate responsible disclosure and will:

- Acknowledge receipt of your report within 48 hours
- Provide a timeline for addressing the issue
- Credit you in the fix (unless you prefer to remain anonymous)

## Disclaimer

This project is provided "as is" for research and educational purposes. Use at your own risk. Always review code before deploying to your AWS account.
