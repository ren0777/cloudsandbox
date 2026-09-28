#!/bin/bash
# Reference fix (PRIVATE: labtest/CI only): put the missing route and the HTTP rule back.
set -euo pipefail
RTB=$(aws ec2 describe-route-tables --filters "Name=tag:Name,Values=$ROUTE_TABLE_NAME" \
  --query "RouteTables[0].RouteTableId" --output text)
IGW=$(aws ec2 describe-internet-gateways --filters "Name=tag:Name,Values=$IGW_NAME" \
  --query "InternetGateways[0].InternetGatewayId" --output text)
aws ec2 create-route --route-table-id "$RTB" --destination-cidr-block 0.0.0.0/0 --gateway-id "$IGW"
SG=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$SG_NAME" \
  --query "SecurityGroups[0].GroupId" --output text)
aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port 80 --cidr 0.0.0.0/0
