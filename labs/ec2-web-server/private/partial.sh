#!/bin/bash
# Partial (PRIVATE): SSH open to the world, wrong instance type, and an extra running instance.
set -euo pipefail
AMI=$(aws ec2 describe-images --owners amazon --query "Images[0].ImageId" --output text)
SG_ID=$(aws ec2 create-security-group --group-name "$SG" --description "CloudCafe web" --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 80 --cidr 0.0.0.0/0 >/dev/null
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 22 --cidr 0.0.0.0/0 >/dev/null
aws ec2 create-key-pair --key-name "$KEY" --query KeyName --output text >/dev/null
aws ec2 run-instances --image-id "$AMI" --instance-type t2.micro --key-name "$KEY" --security-group-ids "$SG_ID" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE},{Key=Project,Value=cloudcafe}]" >/dev/null
aws ec2 run-instances --image-id "$AMI" --instance-type t2.micro --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=test-box}]" >/dev/null
