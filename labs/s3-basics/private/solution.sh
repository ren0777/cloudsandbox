#!/bin/bash
# Reference solution (PRIVATE: labtest/CI only). $BUCKET is provided by labtest.
set -euo pipefail
aws s3 mb "s3://$BUCKET"
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
echo '<h1>CloudCafe menu</h1>' > /tmp/index.html
aws s3 cp /tmp/index.html "s3://$BUCKET/index.html"
aws s3api put-bucket-tagging --bucket "$BUCKET" --tagging 'TagSet=[{Key=project,Value=cloudcafe}]'
