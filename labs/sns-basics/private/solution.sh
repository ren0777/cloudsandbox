#!/bin/bash
# Reference solution (PRIVATE: labtest/CI only). Variables are exported in upper case.
set -euo pipefail
URL=$(aws sqs create-queue --queue-name "$QUEUE_NAME" \
  --attributes "MessageRetentionPeriod=3600" --query "QueueUrl" --output text)
QUEUE_ARN=$(aws sqs get-queue-attributes --queue-url "$URL" --attribute-names QueueArn \
  --query "Attributes.QueueArn" --output text)
TOPIC_ARN=$(aws sns create-topic --name "$TOPIC_NAME" --query "TopicArn" --output text)
aws sns set-topic-attributes --topic-arn "$TOPIC_ARN" --attribute-name DisplayName \
  --attribute-value "CloudCafé alerts"
aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol sqs --notification-endpoint "$QUEUE_ARN"
aws sns publish --topic-arn "$TOPIC_ARN" --message '{"alert": "latte order waiting at the counter"}'
