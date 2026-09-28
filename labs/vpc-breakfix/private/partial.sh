#!/bin/bash
# Partial fix (PRIVATE): the route comes back but the website port stays closed.
set -euo pipefail
RTB=$(aws ec2 describe-route-tables --filters "Name=tag:Name,Values=$ROUTE_TABLE_NAME" \
  --query "RouteTables[0].RouteTableId" --output text)
IGW=$(aws ec2 describe-internet-gateways --filters "Name=tag:Name,Values=$IGW_NAME" \
  --query "InternetGateways[0].InternetGatewayId" --output text)
aws ec2 create-route --route-table-id "$RTB" --destination-cidr-block 0.0.0.0/0 --gateway-id "$IGW"
