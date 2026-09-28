#!/bin/bash
# Partial solution (PRIVATE): the queue exists with the default 4-day retention and no order.
# Expected score is in expected.yaml.
set -euo pipefail
aws sqs create-queue --queue-name "$QUEUE_NAME" --query "QueueUrl" --output text
