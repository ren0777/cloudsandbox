#!/bin/bash
# Reference fix (PRIVATE: labtest/CI only): restore the subscription, then prove fan-out.
set -euo pipefail
QUEUE_ARN=$(aws sqs get-queue-attributes \
  --queue-url "$(aws sqs get-queue-url --queue-name "$QUEUE_NAME" --query QueueUrl --output text)" \
  --attribute-names QueueArn --query "Attributes.QueueArn" --output text)
TOPIC_ARN=$(aws sns create-topic --name "$TOPIC_NAME" --query "TopicArn" --output text)
aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol sqs --notification-endpoint "$QUEUE_ARN"
aws sns publish --topic-arn "$TOPIC_ARN" --message '{"alert": "latte order is waiting"}'
