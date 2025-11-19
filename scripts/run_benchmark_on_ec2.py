#!/usr/bin/env python3
"""
EC2 Benchmark Runner

Launches an EC2 instance to run long-duration benchmarks without SSO token expiration issues.
Recommended for Balanced and Production mode benchmarks that run 6-24 hours.

Features:
- Creates temporary EC2 instance with IAM instance profile (no credential expiration)
- Installs dependencies and runs benchmark
- Auto-terminates instance after completion
- Optional S3 upload for results
- Uses t4g.micro (ARM Graviton) for cost efficiency (~$0.20/day)

Prerequisites:
- LambdaBenchmarkStack must be deployed in the target region
- Repository must be public OR EC2 instance must have git credentials configured
- IAM permissions to create EC2 instances, IAM roles, and security groups

Usage:
    python scripts/run_benchmark_on_ec2.py --mode balanced
    python scripts/run_benchmark_on_ec2.py --mode production --keep-alive
    python scripts/run_benchmark_on_ec2.py --mode test --s3-bucket my-results-bucket
"""

import argparse
import base64
import json
import logging
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, WaiterError

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# Configuration
INSTANCE_TYPE = "t4g.micro"  # ARM Graviton, ~$0.0084/hour
AMI_OWNER = "amazon"  # Amazon Linux 2023
AMI_NAME_FILTER = "al2023-ami-2023.*-arm64"  # Latest AL2023 ARM64
SECURITY_GROUP_NAME = "lambda-benchmark-runner"
IAM_ROLE_NAME = "LambdaBenchmarkRunnerRole"
IAM_POLICY_NAME = "LambdaBenchmarkRunnerPolicy"
INSTANCE_NAME_TAG = "LambdaBenchmarkRunner"


def get_latest_al2023_ami(ec2_client) -> str:
    """Get the latest Amazon Linux 2023 ARM64 AMI ID."""
    log.info("Finding latest Amazon Linux 2023 ARM64 AMI...")

    response = ec2_client.describe_images(
        Owners=[AMI_OWNER],
        Filters=[
            {"Name": "name", "Values": [AMI_NAME_FILTER]},
            {"Name": "state", "Values": ["available"]},
            {"Name": "architecture", "Values": ["arm64"]},
        ],
    )

    if not response["Images"]:
        log.error("No Amazon Linux 2023 ARM64 AMI found")
        sys.exit(1)

    # Sort by creation date and get the latest
    latest_ami = sorted(response["Images"], key=lambda x: x["CreationDate"], reverse=True)[0]
    ami_id = latest_ami["ImageId"]
    log.info(f"Using AMI: {ami_id} ({latest_ami['Name']})")

    return ami_id


