#!/bin/bash
# Partial solution (PRIVATE): queue + topic with display name, but no subscription and no alert.
# Expected score is in expected.yaml.
set -euo pipefail
aws sqs create-queue --queue-name "$QUEUE_NAME" --query "QueueUrl" --output text >/dev/null
TOPIC_ARN=$(aws sns create-topic --name "$TOPIC_NAME" --query "TopicArn" --output text)
aws sns set-topic-attributes --topic-arn "$TOPIC_ARN" --attribute-name DisplayName \
  --attribute-value "CloudCafé alerts"
