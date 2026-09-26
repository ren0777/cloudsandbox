#!/bin/bash
# Break-fix setup: creates CloudCafé's BROKEN IAM configuration for this student. Runs once in a short-lived
# job container before the lab starts (and again on Reset). Variables arrive in upper case ($GROUP, $BARISTA,
# $INTERN, $POLICY, $TABLE). This file is not secret: it describes the problem, not the fix.
set -euo pipefail
ADMIN=arn:aws:iam::aws:policy/AdministratorAccess

aws iam create-group --group-name "$GROUP" >/dev/null
aws iam attach-group-policy --group-name "$GROUP" --policy-arn "$ADMIN"          # the break: admins

aws iam create-user --user-name "$BARISTA" >/dev/null
aws iam add-user-to-group --group-name "$GROUP" --user-name "$BARISTA"

aws iam create-user --user-name "$INTERN" >/dev/null                              # left last month
aws iam add-user-to-group --group-name "$GROUP" --user-name "$INTERN"
aws iam put-user-policy --user-name "$INTERN" --policy-name temp-everything \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"*","Resource":"*"}]}'

# The correct least-privilege policy exists, but nobody attached it.
DOC='{"Version":"2012-10-17","Statement":[{"Sid":"OrdersReadWrite","Effect":"Allow",'
DOC+='"Action":["dynamodb:GetItem","dynamodb:PutItem","dynamodb:UpdateItem","dynamodb:Query"],'
DOC+="\"Resource\":\"arn:aws:dynamodb:*:*:table/$TABLE\"}]}"
aws iam create-policy --policy-name "$POLICY" --policy-document "$DOC" >/dev/null
echo "broken IAM setup created for $GROUP"