def create_iam_role(iam_client, region: str, account_id: str) -> str:
    """Create IAM role with instance profile for EC2 benchmark runner."""
    log.info(f"Creating IAM role: {IAM_ROLE_NAME}")

    # Trust policy for EC2
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "ec2.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }

    # IAM policy with required permissions
    policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "lambda:InvokeFunction",
                    "lambda:GetFunction",
                    "lambda:UpdateFunctionConfiguration",
                    "lambda:GetFunctionConfiguration",
                ],
                "Resource": f"arn:aws:lambda:{region}:{account_id}:function:*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "dynamodb:PutItem",
                    "dynamodb:GetItem",
                    "dynamodb:Query",
                    "dynamodb:BatchWriteItem",
                    "dynamodb:UpdateItem",
                ],
                "Resource": f"arn:aws:dynamodb:{region}:{account_id}:table/Benchmark*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "cloudformation:DescribeStacks",
                    "cloudformation:ListStackResources",
                ],
                "Resource": f"arn:aws:cloudformation:{region}:{account_id}:stack/LambdaBenchmarkStack/*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                "Resource": f"arn:aws:logs:{region}:{account_id}:log-group:/aws/ec2/benchmark-runner:*",
            },
            {
                "Effect": "Allow",
                "Action": [
                    "s3:PutObject",
                    "s3:PutObjectAcl",
                ],
                "Resource": "arn:aws:s3:::lambda-benchmark-results-*/*",
            },
        ],
    }

    try:
        # Create role
        try:
            iam_client.create_role(
                RoleName=IAM_ROLE_NAME,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description="Role for EC2 instance running Lambda benchmarks",
            )
            log.info(f"Created IAM role: {IAM_ROLE_NAME}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "EntityAlreadyExists":
                log.info(f"IAM role {IAM_ROLE_NAME} already exists")
            else:
                raise

        # Create and attach inline policy
        try:
            iam_client.put_role_policy(
                RoleName=IAM_ROLE_NAME,
                PolicyName=IAM_POLICY_NAME,
                PolicyDocument=json.dumps(policy_document),
            )
            log.info(f"Attached inline policy: {IAM_POLICY_NAME}")
        except ClientError as e:
            if e.response["Error"]["Code"] != "EntityAlreadyExists":
                raise

        # Create instance profile
        try:
            iam_client.create_instance_profile(InstanceProfileName=IAM_ROLE_NAME)
            log.info(f"Created instance profile: {IAM_ROLE_NAME}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "EntityAlreadyExists":
                log.info(f"Instance profile {IAM_ROLE_NAME} already exists")
            else:
                raise

        # Add role to instance profile
        try:
            iam_client.add_role_to_instance_profile(
                InstanceProfileName=IAM_ROLE_NAME, RoleName=IAM_ROLE_NAME
            )
            log.info(f"Added role to instance profile")
        except ClientError as e:
            if e.response["Error"]["Code"] != "LimitExceeded":
                raise

        # Wait for instance profile to be ready
        log.info("Waiting for instance profile to propagate...")
        time.sleep(10)

        return IAM_ROLE_NAME

    except ClientError as e:
        log.error(f"Failed to create IAM role: {e}")
        sys.exit(1)


def create_security_group(ec2_client, vpc_id: str) -> str:
    """Create security group for benchmark runner (egress-only)."""
    log.info(f"Creating security group: {SECURITY_GROUP_NAME}")

    try:
        response = ec2_client.create_security_group(
            GroupName=SECURITY_GROUP_NAME,
            Description="Security group for Lambda benchmark runner (egress only)",
            VpcId=vpc_id,
        )
        sg_id = response["GroupId"]
        log.info(f"Created security group: {sg_id}")

        # Add tags
        ec2_client.create_tags(
            Resources=[sg_id],
            Tags=[{"Key": "Name", "Value": SECURITY_GROUP_NAME}],
        )

        return sg_id

    except ClientError as e:
        if e.response["Error"]["Code"] == "InvalidGroup.Duplicate":
            log.info(f"Security group {SECURITY_GROUP_NAME} already exists")
            # Get existing security group ID
            response = ec2_client.describe_security_groups(
                Filters=[
                    {"Name": "group-name", "Values": [SECURITY_GROUP_NAME]},
                    {"Name": "vpc-id", "Values": [vpc_id]},
                ]
            )
            return response["SecurityGroups"][0]["GroupId"]
        else:
            log.error(f"Failed to create security group: {e}")
            sys.exit(1)


def get_user_data_script(mode: str, s3_bucket: str | None, region: str, keep_alive: bool) -> str:
    """Generate user data script for EC2 instance."""

    # Determine shutdown behavior
    shutdown_cmd = "" if keep_alive else "sudo shutdown -h now"

    # S3 upload command (optional)
    s3_upload = ""
    if s3_bucket:
        s3_upload = f"""
    # Upload results to S3
    echo "Uploading results to S3..."
    TIMESTAMP=$(date +%Y%m%d-%H%M%S)
    aws s3 cp /tmp/benchmark-results.log s3://{s3_bucket}/benchmark-results-${{TIMESTAMP}}.log || true
"""

    user_data = f"""#!/bin/bash
set -e

# Configure logging
exec > >(tee /var/log/benchmark-setup.log)
exec 2>&1

echo "Starting Lambda benchmark runner setup..."

# Update system
dnf update -y

# Install dependencies (Git, Python, Node.js)
dnf install -y git python3.11 python3.11-pip nodejs npm

# Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="/root/.local/bin:$PATH"

# Clone repository
cd /root
echo "Cloning repository..."
# Note: Using HTTPS clone to avoid SSH key issues
git clone https://github.com/cebert/aws-lambda-performance-benchmarks.git
cd aws-lambda-performance-benchmarks

# Install Python dependencies
echo "Installing Python dependencies..."
/root/.local/bin/uv sync --all-extras

# Set region (both variables for maximum compatibility)
export AWS_REGION={region}
export AWS_DEFAULT_REGION={region}
echo "AWS Region configured: {region}"

# Run benchmark
echo "Starting benchmark in {mode} mode..."
/root/.local/bin/uv run python scripts/benchmark_orchestrator.py --{mode} --yes 2>&1 | tee /tmp/benchmark-results.log

# Check exit status
if [ ${{PIPESTATUS[0]}} -eq 0 ]; then
    echo "Benchmark completed successfully!"
else
    echo "Benchmark failed with exit code ${{PIPESTATUS[0]}}"
fi
{s3_upload}
# Cleanup and shutdown
echo "Benchmark runner finished. Logs available in CloudWatch and /var/log/benchmark-setup.log"
{shutdown_cmd}
"""

    return base64.b64encode(user_data.encode()).decode()


def launch_instance(
    ec2_client,
    iam_client,
    ami_id: str,
    instance_profile_name: str,
    security_group_id: str,
    mode: str,
    s3_bucket: str | None,
    region: str,
    keep_alive: bool,
) -> str:
    """Launch EC2 instance with benchmark runner."""

    log.info(f"Launching {INSTANCE_TYPE} instance...")

    user_data = get_user_data_script(mode, s3_bucket, region, keep_alive)

    try:
        response = ec2_client.run_instances(
            ImageId=ami_id,
            InstanceType=INSTANCE_TYPE,
            MinCount=1,
            MaxCount=1,
            IamInstanceProfile={"Name": instance_profile_name},
            SecurityGroupIds=[security_group_id],
            UserData=user_data,
            TagSpecifications=[
                {
                    "ResourceType": "instance",
                    "Tags": [
                        {"Key": "Name", "Value": INSTANCE_NAME_TAG},
                        {"Key": "Purpose", "Value": "Lambda Benchmark Runner"},
                        {"Key": "Mode", "Value": mode},
                        {"Key": "AutoTerminate", "Value": str(not keep_alive)},
                    ],
                }
            ],
            # Enable detailed monitoring for better CloudWatch metrics
            Monitoring={"Enabled": False},  # Keep costs low
        )

        instance_id = response["Instances"][0]["InstanceId"]
        log.info(f"Launched instance: {instance_id}")

        return instance_id

    except ClientError as e:
        log.error(f"Failed to launch instance: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Run Lambda benchmarks on EC2 to avoid SSO token expiration"
    )
    parser.add_argument(
        "--mode",
        choices=["test", "balanced", "production"],
        required=True,
        help="Benchmark mode (test: ~10 min, balanced: ~6-8 hrs, production: ~18-24 hrs)",
    )
    parser.add_argument(
        "--s3-bucket",
        help="Optional S3 bucket to upload results log to",
    )
    parser.add_argument(
        "--region",
        default="us-east-2",
        help="AWS region (default: us-east-2)",
    )
    parser.add_argument(
        "--keep-alive",
        action="store_true",
        help="Keep instance running after benchmark completes (for debugging)",
    )

    args = parser.parse_args()

    # Initialize AWS clients
    session = boto3.Session(region_name=args.region)
    ec2_client = session.client("ec2")
    iam_client = session.client("iam")
    sts_client = session.client("sts")

    # Get account ID
    account_id = sts_client.get_caller_identity()["Account"]
    log.info(f"AWS Account: {account_id}, Region: {args.region}")

    # Get default VPC
    vpcs = ec2_client.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])
    if not vpcs["Vpcs"]:
        log.error("No default VPC found. Please create one or specify a VPC ID.")
        sys.exit(1)
    vpc_id = vpcs["Vpcs"][0]["VpcId"]
    log.info(f"Using VPC: {vpc_id}")

    # Setup infrastructure
    ami_id = get_latest_al2023_ami(ec2_client)
    instance_profile_name = create_iam_role(iam_client, args.region, account_id)
    security_group_id = create_security_group(ec2_client, vpc_id)

    # Launch instance
    instance_id = launch_instance(
        ec2_client,
        iam_client,
        ami_id,
        instance_profile_name,
        security_group_id,
        args.mode,
        args.s3_bucket,
        args.region,
        args.keep_alive,
    )

    # Wait for instance to be running
    log.info("Waiting for instance to start...")
    try:
        waiter = ec2_client.get_waiter("instance_running")
        waiter.wait(InstanceIds=[instance_id])
        log.info("Instance is running!")
    except WaiterError as e:
        log.error(f"Instance failed to start: {e}")
        sys.exit(1)

    # Get instance details
    response = ec2_client.describe_instances(InstanceIds=[instance_id])
    instance = response["Reservations"][0]["Instances"][0]

    print("\n" + "="*80)
    print("EC2 BENCHMARK RUNNER LAUNCHED SUCCESSFULLY")
    print("="*80)
    print(f"Instance ID:     {instance_id}")
    print(f"Instance Type:   {INSTANCE_TYPE}")
    print(f"Mode:            {args.mode}")
    print(f"Region:          {args.region}")
    print(f"Private IP:      {instance.get('PrivateIpAddress', 'N/A')}")
    print(f"Auto-terminate:  {not args.keep_alive}")
    print("\n" + "-"*80)
    print("MONITORING:")
    print("-"*80)
    print(f"View logs:       aws logs tail /var/log/cloud-init-output.log --follow")
    print(f"SSH (if needed): aws ssm start-session --target {instance_id}")
    print(f"Status:          aws ec2 describe-instance-status --instance-ids {instance_id}")
    print("\n" + "-"*80)
    print("ESTIMATED DURATION:")
    print("-"*80)
    if args.mode == "test":
        print("  ~10 minutes")
    elif args.mode == "balanced":
        print("  ~6-8 hours")
    else:  # production
        print("  ~18-24 hours")

    if not args.keep_alive:
        print("\nInstance will auto-terminate when complete.")
    else:
        print("\nWARNING: Instance will remain running. Terminate manually when done:")
        print(f"  aws ec2 terminate-instances --instance-ids {instance_id}")

    print("="*80 + "\n")


if __name__ == "__main__":
    main()
