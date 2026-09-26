#!/bin/bash
# Partial solution (PRIVATE): function created and configured, but still the "Hello from Lambda" code
# and default memory -> create-function 25 + configure 20 = 45.
set -euo pipefail
cd "$(mktemp -d)"
cat > lambda_function.py <<'PY'
import json


def lambda_handler(event, context):
    return {"statusCode": 200, "body": json.dumps("Hello from Lambda!")}
PY
zip -q fn.zip lambda_function.py
ROLE=$(aws iam create-role --role-name "$FUNCTION-role" --query Role.Arn --output text \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}')
aws lambda create-function --function-name "$FUNCTION" --runtime python3.12 --role "$ROLE" \
  --handler lambda_function.lambda_handler --zip-file fileb://fn.zip \
  --timeout 10 --environment 'Variables={TAX_RATE=0.08}' >/dev/null
