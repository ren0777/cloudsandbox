"""The curated break-action catalogue (phase 9, milestone 41).

Every action is safe by construction: typed parameters, no shell from the instructor, and a deterministic
compiler. `reads` names the emulator operations the action performs, so import-time capability validation
can refuse an action on an engine that does not support it.
"""

from __future__ import annotations

import shlex
from typing import Literal

from pydantic import Field

from .registry import ActionParams, BreakActionDef, register

IAM_NAME = r"^[A-Za-z0-9][A-Za-z0-9+=,.@_-]{0,63}$"
POLICY = (r"^(?:[A-Za-z0-9+=,.@_/-]{1,128}"
          r"|arn:aws[a-z-]*:iam::\d{12}:policy/[A-Za-z0-9+=,.@_/-]{1,128})$")
BUCKET = r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$"
FUNCTION = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
ENV_NAME = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
SG_NAME = r"^[A-Za-z0-9][A-Za-z0-9 ._:/@()#+,=-]{0,254}$"
CIDR = r"^[0-9A-Fa-f.:]{2,43}/[0-9]{1,3}$"
TEXT = r"^[ -~]{1,255}$"

TargetType = Literal["user", "group", "role"]
Protocol = Literal["tcp", "udp"]


def _q(v: str) -> str:
    return shlex.quote(str(v))


def _policy_arn(policy: str) -> str:
    return policy if policy.startswith("arn:") else f"arn:aws:iam::aws:policy/{policy}"


# -------------------------------------------------------------------------------------------- IAM
class CreateGroup(ActionParams):
    group: str = Field(pattern=IAM_NAME)


class CreateUser(ActionParams):
    user: str = Field(pattern=IAM_NAME)


class AddUserToGroup(ActionParams):
    user: str = Field(pattern=IAM_NAME)
    group: str = Field(pattern=IAM_NAME)


class TargetPolicy(ActionParams):
    target_type: TargetType
    target: str = Field(pattern=IAM_NAME)
    policy: str = Field(pattern=POLICY)


def _target_flag(t: TargetType) -> str:
    return {"user": "--user-name", "group": "--group-name", "role": "--role-name"}[t]


def _attach_reads(p: TargetPolicy) -> tuple[str, ...]:
    return (f"iam:Attach{p.target_type.capitalize()}Policy",)


def _detach_reads(p: TargetPolicy) -> tuple[str, ...]:
    return (f"iam:Detach{p.target_type.capitalize()}Policy",)


def _compile_attach(p: TargetPolicy) -> list[str]:
    verb = {"user": "attach-user-policy", "group": "attach-group-policy", "role": "attach-role-policy"}[p.target_type]
    return [f"aws iam {verb} {_target_flag(p.target_type)} {_q(p.target)} --policy-arn {_q(_policy_arn(p.policy))}"]


def _compile_detach(p: TargetPolicy) -> list[str]:
    verb = {"user": "detach-user-policy", "group": "detach-group-policy", "role": "detach-role-policy"}[p.target_type]
    return [f"aws iam {verb} {_target_flag(p.target_type)} {_q(p.target)} --policy-arn {_q(_policy_arn(p.policy))}"]


register(BreakActionDef("iam.create_group", CreateGroup, "iam", ("iam:CreateGroup",),
                        lambda p: [f"aws iam create-group --group-name {_q(p.group)}"],
                        lambda p: f"Group {p.group} exists"))
register(BreakActionDef("iam.create_user", CreateUser, "iam", ("iam:CreateUser",),
                        lambda p: [f"aws iam create-user --user-name {_q(p.user)}"],
                        lambda p: f"User {p.user} exists"))
register(BreakActionDef("iam.add_user_to_group", AddUserToGroup, "iam", ("iam:AddUserToGroup",),
                        lambda p: [f"aws iam add-user-to-group --group-name {_q(p.group)} --user-name {_q(p.user)}"],
                        lambda p: f"{p.user} is a member of {p.group}"))
register(BreakActionDef("iam.attach_managed_policy", TargetPolicy, "iam", _attach_reads, _compile_attach,
                        lambda p: f"{p.target} ({p.target_type}) has {p.policy}"))
register(BreakActionDef("iam.detach_managed_policy", TargetPolicy, "iam", _detach_reads, _compile_detach,
                        lambda p: f"{p.target} ({p.target_type}) is missing {p.policy}"))


# --------------------------------------------------------------------------------------------- S3
class Bucket(ActionParams):
    bucket: str = Field(pattern=BUCKET)


