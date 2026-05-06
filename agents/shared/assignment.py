"""Assignment lifecycle management.

Called by agents to mark assignments as completed or failed in the
dispatch assignments table. This closes the loop that the Dispatch
Router opens when it creates an assignment.
"""

import logging
import os
import time
from decimal import Decimal

import boto3

logger = logging.getLogger(__name__)

_dynamodb = None
_table = None


def _get_table():
    global _dynamodb, _table
    if _table is None:
        _dynamodb = boto3.resource("dynamodb")
        table_name = os.environ.get("ASSIGNMENTS_TABLE", "dispatch-assignments-dev")
        _table = _dynamodb.Table(table_name)
    return _table


def complete_assignment(assignment_id: str, result_summary: str = ""):
    """Mark an assignment as completed. Raises on DynamoDB failure."""
    if not assignment_id or assignment_id == "default":
        logger.info("Skipping assignment update (no real assignment_id: %r)", assignment_id)
        return

    table = _get_table()
    now = int(time.time())
    update_expr = "SET #s = :s, completed_at = :ca"
    attr_names = {"#s": "status"}
    attr_values = {
        ":s": "completed",
        ":ca": now,
    }
    if result_summary:
        update_expr += ", result_summary = :rs"
        attr_values[":rs"] = result_summary[:1000]

    table.update_item(
        Key={"assignment_id": assignment_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=attr_names,
        ExpressionAttributeValues=attr_values,
    )
    logger.info("Assignment %s marked completed", assignment_id)


def fail_assignment(assignment_id: str, error: str = ""):
    """Mark an assignment as failed. Raises on DynamoDB failure."""
    if not assignment_id or assignment_id == "default":
        logger.info("Skipping fail_assignment (no real assignment_id: %r)", assignment_id)
        return

    table = _get_table()
    now = int(time.time())
    table.update_item(
        Key={"assignment_id": assignment_id},
        UpdateExpression="SET #s = :s, completed_at = :ca, result_summary = :rs",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "failed",
            ":ca": now,
            ":rs": str(error)[:1000],
        },
    )
    logger.info("Assignment %s marked failed", assignment_id)
