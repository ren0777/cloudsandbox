#!/bin/bash
# Reference solution (PRIVATE: labtest/CI only). $BUCKET is provided by labtest. Runs through the audit proxy.
set -euo pipefail
aws s3 mb "s3://$BUCKET"
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
echo 'date,total' > /tmp/ledger.csv
aws s3 cp /tmp/ledger.csv "s3://$BUCKET/ledger.csv"
