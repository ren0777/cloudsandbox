#!/bin/bash
# Reference solution (PRIVATE). $GROUP $USER $POLICY $BUCKET provided by labtest.
set -euo pipefail
aws iam create-group --group-name "$GROUP" >/dev/null
aws iam create-user --user-name "$USER" >/dev/null
aws iam add-user-to-group --group-name "$GROUP" --user-name "$USER"
ARN=$(aws iam create-policy --policy-name "$POLICY" --query Policy.Arn --output text --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"s3:GetObject\",\"Resource\":\"arn:aws:s3:::$BUCKET/*\"}]}")
aws iam attach-group-policy --group-name "$GROUP" --policy-arn "$ARN"
