#!/bin/bash
# Partial fix (PRIVATE): the subscription is back, but no test alert was published.
set -euo pipefail
QUEUE_ARN=$(aws sqs get-queue-attributes \
  --queue-url "$(aws sqs get-queue-url --queue-name "$QUEUE_NAME" --query QueueUrl --output text)" \
  --attribute-names QueueArn --query "Attributes.QueueArn" --output text)
TOPIC_ARN=$(aws sns create-topic --name "$TOPIC_NAME" --query "TopicArn" --output text)
aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol sqs --notification-endpoint "$QUEUE_ARN"
