#!/bin/bash
# Partial solution (PRIVATE): bucket + versioning, and an index.html with the WRONG content type
# (exercises the hidden check). Expected score is in expected.yaml.
set -euo pipefail
aws s3 mb "s3://$BUCKET"
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
echo 'plain text' > /tmp/index.html
aws s3 cp /tmp/index.html "s3://$BUCKET/index.html" --content-type text/plain