register(BreakActionDef("s3.create_bucket", Bucket, "s3", ("s3:CreateBucket",),
                        lambda p: [f"aws s3api create-bucket --bucket {_q(p.bucket)}"],
                        lambda p: f"Bucket {p.bucket} exists"))
register(BreakActionDef("s3.disable_versioning", Bucket, "s3", ("s3:PutBucketVersioning",),
                        lambda p: [f"aws s3api put-bucket-versioning --bucket {_q(p.bucket)} "
                                   "--versioning-configuration Status=Suspended"],
                        lambda p: f"Bucket {p.bucket} has versioning disabled"))
register(BreakActionDef("s3.delete_bucket_policy", Bucket, "s3", ("s3:DeleteBucketPolicy",),
                        lambda p: [f"aws s3api delete-bucket-policy --bucket {_q(p.bucket)} 2>/dev/null || true"],
                        lambda p: f"Bucket {p.bucket} has no bucket policy"))
register(BreakActionDef("s3.block_public_access", Bucket, "s3", ("s3:PutPublicAccessBlock",),
                        lambda p: [f"aws s3api put-public-access-block --bucket {_q(p.bucket)} "
                                   "--public-access-block-configuration "
                                   "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,"
                                   "RestrictPublicBuckets=true"],
                        lambda p: f"Bucket {p.bucket} blocks all public access"))
register(BreakActionDef("s3.delete_bucket_tagging", Bucket, "s3", ("s3:DeleteBucketTagging",),
                        lambda p: [f"aws s3api delete-bucket-tagging --bucket {_q(p.bucket)} 2>/dev/null || true"],
                        lambda p: f"Bucket {p.bucket} has no tags"))


# -------------------------------------------------------------------------------------------- EC2
class SecurityGroup(ActionParams):
    group: str = Field(pattern=SG_NAME)
    description: str = Field("Created by Stackora break-fix setup", pattern=TEXT)


class IngressRule(ActionParams):
    group: str = Field(pattern=SG_NAME)
    protocol: Protocol = "tcp"
    port: int = Field(ge=0, le=65535)
    cidr: str = Field(pattern=CIDR)


register(BreakActionDef("ec2.create_security_group", SecurityGroup, "ec2", ("ec2:CreateSecurityGroup",),
                        lambda p: [f"aws ec2 create-security-group --group-name {_q(p.group)} "
                                   f"--description {_q(p.description)}"],
                        lambda p: f"Security group {p.group} exists"))
register(BreakActionDef("ec2.authorize_ingress", IngressRule, "ec2", ("ec2:AuthorizeSecurityGroupIngress",),
                        lambda p: [f"aws ec2 authorize-security-group-ingress --group-name {_q(p.group)} "
                                   f"--protocol {p.protocol} --port {p.port} --cidr {_q(p.cidr)}"],
                        lambda p: f"{p.group} allows {p.protocol}/{p.port} from {p.cidr}"))
register(BreakActionDef("ec2.revoke_ingress", IngressRule, "ec2", ("ec2:RevokeSecurityGroupIngress",),
                        lambda p: [f"aws ec2 revoke-security-group-ingress --group-name {_q(p.group)} "
                                   f"--protocol {p.protocol} --port {p.port} --cidr {_q(p.cidr)}"],
                        lambda p: f"{p.group} no longer allows {p.protocol}/{p.port} from {p.cidr}"))


# ----------------------------------------------------------------------------------------- Lambda
class RemoveEnvVar(ActionParams):
    function: str = Field(pattern=FUNCTION)
    name: str = Field(pattern=ENV_NAME)


def _compile_remove_env(p: RemoveEnvVar) -> list[str]:
    f = _q(p.function)
    return [
        f"ENV=$(aws lambda get-function-configuration --function-name {f} "
        "--query 'Environment.Variables' --output json)",
        f"printf '%s' \"$ENV\" | jq -c '(. // {{}}) | del(.\"{p.name}\")' > /tmp/cloudlabs-env.json",
        f"aws lambda update-function-configuration --function-name {f} "
        f'--environment "{{\\"Variables\\": $(cat /tmp/cloudlabs-env.json)}}"',
    ]


register(BreakActionDef("lambda.remove_env_var", RemoveEnvVar, "lambda", ("lambda:UpdateFunctionConfiguration",),
                        _compile_remove_env,
                        lambda p: f"Function {p.function} is missing the environment variable {p.name}"))
