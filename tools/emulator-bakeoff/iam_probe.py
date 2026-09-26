"""Probe candidate IAM operations on every engine through the real runner (run inside api-test):
    python /srv/../tools/... (copied) — prints PASS/FAIL per engine and operation."""
import asyncio
import json
import uuid

from app.config import get_settings
from app.runtime import emulators
from app.runtime.runner_client import HttpRunnerClient

POL = json.dumps({"Version": "2012-10-17", "Statement": [
    {"Effect": "Allow", "Action": ["s3:GetObject", "s3:ListBucket"], "Resource": ["arn:aws:s3:::menu", "arn:aws:s3:::menu/*"]}]})
TRUST = json.dumps({"Version": "2012-10-17", "Statement": [
    {"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]})
MANAGED = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"


def ops(c):
    st = {}
    return [
        ("CreateUser", lambda: c.create_user(UserName="dev1", Tags=[{"Key": "team", "Value": "cafe"}])),
        ("GetUser", lambda: c.get_user(UserName="dev1")["User"]["Arn"]),
        ("ListUsers", lambda: [u["UserName"] for u in c.list_users()["Users"]] == ["dev1"] or 1 / 0),
        ("CreateGroup", lambda: c.create_group(GroupName="devs")),
        ("ListGroups", lambda: c.list_groups()["Groups"]),
        ("AddUserToGroup", lambda: c.add_user_to_group(GroupName="devs", UserName="dev1")),
        ("ListGroupsForUser", lambda: [g["GroupName"] for g in c.list_groups_for_user(UserName="dev1")["Groups"]] == ["devs"] or 1 / 0),
        ("GetGroup", lambda: [u["UserName"] for u in c.get_group(GroupName="devs")["Users"]] == ["dev1"] or 1 / 0),
        ("CreatePolicy", lambda: st.__setitem__("arn", c.create_policy(PolicyName="menu-read", PolicyDocument=POL)["Policy"]["Arn"])),
        ("GetPolicy", lambda: c.get_policy(PolicyArn=st["arn"])["Policy"]["DefaultVersionId"]),
        ("GetPolicyVersion", lambda: c.get_policy_version(PolicyArn=st["arn"], VersionId="v1")["PolicyVersion"]["Document"]),
        ("ListPolicies(Local)", lambda: [p["PolicyName"] for p in c.list_policies(Scope="Local")["Policies"]] == ["menu-read"] or 1 / 0),
        ("GetPolicy(AWS managed)", lambda: c.get_policy(PolicyArn=MANAGED)["Policy"]["DefaultVersionId"]),
        ("GetPolicyVersion(AWS managed)", lambda: c.get_policy_version(PolicyArn=MANAGED, VersionId=c.get_policy(PolicyArn=MANAGED)["Policy"]["DefaultVersionId"])["PolicyVersion"]["Document"]),
        ("ListPolicies(AWS)", lambda: len(c.list_policies(Scope="AWS", MaxItems=50)["Policies"]) > 0 or 1 / 0),
        ("AttachGroupPolicy", lambda: c.attach_group_policy(GroupName="devs", PolicyArn=st["arn"])),
        ("ListAttachedGroupPolicies", lambda: len(c.list_attached_group_policies(GroupName="devs")["AttachedPolicies"]) == 1 or 1 / 0),
        ("AttachUserPolicy(managed)", lambda: c.attach_user_policy(UserName="dev1", PolicyArn=MANAGED)),
        ("ListAttachedUserPolicies", lambda: len(c.list_attached_user_policies(UserName="dev1")["AttachedPolicies"]) == 1 or 1 / 0),
        ("DetachUserPolicy", lambda: c.detach_user_policy(UserName="dev1", PolicyArn=MANAGED)),
        ("PutUserPolicy", lambda: c.put_user_policy(UserName="dev1", PolicyName="inline1", PolicyDocument=POL)),
        ("ListUserPolicies", lambda: c.list_user_policies(UserName="dev1")["PolicyNames"] == ["inline1"] or 1 / 0),
        ("GetUserPolicy", lambda: c.get_user_policy(UserName="dev1", PolicyName="inline1")["PolicyDocument"]),
        ("DeleteUserPolicy", lambda: c.delete_user_policy(UserName="dev1", PolicyName="inline1")),
        ("CreateRole", lambda: c.create_role(RoleName="fn-role", AssumeRolePolicyDocument=TRUST, Description="d")),
        ("GetRole", lambda: c.get_role(RoleName="fn-role")["Role"]["AssumeRolePolicyDocument"]),
        ("ListRoles", lambda: [r["RoleName"] for r in c.list_roles()["Roles"]]),
        ("AttachRolePolicy", lambda: c.attach_role_policy(RoleName="fn-role", PolicyArn=st["arn"])),
        ("ListAttachedRolePolicies", lambda: len(c.list_attached_role_policies(RoleName="fn-role")["AttachedPolicies"]) == 1 or 1 / 0),
        ("ListRolePolicies", lambda: c.list_role_policies(RoleName="fn-role")["PolicyNames"]),
        ("RemoveUserFromGroup", lambda: c.remove_user_from_group(GroupName="devs", UserName="dev1")),
        ("DetachGroupPolicy", lambda: c.detach_group_policy(GroupName="devs", PolicyArn=st["arn"])),
        ("DetachRolePolicy", lambda: c.detach_role_policy(RoleName="fn-role", PolicyArn=st["arn"])),
        ("DeletePolicy", lambda: c.delete_policy(PolicyArn=st["arn"])),
        ("DeleteRole", lambda: c.delete_role(RoleName="fn-role")),
        ("DeleteGroup", lambda: c.delete_group(GroupName="devs")),
        ("DeleteUser", lambda: c.delete_user(UserName="dev1")),
        ("SimulatePrincipalPolicy", lambda: c.simulate_custom_policy(PolicyInputList=[POL], ActionNames=["s3:GetObject"])),
    ]


async def main():
    s = get_settings()
    r = HttpRunnerClient(s.runner_id, s.runner_url, s.runner_secret, 150)
    for eng in emulators.ENGINES:
        sid = str(uuid.uuid4())
        info = await r.create_sandbox({"sandbox_id": sid, "env": s.env, "engine": eng,
                                       "terminal_credential": "probe:abcdefgh1234"})
        c = emulators.get(eng).client("iam", info["emulator_endpoint"])
        for name, fn in ops(c):
            try:
                await asyncio.to_thread(fn)
                print(f"{eng:<6} PASS {name}")
            except Exception as e:
                print(f"{eng:<6} FAIL {name}: {str(e)[:110]}")
        await r.destroy_sandbox(sid)


asyncio.run(main())
