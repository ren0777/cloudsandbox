"""Phase 9 milestone 41 — typed break actions: the registry, the deterministic compiler, schema rules,
capability validation, the compiled setup job and the baseline publish gate."""

from __future__ import annotations

import base64
import hashlib
from decimal import Decimal

import pytest
import yaml
from pydantic import ValidationError

from app import breakfix
from app.labs import drafts as dr
from app.labs.package import pack_from_files, setup_job, tar_members
from app.labs.render import compute_variables
from app.labs.schema import LabValidationError, parse_definition

SAMPLE_SHORT = "abc123"


def _lab(**over):
    lab = {
        "schema_version": 1, "id": "bf-test", "version": "1.0.0", "kind": "break_fix",
        "title": "Broken IAM", "services": ["iam"], "duration_minutes": 30,
        "variables": {"group": "baristas-{{ student_short_id }}"},
        "break_actions": [
            {"type": "iam.create_group", "group": "{{ group }}"},
            {"type": "iam.attach_managed_policy", "target_type": "group", "target": "{{ group }}",
             "policy": "AdministratorAccess"},
        ],
        "tasks": [{"id": "fix", "title": "Fix it", "marks": 100,
                   "checks": [{"type": "iam.group_exists", "group": "{{ group }}"}]}],
    }
    lab.update(over)
    return lab


def _files(lab=None, **private):
    files = {
        "lab.yaml": yaml.safe_dump(lab or _lab()).encode(),
        "private/solution.sh": b"#!/bin/bash\naws iam detach-group-policy --group-name \"$GROUP\" "
                               b"--policy-arn arn:aws:iam::aws:policy/AdministratorAccess\n",
        "private/expected.yaml": b'empty: "0.00"\nsolution: "100.00"\n',
    }
    files.update({f"private/{k}": v.encode() if isinstance(v, str) else v for k, v in private.items()})
    return files


# --------------------------------------------------------------------------------------- compiler
def test_compiler_is_deterministic_and_compiles_typed_actions():
    specs = [
        {"type": "iam.create_user", "user": "former-intern"},
        {"type": "iam.attach_managed_policy", "target_type": "user", "target": "former-intern",
         "policy": "AdministratorAccess"},
    ]
    a, b = breakfix.compile_actions(specs), breakfix.compile_actions(specs)
    assert a == b, "the same actions must always compile to the same setup script"
    assert a.startswith("#!/bin/bash\n") and "set -euo pipefail" in a
    assert "aws iam create-user --user-name former-intern" in a
    assert "aws iam attach-user-policy --user-name former-intern " \
           "--policy-arn arn:aws:iam::aws:policy/AdministratorAccess" in a
    # order is preserved (setup is deterministic, not sorted)
    assert a.index("create-user") < a.index("attach-user-policy")


def test_compiler_rejects_unknown_actions_and_bad_params():
    with pytest.raises(ValueError, match="unknown break action"):
        breakfix.compile_actions([{"type": "nope.nope"}])
    with pytest.raises(ValidationError):
        breakfix.compile_actions([{"type": "iam.create_group"}])
    with pytest.raises(ValidationError):
        breakfix.compile_actions([{"type": "iam.attach_managed_policy", "target_type": "bucket",
                                   "target": "x", "policy": "AdministratorAccess"}])


def test_shell_values_are_quoted_not_interpolated():
    # Parameters are pattern-validated; the compiler also quotes every value it emits.
    script = breakfix.compile_actions([{"type": "ec2.create_security_group",
                                        "group": "web sg", "description": "it's open"}])
    assert "aws ec2 create-security-group --group-name 'web sg' --description 'it'\"'\"'s open'" in script


# ----------------------------------------------------------------------------------------- schema
def test_schema_accepts_break_actions_and_baseline():
    d = parse_definition(_lab(baseline={"expected_score": "40.00"}))
    assert d.kind == "break_fix" and len(d.break_actions) == 2
    assert d.baseline is not None and str(d.baseline.expected_score) == "40.00"
    assert d.setup is None


@pytest.mark.parametrize("over, needle", [
    ({"kind": "guided", "break_actions": [{"type": "iam.create_group", "group": "g"}]},
     "only a break_fix lab"),
    ({"setup": {"script": "setup.sh"}, "break_actions": [{"type": "iam.create_group", "group": "g"}]},
     "not both"),
    ({"break_actions": []}, "needs break_actions"),
    ({"baseline": {"expected_score": "100.00"}}, "below full marks"),
    ({"kind": "guided", "baseline": {"expected_score": "0"}}, "only a break_fix lab"),
])
def test_schema_rejects_invalid_break_fix_combinations(over, needle):
    with pytest.raises(LabValidationError) as e:
        parse_definition(_lab(**over))
    assert needle in str(e.value)


