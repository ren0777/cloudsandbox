"""Probe candidate EC2 operations on every engine through the real runner (run inside api-test with
PYTHONPATH=/srv). Prints PASS/FAIL per engine and operation, plus sample AMIs."""
import asyncio
import uuid

from app.config import get_settings
from app.runtime import emulators
from app.runtime.runner_client import HttpRunnerClient


def ops(c, st):
    return [
        ("DescribeImages", lambda: st.__setitem__("ami", sorted(c.describe_images(Owners=["amazon"])["Images"], key=lambda i: i["ImageId"])[0]["ImageId"])),
        ("DescribeImages(sample)", lambda: print("   sample AMIs:", [(i["ImageId"], i.get("Name", "")[:40]) for i in c.describe_images(Owners=["amazon"])["Images"][:4]])),
        ("DescribeInstanceTypes", lambda: len(c.describe_instance_types(InstanceTypes=["t2.micro", "t3.micro"])["InstanceTypes"]) == 2 or 1 / 0),
        ("DescribeVpcs", lambda: st.__setitem__("vpc", c.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"][0]["VpcId"])),
        ("DescribeSubnets", lambda: st.__setitem__("subnet", c.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [st["vpc"]]}])["Subnets"][0]["SubnetId"])),
        ("CreateSecurityGroup", lambda: st.__setitem__("sg", c.create_security_group(GroupName="web-sg", Description="web", VpcId=st["vpc"])["GroupId"])),
        ("AuthorizeSecurityGroupIngress", lambda: c.authorize_security_group_ingress(GroupId=st["sg"], IpPermissions=[
            {"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80, "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "http"}]},
            {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "10.0.0.0/16"}]}])),
        ("DescribeSecurityGroups", lambda: len(c.describe_security_groups(GroupIds=[st["sg"]])["SecurityGroups"][0]["IpPermissions"]) == 2 or 1 / 0),
        ("RevokeSecurityGroupIngress", lambda: c.revoke_security_group_ingress(GroupId=st["sg"], IpPermissions=[
            {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "10.0.0.0/16"}]}])),
        ("CreateKeyPair", lambda: "KeyMaterial" in c.create_key_pair(KeyName="cafe-key") or 1 / 0),
        ("DescribeKeyPairs", lambda: c.describe_key_pairs()["KeyPairs"][0]["KeyName"] == "cafe-key" or 1 / 0),
        ("RunInstances", lambda: st.__setitem__("i", c.run_instances(ImageId=st["ami"], InstanceType="t2.micro", MinCount=1, MaxCount=1,
            KeyName="cafe-key", SecurityGroupIds=[st["sg"]], SubnetId=st["subnet"],
            TagSpecifications=[{"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "web1"}]}])["Instances"][0]["InstanceId"])),
        ("DescribeInstances", lambda: print("   state/type/sg/key:", [(i["State"]["Name"], i["InstanceType"], [g["GroupName"] for g in i.get("SecurityGroups", [])], i.get("KeyName"), i.get("Tags"))
            for r in c.describe_instances(InstanceIds=[st["i"]])["Reservations"] for i in r["Instances"]])),
        ("CreateTags", lambda: c.create_tags(Resources=[st["i"]], Tags=[{"Key": "Project", "Value": "cloudcafe"}])),
        ("DescribeTags", lambda: len(c.describe_tags(Filters=[{"Name": "resource-id", "Values": [st["i"]]}])["Tags"]) == 2 or 1 / 0),
        ("StopInstances", lambda: c.stop_instances(InstanceIds=[st["i"]])),
        ("DescribeInstances(stopped)", lambda: print("   after stop:", c.describe_instances(InstanceIds=[st["i"]])["Reservations"][0]["Instances"][0]["State"]["Name"])),
        ("StartInstances", lambda: c.start_instances(InstanceIds=[st["i"]])),
        ("TerminateInstances", lambda: c.terminate_instances(InstanceIds=[st["i"]])),
        ("DescribeInstances(terminated)", lambda: print("   after terminate:", c.describe_instances(InstanceIds=[st["i"]])["Reservations"][0]["Instances"][0]["State"]["Name"])),
        ("DeleteKeyPair", lambda: c.delete_key_pair(KeyName="cafe-key")),
        ("DeleteSecurityGroup", lambda: c.delete_security_group(GroupId=st["sg"])),
    ]


async def main():
    s = get_settings()
    r = HttpRunnerClient(s.runner_id, s.runner_url, s.runner_secret, 150)
    for eng in emulators.ENGINES:
        sid = str(uuid.uuid4())
        info = await r.create_sandbox({"sandbox_id": sid, "env": s.env, "engine": eng, "terminal_credential": "probe:abcdefgh1234"})
        c = emulators.get(eng).client("ec2", info["emulator_endpoint"])
        st: dict = {}
        for name, fn in ops(c, st):
            try:
                await asyncio.to_thread(fn)
                print(f"{eng:<6} PASS {name}")
            except Exception as e:
                print(f"{eng:<6} FAIL {name}: {str(e)[:120]}")
        await r.destroy_sandbox(sid)


asyncio.run(main())
