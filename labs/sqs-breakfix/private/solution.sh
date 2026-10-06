#!/bin/bash
# Reference fix (PRIVATE: labtest/CI only): put the two settings back.
set -euo pipefail
URL=$(aws sqs get-queue-url --queue-name "$QUEUE_NAME" --query "QueueUrl" --output text)
aws sqs set-queue-attributes --queue-url "$URL" --attributes VisibilityTimeout=30,DelaySeconds=0