# ------------------------------------------------------------------------------------- validation
def test_validate_definition_checks_action_types_params_and_services():
    bad_type = _lab(break_actions=[{"type": "iam.nope"}])
    with pytest.raises(LabValidationError) as e:
        pack_from_files(_files(bad_type))
    assert "unknown break action type" in str(e.value)

    bad_params = _lab(break_actions=[{"type": "iam.attach_managed_policy", "target_type": "group",
                                      "target": "baristas", "policy": "AdministratorAccess", "oops": 1}])
    with pytest.raises(LabValidationError) as e:
        pack_from_files(_files(bad_params))
    assert "oops" in str(e.value)

    wrong_service = _lab(services=["s3"], break_actions=[{"type": "iam.create_group", "group": "baristas"}])
    with pytest.raises(LabValidationError) as e:
        pack_from_files(_files(wrong_service))
    assert "not listed in services" in str(e.value)


def test_validate_definition_checks_action_capabilities():
    # IAM actions are supported on the primary engines, but MiniStack is Lambda-only.
    lab = _lab(runtime={"emulator": "ministack"})
    with pytest.raises(LabValidationError) as e:
        pack_from_files(_files(lab))
    assert "unsupported emulator operations on ministack" in str(e.value)


# -------------------------------------------------------------------------------------- setup job
def test_setup_job_compiles_actions_into_the_public_bundle():
    pkg = pack_from_files(_files())
    variables = compute_variables(pkg.definition, SAMPLE_SHORT)
    job = setup_job(pkg.public_bundle, pkg.definition, variables)
    assert job is not None and job["timeout_s"] == 180  # CLI-heavy setups (e.g. a VPC network) need headroom
    raw = base64.b64decode(job["bundle_b64"])
    assert hashlib.sha256(raw).hexdigest() == job["sha256"]
    members = tar_members(raw)
    script = members["public/_cloudlabs_break_actions.sh"].decode()
    assert "baristas-abc123" in script, "variables must be rendered into the compiled script"
    assert "aws iam attach-group-policy --group-name baristas-abc123 " \
           "--policy-arn arn:aws:iam::aws:policy/AdministratorAccess" in script
    wrapper = members["_cloudlabs_setup.sh"].decode()
    assert "bash _cloudlabs_break_actions.sh" in wrapper and "export GROUP=baristas-abc123" in wrapper


# --------------------------------------------------------------------------------------- baseline
def test_baseline_drives_the_expected_empty_score():
    lab = _lab(baseline={"expected_score": "40.00"})
    pkg = pack_from_files(_files(lab, **{"expected.yaml": 'empty: "40.00"\nsolution: "100.00"\n'}))
    expected, errors = dr.expectations(_files(lab, **{"expected.yaml": 'empty: "40.00"\nsolution: "100.00"\n'}),
                                       pkg.definition)
    assert not errors and expected["empty"] == Decimal("40.00")
    # expected.yaml that still says 0 does not match the declared baseline
    _, errors = dr.expectations(_files(lab), pkg.definition)
    assert any("broken baseline must score 40" in e for e in errors), errors


