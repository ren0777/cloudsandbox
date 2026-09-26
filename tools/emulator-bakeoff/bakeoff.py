"""Emulator bake-off: run CloudLabs-relevant operations for S3, IAM, DynamoDB, EC2, Lambda against an
endpoint and report pass/fail per operation. Usage: python bakeoff.py http://emu:4566"""
import io
import json
import sys
import time
import zipfile

import boto3
from botocore.config import Config

EP = sys.argv[1]
kw = dict(endpoint_url=EP, region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test",
          config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 1}, read_timeout=30))
s3, iam, ddb, ec2, lam = (boto3.client(n, **kw) for n in ("s3", "iam", "dynamodb", "ec2", "lambda"))
results = []


def t(name, fn):
    t0 = time.time()
    try:
        out = fn()
        ok = out is not False
        results.append((name, "PASS" if ok else "WRONG", f"{(time.time()-t0)*1000:.0f}ms"))
    except Exception as e:
        results.append((name, "FAIL", str(e)[:90]))


B = "bake-bucket"
# ---- S3 (everything slice 1 uses)
t("s3 CreateBucket", lambda: s3.create_bucket(Bucket=B))
t("s3 PutPublicAccessBlock", lambda: s3.put_public_access_block(Bucket=B, PublicAccessBlockConfiguration={
    "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True}))
t("s3 GetPublicAccessBlock", lambda: s3.get_public_access_block(Bucket=B)["PublicAccessBlockConfiguration"]["BlockPublicAcls"] is True)
t("s3 PutObject+ContentType", lambda: s3.put_object(Bucket=B, Key="index.html", Body=b"<h1>x</h1>", ContentType="text/html"))
t("s3 HeadObject ContentType", lambda: s3.head_object(Bucket=B, Key="index.html")["ContentType"] == "text/html")
t("s3 ListObjectsV2", lambda: [o["Key"] for o in s3.list_objects_v2(Bucket=B)["Contents"]] == ["index.html"])
t("s3 Put/GetBucketVersioning", lambda: (s3.put_bucket_versioning(Bucket=B, VersioningConfiguration={"Status": "Enabled"}),
                                          s3.get_bucket_versioning(Bucket=B)["Status"] == "Enabled")[1])
t("s3 Put/GetBucketTagging", lambda: (s3.put_bucket_tagging(Bucket=B, Tagging={"TagSet": [{"Key": "project", "Value": "cloudcafe"}]}),
                                       s3.get_bucket_tagging(Bucket=B)["TagSet"] == [{"Key": "project", "Value": "cloudcafe"}])[1])
t("s3 GetBucketLocation", lambda: s3.get_bucket_location(Bucket=B) is not None)
t("s3 Put/GetBucketPolicy", lambda: (s3.put_bucket_policy(Bucket=B, Policy=json.dumps({"Version": "2012-10-17", "Statement": [
    {"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{B}/*"}]})),
    "s3:GetObject" in s3.get_bucket_policy(Bucket=B)["Policy"])[1])
# ---- IAM
t("iam CreateUser", lambda: iam.create_user(UserName="dev1"))
t("iam CreateGroup+AddUser", lambda: (iam.create_group(GroupName="devs"), iam.add_user_to_group(GroupName="devs", UserName="dev1")))
pol = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}]})
t("iam CreatePolicy+Attach", lambda: iam.attach_user_policy(UserName="dev1", PolicyArn=iam.create_policy(
    PolicyName="ro", PolicyDocument=pol)["Policy"]["Arn"]))
t("iam CreateRole(trust)", lambda: iam.create_role(RoleName="lambda-role", AssumeRolePolicyDocument=json.dumps({
    "Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]})))
t("iam ListAttachedUserPolicies", lambda: len(iam.list_attached_user_policies(UserName="dev1")["AttachedPolicies"]) == 1)
t("iam SimulatePrincipalPolicy", lambda: iam.simulate_principal_policy(
    PolicySourceArn=iam.get_user(UserName="dev1")["User"]["Arn"], ActionNames=["s3:GetObject", "s3:PutObject"])["EvaluationResults"])
# ---- DynamoDB
t("ddb CreateTable", lambda: ddb.create_table(TableName="orders", BillingMode="PAY_PER_REQUEST",
    KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}], AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}]))
t("ddb Put/GetItem", lambda: (ddb.put_item(TableName="orders", Item={"id": {"S": "1"}, "qty": {"N": "2"}}),
                               ddb.get_item(TableName="orders", Key={"id": {"S": "1"}})["Item"]["qty"]["N"] == "2")[1])
t("ddb DescribeTable billing", lambda: ddb.describe_table(TableName="orders")["Table"].get("BillingModeSummary", {}).get("BillingMode") == "PAY_PER_REQUEST")
# ---- EC2
t("ec2 CreateSecurityGroup+Ingress", lambda: ec2.authorize_security_group_ingress(GroupId=ec2.create_security_group(
    GroupName="web", Description="web")["GroupId"], IpPermissions=[{"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]))
t("ec2 DescribeImages", lambda: len(ec2.describe_images(Owners=["amazon"]).get("Images", [])) >= 0)
t("ec2 RunInstances(t2.micro)", lambda: ec2.run_instances(ImageId="ami-12345678", InstanceType="t2.micro", MinCount=1, MaxCount=1,
                                                         TagSpecifications=[{"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "web"}]}]))
t("ec2 DescribeInstances(tag)", lambda: len(ec2.describe_instances(Filters=[{"Name": "tag:Name", "Values": ["web"]}])["Reservations"]) == 1)
# ---- Lambda
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("app.py", "def handler(e, c):\n    return {'ok': True}\n")
t("lambda CreateFunction", lambda: lam.create_function(FunctionName="hello", Runtime="python3.12", Handler="app.handler",
    Role=iam.get_role(RoleName="lambda-role")["Role"]["Arn"], Code={"ZipFile": buf.getvalue()}))
t("lambda GetFunction config", lambda: lam.get_function(FunctionName="hello")["Configuration"]["Runtime"] == "python3.12")
t("lambda Invoke (runs code)", lambda: b'"ok": true' in lam.invoke(FunctionName="hello")["Payload"].read())

for r in results:
    print(f"{r[1]:<5} {r[0]:<34} {r[2]}")
print("SUMMARY", sum(r[1] == "PASS" for r in results), "/", len(results))
