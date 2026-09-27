#!/bin/bash
# Reference solution (PRIVATE: labtest/CI only). Variables are exported in upper case.
set -euo pipefail
VPC=$(aws ec2 create-vpc --cidr-block "$VPC_CIDR" --query "Vpc.VpcId" --output text)
aws ec2 create-tags --resources "$VPC" --tags "Key=Name,Value=$VPC_NAME"
SUBNET=$(aws ec2 create-subnet --vpc-id "$VPC" --cidr-block "$SUBNET_CIDR" --availability-zone us-east-1a \
  --query "Subnet.SubnetId" --output text)
aws ec2 create-tags --resources "$SUBNET" --tags "Key=Name,Value=$SUBNET_NAME"
aws ec2 modify-subnet-attribute --subnet-id "$SUBNET" --map-public-ip-on-launch
IGW=$(aws ec2 create-internet-gateway --query "InternetGateway.InternetGatewayId" --output text)
aws ec2 create-tags --resources "$IGW" --tags "Key=Name,Value=$IGW_NAME"
aws ec2 attach-internet-gateway --internet-gateway-id "$IGW" --vpc-id "$VPC"
RTB=$(aws ec2 create-route-table --vpc-id "$VPC" --query "RouteTable.RouteTableId" --output text)
aws ec2 create-tags --resources "$RTB" --tags "Key=Name,Value=$ROUTE_TABLE_NAME"
aws ec2 create-route --route-table-id "$RTB" --destination-cidr-block 0.0.0.0/0 --gateway-id "$IGW"
aws ec2 associate-route-table --route-table-id "$RTB" --subnet-id "$SUBNET"
SG=$(aws ec2 create-security-group --group-name "$SG_NAME" --description "CloudCafe web" --vpc-id "$VPC" \
  --query "GroupId" --output text)
aws ec2 create-tags --resources "$SG" --tags "Key=Name,Value=$SG_NAME"
aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port 80 --cidr 0.0.0.0/0
