#!/bin/bash
# Partial solution (PRIVATE): VPC + public subnet + attached internet gateway, but no route table
# association and no security group. Expected score is in expected.yaml.
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
