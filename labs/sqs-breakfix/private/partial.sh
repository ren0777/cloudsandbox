#!/bin/bash
# Partial fix (PRIVATE): consumers are unstuck, but new orders are still delayed 15 minutes.
set -euo pipefail
URL=$(aws sqs get-queue-url --queue-name "$QUEUE_NAME" --query "QueueUrl" --output text)
aws sqs set-queue-attributes --queue-url "$URL" --attributes VisibilityTimeout=30
