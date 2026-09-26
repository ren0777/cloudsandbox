#!/bin/bash
# Partial solution (PRIVATE): provisioned capacity and quantity stored as a String (hidden check fails).
set -euo pipefail
aws dynamodb create-table --table-name "$TABLE" \
  --attribute-definitions AttributeName=orderId,AttributeType=S \
  --key-schema AttributeName=orderId,KeyType=HASH \
  --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 >/dev/null
aws dynamodb put-item --table-name "$TABLE" --item '{"orderId":{"S":"1001"},"drink":{"S":"latte"},"quantity":{"S":"2"}}'
aws dynamodb put-item --table-name "$TABLE" --item '{"orderId":{"S":"1002"},"drink":{"S":"mocha"},"quantity":{"N":"1"}}'
aws dynamodb put-item --table-name "$TABLE" --item '{"orderId":{"S":"1003"},"drink":{"S":"tea"},"quantity":{"N":"3"}}'
