#!/bin/bash
# Reference solution (PRIVATE: labtest/CI only). $TABLE is provided by labtest.
set -euo pipefail
aws dynamodb create-table --table-name "$TABLE" \
  --attribute-definitions AttributeName=orderId,AttributeType=S \
  --key-schema AttributeName=orderId,KeyType=HASH --billing-mode PAY_PER_REQUEST >/dev/null
aws dynamodb put-item --table-name "$TABLE" --item '{"orderId":{"S":"1001"},"drink":{"S":"latte"},"quantity":{"N":"2"}}'
aws dynamodb put-item --table-name "$TABLE" --item '{"orderId":{"S":"1002"},"drink":{"S":"mocha"},"quantity":{"N":"1"}}'
aws dynamodb put-item --table-name "$TABLE" --item '{"orderId":{"S":"1003"},"drink":{"S":"tea"},"quantity":{"N":"3"}}'
