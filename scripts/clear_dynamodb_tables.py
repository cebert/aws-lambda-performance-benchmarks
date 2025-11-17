#!/usr/bin/env python3
"""
Clear all items from DynamoDB benchmark tables.

This script clears:
- BenchmarkResults (benchmark results, aggregates, test-run metadata)
- BenchmarkTestData (test data for Light workload)
"""

import boto3
from botocore.config import Config

# Configure boto3
boto_config = Config(
    retries={"max_attempts": 10, "mode": "standard"},
)

dynamodb = boto3.resource("dynamodb", config=boto_config)


def clear_table(table_name: str, key_attrs: list[str]) -> None:
    """
    Clear all items from a DynamoDB table.

    Args:
        table_name: Name of the table to clear
        key_attrs: List of key attribute names (e.g., ['pk', 'sk'] or ['itemId'])
    """
    table = dynamodb.Table(table_name)

    print(f"\nClearing table: {table_name}")
    print(f"Key attributes: {key_attrs}")

    response = table.scan(ProjectionExpression=",".join(key_attrs))
    items = response.get("Items", [])

    while "LastEvaluatedKey" in response:
        response = table.scan(
            ProjectionExpression=",".join(key_attrs),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    total_items = len(items)
    print(f"Found {total_items} items to delete")

    if total_items == 0:
        print("Table is already empty")
        return

    deleted = 0
    batch_size = 25

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]

        with table.batch_writer() as writer:
            for item in batch:
                # Extract only the key attributes
                key = {attr: item[attr] for attr in key_attrs}
                writer.delete_item(Key=key)
                deleted += 1

        if deleted % 100 == 0 or deleted == total_items:
            print(f"  Deleted {deleted}/{total_items} items ({100 * deleted / total_items:.1f}%)")

    print(f"✓ Successfully deleted all {total_items} items from {table_name}")


def main() -> None:
    """Clear all benchmark tables."""
    print("=" * 80)
    print("DynamoDB Table Cleanup")
    print("=" * 80)

    # Confirm with user
    print("\nThis will delete ALL data from the following tables:")
    print("  - BenchmarkResults (results, aggregates, test-run metadata)")
    print("  - BenchmarkTestData (test data for Light workload)")
    print("\nThis action cannot be undone!")

    response = input("\nContinue? (yes/no): ")
    if response.lower() != "yes":
        print("Aborted.")
        return

    # Clear tables
    clear_table("BenchmarkResults", ["pk", "sk"])
    clear_table("BenchmarkTestData", ["pk", "sk"])

    print("\n" + "=" * 80)
    print("Cleanup complete! Tables are now empty.")
    print("=" * 80)


if __name__ == "__main__":
    main()
