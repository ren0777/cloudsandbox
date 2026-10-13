#!/bin/bash
# Partial solution (PRIVATE): table, queue and a correct batch-processing function, but no trigger, so the
# queue is never drained into the table. Expected score is in expected.yaml.
set -euo pipefail
cd "$(mktemp -d)"

aws dynamodb create-table --table-name "$TABLE" --billing-mode PAY_PER_REQUEST \
  --attribute-definitions AttributeName=orderId,AttributeType=S \
  --key-schema AttributeName=orderId,KeyType=HASH >/dev/null
aws sqs create-queue --queue-name "$QUEUE" --attributes VisibilityTimeout=60 >/dev/null

cat > lambda_function.py <<'PY'
import json
import os

import boto3

TABLE = os.environ["TABLE_NAME"]
DB = boto3.client("dynamodb")


def save(order):
    subtotal = sum(item["price"] * item["qty"] for item in order.get("items", []))
    total = round(subtotal * 1.08, 2)
    DB.put_item(TableName=TABLE, Item={"orderId": {"S": str(order["orderId"])}, "total": {"N": str(total)}})


def lambda_handler(event, context):
    failures = []
    for record in event.get("Records", []):
        try:
            save(json.loads(record["body"]))
        except Exception:
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
PY
zip -q fn.zip lambda_function.py

ROLE=$(aws iam create-role --role-name "$FUNCTION-role" --query Role.Arn --output text \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}')
aws lambda create-function --function-name "$FUNCTION" --runtime python3.12 --role "$ROLE" \
  --handler lambda_function.lambda_handler --zip-file fileb://fn.zip \
  --timeout 10 --memory-size 256 --environment "Variables={TABLE_NAME=$TABLE}" >/dev/null
