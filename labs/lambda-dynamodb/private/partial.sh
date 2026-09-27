#!/bin/bash
# Partial solution (PRIVATE): table + function exist and compute the total, but the function never saves
# the order, so the last task fails. Expected score is in expected.yaml.
set -euo pipefail
cd "$(mktemp -d)"

aws dynamodb create-table --table-name "$TABLE" --billing-mode PAY_PER_REQUEST \
  --attribute-definitions AttributeName=orderId,AttributeType=S \
  --key-schema AttributeName=orderId,KeyType=HASH >/dev/null

cat > lambda_function.py <<'PY'
import os


def lambda_handler(event, context):
    subtotal = sum(item["price"] * item["qty"] for item in event.get("items", []))
    return {"orderId": str(event["orderId"]), "total": round(subtotal * 1.08, 2), "saved": False}
PY
zip -q fn.zip lambda_function.py

ROLE=$(aws iam create-role --role-name "$FUNCTION-role" --query Role.Arn --output text \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}')
aws lambda create-function --function-name "$FUNCTION" --runtime python3.12 --role "$ROLE" \
  --handler lambda_function.lambda_handler --zip-file fileb://fn.zip \
  --timeout 10 --memory-size 256 --environment "Variables={TABLE_NAME=$TABLE}" >/dev/null
