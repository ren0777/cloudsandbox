#!/bin/bash
# Reference solution (PRIVATE: labtest/CI only). $FUNCTION is provided by labtest.
set -euo pipefail
cd "$(mktemp -d)"
cat > lambda_function.py <<'PY'
import os


def lambda_handler(event, context):
    rate = float(os.environ["TAX_RATE"])
    subtotal = sum(i["price"] * i["qty"] for i in event.get("items", []))
    return {"total": round(subtotal * (1 + rate), 2)}
PY
zip -q fn.zip lambda_function.py
ROLE=$(aws iam create-role --role-name "$FUNCTION-role" --query Role.Arn --output text \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}')
aws lambda create-function --function-name "$FUNCTION" --runtime python3.12 --role "$ROLE" \
  --handler lambda_function.lambda_handler --zip-file fileb://fn.zip \
  --timeout 10 --memory-size 256 --environment 'Variables={TAX_RATE=0.08}' >/dev/null
