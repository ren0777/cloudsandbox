#!/bin/bash
# Reference solution (PRIVATE: labtest/CI only). Variables are exported in upper case.
set -euo pipefail
URL=$(aws sqs create-queue --queue-name "$QUEUE_NAME" \
  --attributes "MessageRetentionPeriod=3600" --query "QueueUrl" --output text)
aws sqs send-message --queue-url "$URL" --message-body '{"orderId": 1001, "drink": "latte", "quantity": 2}'
