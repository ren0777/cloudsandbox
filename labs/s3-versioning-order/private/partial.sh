#!/bin/bash
# Partial (PRIVATE): the classic mistake. Same end state as the solution, but the ledger was uploaded BEFORE
# versioning was enabled, so its version ID is null. Only the audit log can tell: every end-state check passes.
set -euo pipefail
aws s3 mb "s3://$BUCKET"
echo 'date,total' > /tmp/ledger.csv
aws s3 cp /tmp/ledger.csv "s3://$BUCKET/ledger.csv"
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
