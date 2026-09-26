#!/bin/bash
# Partial fix (PRIVATE): removes admin but forgets to give the baristas their real permissions and leaves the
# intern in place -> remove-admin 30 + least-privilege 15 = 45.
set -euo pipefail
aws iam detach-group-policy --group-name "$GROUP" --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