def test_compiler_covers_the_vpc_actions():
    """The VPC catalogue compiles to deterministic AWS CLI; both the create and the break side are covered."""
    specs = [
        {"type": "vpc.create_vpc", "name": "cafe-vpc-abc123", "cidr": "10.0.0.0/16"},
        {"type": "vpc.create_subnet", "vpc": "cafe-vpc-abc123", "name": "public-abc123",
         "cidr": "10.0.1.0/24", "public": True},
        {"type": "vpc.create_internet_gateway", "vpc": "cafe-vpc-abc123", "name": "igw-abc123"},
        {"type": "vpc.create_route_table", "vpc": "cafe-vpc-abc123", "name": "rtb-abc123"},
        {"type": "vpc.create_route", "route_table": "rtb-abc123", "destination": "0.0.0.0/0",
         "internet_gateway": "igw-abc123"},
        {"type": "vpc.associate_route_table", "route_table": "rtb-abc123", "subnet": "public-abc123"},
        {"type": "vpc.create_security_group", "vpc": "cafe-vpc-abc123", "group": "web-abc123"},
        {"type": "vpc.authorize_ingress", "group": "web-abc123", "protocol": "tcp", "port": 80,
         "cidr": "0.0.0.0/0"},
        {"type": "vpc.delete_route", "route_table": "rtb-abc123", "destination": "0.0.0.0/0"},
        {"type": "vpc.revoke_ingress", "group": "web-abc123", "protocol": "tcp", "port": 80,
         "cidr": "0.0.0.0/0"},
    ]
    script = breakfix.compile_actions(specs)
    assert script == breakfix.compile_actions(specs)
    for expected in (
        'aws ec2 create-vpc --cidr-block 10.0.0.0/16 --query "Vpc.VpcId" --output text',
        "Key=Name,Value=cafe-vpc-abc123",
        "aws ec2 create-subnet --vpc-id $(aws ec2 describe-vpcs --filters Name=tag:Name,Values=cafe-vpc-abc123",
        "--map-public-ip-on-launch",
        'aws ec2 attach-internet-gateway --internet-gateway-id "$IGW_ID"',
        "aws ec2 create-route --route-table-id $(aws ec2 describe-route-tables",
        "--gateway-id $(aws ec2 describe-internet-gateways",
        "aws ec2 associate-route-table",
        "aws ec2 authorize-security-group-ingress --group-id $(aws ec2 describe-security-groups",
        "--protocol tcp --port 80 --cidr 0.0.0.0/0",
        "aws ec2 delete-route",
        "aws ec2 revoke-security-group-ingress",
    ):
        assert expected in script, expected


def test_compiler_covers_the_sqs_actions():
    specs = [
        {"type": "sqs.create_queue", "name": "cafe-orders-abc123", "visibility_timeout": 30,
         "retention_period": 3600, "delay_seconds": 0},
        {"type": "sqs.set_queue_attribute", "queue": "cafe-orders-abc123",
         "attribute": "VisibilityTimeout", "value": 30},
        {"type": "sqs.send_message", "queue": "cafe-orders-abc123", "body": '{"drink": "latte"}'},
        {"type": "sqs.delete_queue", "queue": "cafe-orders-abc123"},
    ]
    script = breakfix.compile_actions(specs)
    assert script == breakfix.compile_actions(specs)
    for expected in (
        "aws sqs create-queue --queue-name cafe-orders-abc123",
        "--attributes VisibilityTimeout=30,MessageRetentionPeriod=3600,DelaySeconds=0",
        'aws sqs set-queue-attributes --queue-url $(aws sqs get-queue-url --queue-name cafe-orders-abc123',
        "--attributes VisibilityTimeout=30",
        "aws sqs send-message --queue-url $(aws sqs get-queue-url",
        "aws sqs delete-queue --queue-url $(aws sqs get-queue-url",
    ):
        assert expected in script, expected
    # FIFO needs the .fifo suffix and the attribute
    with pytest.raises(ValueError):
        breakfix.compile_actions([{"type": "sqs.create_queue", "name": "orders", "fifo": True}])
    fifo = breakfix.compile_actions([{"type": "sqs.create_queue", "name": "orders.fifo", "fifo": True}])
    assert "FifoQueue=true" in fifo


def test_compiler_covers_the_sns_actions():
    specs = [
        {"type": "sns.create_topic", "name": "cafe-alerts-abc123"},
        {"type": "sns.subscribe_sqs", "topic": "cafe-alerts-abc123", "queue": "cafe-orders-abc123",
         "raw_delivery": True},
        {"type": "sns.publish", "topic": "cafe-alerts-abc123", "message": '{"alert": "latte"}'},
        {"type": "sns.unsubscribe_sqs", "topic": "cafe-alerts-abc123", "queue": "cafe-orders-abc123"},
        {"type": "sns.delete_topic", "name": "cafe-alerts-abc123"},
    ]
    script = breakfix.compile_actions(specs)
    assert script == breakfix.compile_actions(specs)
    for expected in (
        "aws sns create-topic --name cafe-alerts-abc123",
        "aws sns subscribe --topic-arn $(aws sns create-topic --name cafe-alerts-abc123",
        "--protocol sqs",
        "--notification-endpoint",
        "--attributes RawMessageDelivery=true",
        "aws sns publish --topic-arn $(aws sns create-topic",
        "aws sns list-subscriptions-by-topic",
        "aws sns unsubscribe",
        "aws sns delete-topic",
    ):
        assert expected in script, expected
