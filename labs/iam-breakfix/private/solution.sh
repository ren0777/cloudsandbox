#!/bin/bash
# Reference fix (PRIVATE: labtest/CI only).
set -euo pipefail
ORDERS=$(aws iam list-policies --scope Local --query "Policies[?PolicyName=='$POLICY'].Arn" --output text)
aws iam detach-group-policy --group-name "$GROUP" --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
aws iam attach-group-policy --group-name "$GROUP" --policy-arn "$ORDERS"
aws iam remove-user-from-group --group-name "$GROUP" --user-name "$INTERN"
aws iam delete-user-policy --user-name "$INTERN" --policy-name temp-everything
aws iam delete-user --user-name "$INTERN"
