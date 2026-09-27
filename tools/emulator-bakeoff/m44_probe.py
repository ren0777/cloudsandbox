"""M44 probe: VPC, SQS and SNS on one emulator endpoint, under CloudLabs sandbox hardening.

Run from a container on the same internal network as the emulator:
    python m44_probe.py http://<emulator-ip>:<port>

Prints one `RESULT <service> <op> PASS|FAIL|PARTIAL <detail>` line per operation (the operation sets
follow the M44 contract tests), then a per-service summary. Exit status is always 0: the run's value is
the table, not the exit code.
"""
import json
import sys
import time
from datetime import datetime, timezone

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

EP = sys.argv[1]
SUFFIX = datetime.now(timezone.utc).strftime("%H%M%S")
KW = dict(endpoint_url=EP, region_name="us-east-1", aws_access_key_id="cloudlabs",
          aws_secret_access_key="cloudlabs",
          config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 1, "mode": "standard"},
                        connect_timeout=5, read_timeout=30))

results: list[tuple[str, str, str, str]] = []  # (service, op, status, detail)


def rec(service: str, op: str, status: str, detail: str = "") -> None:
    results.append((service, op, status, detail))
    print(f"RESULT {service:<5} {op:<44} {status:<7} {detail}", flush=True)


def t(service: str, op: str, fn):
    """Run fn; PASS on truthy/none, PARTIAL on explicit False, FAIL on exception."""
    try:
        out = fn()
        if out is False:
            rec(service, op, "PARTIAL", "ran but semantics differ")
        else:
            rec(service, op, "PASS", "" if out in (None, True) else str(out)[:80])
        return out
    except ClientError as e:
        err = e.response.get("Error", {})
        rec(service, op, "FAIL", f"{err.get('Code')}: {err.get('Message', '')[:70]}")
    except Exception as e:  # noqa: BLE001
        rec(service, op, "FAIL", f"{type(e).__name__}: {str(e)[:70]}")
    return None


def wait_for(fn, timeout=10.0, interval=0.4):
    """Poll fn until it returns truthy; return its last value."""
    deadline = time.monotonic() + timeout
    out = fn()
    while not out and time.monotonic() < deadline:
        time.sleep(interval)
        out = fn()
    return out


# ------------------------------------------------------------------------------------------------ VPC
def vpc_suite(ec2) -> None:
    st: dict = {}
    t("vpc", "DescribeVpcs(default)", lambda: print_default(ec2))
    t("vpc", "CreateVpc", lambda: st.update(vpc=ec2.create_vpc(CidrBlock="10.42.0.0/16")["Vpc"]["VpcId"]) or st["vpc"])
    t("vpc", "DescribeVpcs(created)", lambda: describe_created_vpc(ec2, st))
    t("vpc", "CreateTags(vpc)/DescribeTags", lambda: tag_vpc(ec2, st))
    t("vpc", "ModifyVpcAttribute(EnableDnsSupport)", lambda: ec2.modify_vpc_attribute(VpcId=st["vpc"],
        EnableDnsSupport={"Value": True}))
    t("vpc", "DescribeVpcAttribute", lambda: ec2.describe_vpc_attribute(VpcId=st["vpc"],
        Attribute="enableDnsSupport")["EnableDnsSupport"]["Value"] in (True, False))

    t("vpc", "CreateSubnet", lambda: st.update(subnet=ec2.create_subnet(VpcId=st["vpc"], CidrBlock="10.42.1.0/24",
        AvailabilityZone="us-east-1a")["Subnet"]["SubnetId"]) or st["subnet"])
    t("vpc", "DescribeSubnets", lambda: [s for s in ec2.describe_subnets(Filters=[{"Name": "vpc-id",
        "Values": [st["vpc"]]}])["Subnets"] if s["SubnetId"] == st["subnet"]][0]["State"] == "available" or 1 / 0)
    t("vpc", "ModifySubnetAttribute", lambda: ec2.modify_subnet_attribute(SubnetId=st["subnet"],
        MapPublicIpOnLaunch={"Value": True}))

    t("vpc", "CreateInternetGateway", lambda: st.update(igw=ec2.create_internet_gateway(
        TagSpecifications=[{"ResourceType": "internet-gateway", "Tags": [{"Key": "Name", "Value": f"igw-{SUFFIX}"}]}])
        ["InternetGateway"]["InternetGatewayId"]) or st["igw"])
    # TagSpecifications on create is convenient but not required; the suite above stays on core calls.
    t("vpc", "AttachInternetGateway", lambda: ec2.attach_internet_gateway(InternetGatewayId=st["igw"], VpcId=st["vpc"]))
    t("vpc", "DescribeInternetGateways(attachment)", lambda: describe_igw(ec2, st))

    t("vpc", "CreateRouteTable", lambda: st.update(rtb=ec2.create_route_table(VpcId=st["vpc"],
        TagSpecifications=[{"ResourceType": "route-table", "Tags": [{"Key": "Name", "Value": f"public-rtb-{SUFFIX}"}]}])
        ["RouteTable"]["RouteTableId"]) or st["rtb"])
    t("vpc", "CreateRoute(igw)", lambda: ec2.create_route(RouteTableId=st["rtb"], DestinationCidrBlock="0.0.0.0/0",
        GatewayId=st["igw"]))
    t("vpc", "DescribeRouteTables(route)", lambda: describe_route(ec2, st))
    t("vpc", "AssociateRouteTable", lambda: st.update(assoc=ec2.associate_route_table(RouteTableId=st["rtb"],
        SubnetId=st["subnet"])["AssociationId"]) or st["assoc"])
    t("vpc", "DescribeRouteTables(association)", lambda: describe_assoc(ec2, st))

    t("vpc", "CreateSecurityGroup(in vpc)", lambda: st.update(sg=ec2.create_security_group(GroupName=f"web-{SUFFIX}",
        Description="m44 web", VpcId=st["vpc"],
        TagSpecifications=[{"ResourceType": "security-group", "Tags": [{"Key": "Name", "Value": f"web-sg-{SUFFIX}"}]}])
        ["GroupId"]) or st["sg"])
    t("vpc", "AuthorizeSecurityGroupIngress", lambda: ec2.authorize_security_group_ingress(GroupId=st["sg"],
        IpPermissions=[{"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80,
                        "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "http"}]},
                       {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
                        "IpRanges": [{"CidrIp": "10.42.0.0/16"}]}]))
    t("vpc", "DescribeSecurityGroups(in vpc)", lambda: describe_sg(ec2, st))
    t("vpc", "AuthorizeSecurityGroupEgress", lambda: ec2.authorize_security_group_egress(GroupId=st["sg"],
        IpPermissions=[{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
                        "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "https"}]}]))
    t("vpc", "RevokeSecurityGroupIngress", lambda: ec2.revoke_security_group_ingress(GroupId=st["sg"],
        IpPermissions=[{"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
                        "IpRanges": [{"CidrIp": "10.42.0.0/16"}]}]))
    t("vpc", "RevokeSecurityGroupEgress", lambda: ec2.revoke_security_group_egress(GroupId=st["sg"],
        IpPermissions=[{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]))

    # teardown, checks that dependencies are enforced and state disappears
    t("vpc", "DisassociateRouteTable", lambda: ec2.disassociate_route_table(AssociationId=st["assoc"]))
    t("vpc", "DeleteRoute", lambda: ec2.delete_route(RouteTableId=st["rtb"], DestinationCidrBlock="0.0.0.0/0"))
    t("vpc", "DetachInternetGateway", lambda: ec2.detach_internet_gateway(InternetGatewayId=st["igw"], VpcId=st["vpc"]))
    t("vpc", "DeleteInternetGateway", lambda: ec2.delete_internet_gateway(InternetGatewayId=st["igw"]))
    t("vpc", "DeleteRouteTable", lambda: ec2.delete_route_table(RouteTableId=st["rtb"]))
    t("vpc", "DeleteSecurityGroup", lambda: ec2.delete_security_group(GroupId=st["sg"]))
    t("vpc", "DeleteSubnet", lambda: ec2.delete_subnet(SubnetId=st["subnet"]))
    t("vpc", "DeleteVpc", lambda: ec2.delete_vpc(VpcId=st["vpc"]))
    t("vpc", "DeleteVpc(dependent semantics)", lambda: delete_vpc_dependency(ec2))
    unsupported_candidates(ec2)


def print_default(ec2):
    vpcs = ec2.describe_vpcs()["Vpcs"]
    print(f"   default VPCs: {[(v['VpcId'], v['CidrBlock'], v.get('IsDefault')) for v in vpcs[:3]]}")
    return True


def describe_created_vpc(ec2, st):
    v = ec2.describe_vpcs(VpcIds=[st["vpc"]])["Vpcs"][0]
    return True if v["CidrBlock"] == "10.42.0.0/16" and v["State"] == "available" else False


def tag_vpc(ec2, st):
    ec2.create_tags(Resources=[st["vpc"]], Tags=[{"Key": "Name", "Value": f"m44-{SUFFIX}"}])
    tags = ec2.describe_tags(Filters=[{"Name": "resource-id", "Values": [st["vpc"]]}])["Tags"]
    return any(t2["Key"] == "Name" and t2["Value"] == f"m44-{SUFFIX}" for t2 in tags)


def describe_igw(ec2, st):
    igw = ec2.describe_internet_gateways(InternetGatewayIds=[st["igw"]])["InternetGateways"][0]
    return True if any(a.get("VpcId") == st["vpc"] for a in igw.get("Attachments", [])) else False


def describe_route(ec2, st):
    rtb = ec2.describe_route_tables(RouteTableIds=[st["rtb"]])["RouteTables"][0]
    return True if any(r.get("DestinationCidrBlock") == "0.0.0.0/0" and r.get("GatewayId") == st["igw"]
                       for r in rtb.get("Routes", [])) else False


def describe_assoc(ec2, st):
    rtb = ec2.describe_route_tables(RouteTableIds=[st["rtb"]])["RouteTables"][0]
    return True if any(a.get("SubnetId") == st["subnet"] and a.get("RouteTableAssociationId") == st["assoc"]
                       for a in rtb.get("Associations", [])) else False


def describe_sg(ec2, st):
    sg = ec2.describe_security_groups(GroupIds=[st["sg"]])["SecurityGroups"][0]
    ports = sorted(p["FromPort"] for p in sg.get("IpPermissions", []) if p.get("FromPort") is not None)
    return True if sg.get("VpcId") == st["vpc"] and ports == [22, 80] else False


def delete_vpc_dependency(ec2):
    """AWS refuses DeleteVpc while a subnet exists; the run reports which behaviour each engine has."""
    vpc = ec2.create_vpc(CidrBlock="10.43.0.0/16")["Vpc"]["VpcId"]
    sub = ec2.create_subnet(VpcId=vpc, CidrBlock="10.43.1.0/24")["Subnet"]["SubnetId"]
    try:
        ec2.delete_vpc(VpcId=vpc)
        ec2.delete_subnet(SubnetId=sub)
        return "cascaded (AWS would refuse)"
    except ClientError:
        ec2.delete_subnet(SubnetId=sub)
        ec2.delete_vpc(VpcId=vpc)
        return "refused (AWS-faithful)"


unsupported: list[tuple[str, str, str, str]] = []


def u(service: str, op: str, fn) -> None:
    """Probe ops we expect to be unavailable; printed separately so they never pollute the PASS table."""
    try:
        fn()
        unsupported.append((service, op, "IMPLEMENTED", ""))
        print(f"UNSUPPORTED-PROBE {service} {op} IMPLEMENTED (unexpected)", flush=True)
    except Exception as e:  # noqa: BLE001
        detail = (e.response.get("Error", {}).get("Code") if isinstance(e, ClientError)
                  else type(e).__name__) or ""
        unsupported.append((service, op, "absent", str(detail)))
        print(f"UNSUPPORTED-PROBE {service} {op} absent: {detail}", flush=True)


def unsupported_candidates(ec2) -> None:
    """Probe wider VPC surface with real resources; cleanup whatever was created."""
    vpc = ec2.create_vpc(CidrBlock="10.44.0.0/16")["Vpc"]["VpcId"]
    peer = ec2.create_vpc(CidrBlock="10.45.0.0/16")["Vpc"]["VpcId"]
    sub = ec2.create_subnet(VpcId=vpc, CidrBlock="10.44.1.0/24")["Subnet"]["SubnetId"]
    try:
        alloc = ec2.allocate_address(Domain="vpc").get("AllocationId")
    except Exception:  # noqa: BLE001
        alloc = "eipalloc-00000000"
    try:
        u("vpc", "CreateNatGateway", lambda: ec2.create_nat_gateway(SubnetId=sub, AllocationId=alloc))
        u("vpc", "CreateVpcPeeringConnection", lambda: ec2.create_vpc_peering_connection(VpcId=vpc, PeerVpcId=peer))
        u("vpc", "CreateVpcEndpoint", lambda: ec2.create_vpc_endpoint(VpcId=vpc,
            ServiceName="com.amazonaws.us-east-1.s3"))
        u("vpc", "CreateFlowLogs", lambda: ec2.create_flow_logs(ResourceIds=[vpc], ResourceType="VPC",
            TrafficType="ALL", LogDestinationType="cloud-watch-logs", LogGroupName="m44"))
    except Exception:  # noqa: BLE001
        pass
    for fn in (lambda: ec2.delete_nat_gateway(NatGatewayId="nat-0"), lambda: ec2.delete_vpc_endpoints(VpcEndpointIds=["vpce-0"]),
               lambda: ec2.delete_flow_logs(FlowLogIds=["fl-0"])):
        try:
            fn()
        except Exception:  # noqa: BLE001
            pass
    try:
        ec2.delete_subnet(SubnetId=sub)
        ec2.delete_vpc(VpcId=vpc)
        ec2.delete_vpc(VpcId=peer)
    except Exception:  # noqa: BLE001
        pass


def unsupported_sqs(sqs, qurl) -> None:
    """AddPermission is an access-control surface CloudLabs does not use (fixed credentials)."""
    u("sqs", "AddPermission", lambda: sqs.add_permission(QueueUrl=qurl, Label="p",
                                                         AWSAccountIds=["123456789012"], Actions=["SendMessage"]))


# ------------------------------------------------------------------------------------------------ SQS
def sqs_suite(sqs) -> None:
    st: dict = {}
    name = f"m44-orders-{SUFFIX}"
    t("sqs", "CreateQueue(attrs)", lambda: st.update(qurl=sqs.create_queue(QueueName=name, Attributes={
        "VisibilityTimeout": "30", "MessageRetentionPeriod": "3600", "DelaySeconds": "0",
        "ReceiveMessageWaitTimeSeconds": "1"})["QueueUrl"]) or st["qurl"])
    t("sqs", "GetQueueUrl", lambda: sqs.get_queue_url(QueueName=name)["QueueUrl"] == st["qurl"] or 1 / 0)
    t("sqs", "ListQueues(prefix)", lambda: any(u.endswith(name) for u in sqs.list_queues(QueueNamePrefix=name)
                                               .get("QueueUrls", [])) or 1 / 0)
    t("sqs", "GetQueueAttributes", lambda: get_attrs(sqs, st))
    t("sqs", "SetQueueAttributes", lambda: set_attrs(sqs, st))
    t("sqs", "TagQueue/ListQueueTags", lambda: tag_queue(sqs, st))
    t("sqs", "UntagQueue", lambda: untag_queue(sqs, st))
    t("sqs", "SendMessage", lambda: st.update(mid=send_msg(sqs, st)) or st["mid"])
    t("sqs", "GetQueueAttributes(count)", lambda: approx_count(sqs, st))
    t("sqs", "ReceiveMessage", lambda: receive_msg(sqs, st, expect_body=True))
    t("sqs", "ChangeMessageVisibility", lambda: sqs.change_message_visibility(QueueUrl=st["qurl"],
        ReceiptHandle=st["receipt"], VisibilityTimeout=0))
    t("sqs", "ReceiveMessage(after visibility 0)", lambda: receive_msg(sqs, st, expect_body=True))
    t("sqs", "DeleteMessage", lambda: sqs.delete_message(QueueUrl=st["qurl"], ReceiptHandle=st["receipt"]))
    t("sqs", "ReceiveMessage(empty)", lambda: receive_empty(sqs, st))
    t("sqs", "SendMessageBatch", lambda: send_batch(sqs, st))
    t("sqs", "DeleteMessageBatch", lambda: delete_batch(sqs, st))
    unsupported_sqs(sqs, st["qurl"])
    t("sqs", "PurgeQueue", lambda: sqs.purge_queue(QueueUrl=st["qurl"]))
    t("sqs", "DeleteQueue", lambda: sqs.delete_queue(QueueUrl=st["qurl"]))
    t("sqs", "GetQueueUrl(after delete)", lambda: gone(sqs, name))
    t("sqs", "FIFO create/send/receive", lambda: fifo_roundtrip(sqs))


def get_attrs(sqs, st):
    a = sqs.get_queue_attributes(QueueUrl=st["qurl"], AttributeNames=["All"])["Attributes"]
    st["arn"] = a.get("QueueArn")
    return True if a.get("VisibilityTimeout") == "30" and a.get("QueueArn") else False


def set_attrs(sqs, st):
    sqs.set_queue_attributes(QueueUrl=st["qurl"], Attributes={"VisibilityTimeout": "45"})
    a = sqs.get_queue_attributes(QueueUrl=st["qurl"], AttributeNames=["VisibilityTimeout"])["Attributes"]
    return a.get("VisibilityTimeout") == "45"


def tag_queue(sqs, st):
    if not hasattr(sqs, "tag_queue"):
        return False
    sqs.tag_queue(QueueUrl=st["qurl"], Tags={"project": "cloudcafe"})
    tags = sqs.list_queue_tags(QueueUrl=st["qurl"]).get("Tags", {})
    return tags.get("project") == "cloudcafe"


def untag_queue(sqs, st):
    sqs.untag_queue(QueueUrl=st["qurl"], TagKeys=["project"])
    tags = sqs.list_queue_tags(QueueUrl=st["qurl"]).get("Tags", {})
    return "project" not in tags


def send_msg(sqs, st):
    r = sqs.send_message(QueueUrl=st["qurl"], MessageBody=json.dumps({"drink": "latte"}),
                         MessageAttributes={"project": {"DataType": "String", "StringValue": "cloudcafe"},
                                            "attempts": {"DataType": "Number", "StringValue": "2"}})
    return r["MessageId"]


def approx_count(sqs, st):
    a = sqs.get_queue_attributes(QueueUrl=st["qurl"],
                                 AttributeNames=["ApproximateNumberOfMessages"])["Attributes"]
    return int(a.get("ApproximateNumberOfMessages", "0")) >= 1


def receive_msg(sqs, st, expect_body: bool):
    r = sqs.receive_message(QueueUrl=st["qurl"], MaxNumberOfMessages=1, WaitTimeSeconds=1,
                            AttributeNames=["All"], MessageAttributeNames=["All"])
    msgs = r.get("Messages", [])
    if not msgs:
        return False
    m = msgs[0]
    st["receipt"] = m["ReceiptHandle"]
    if not expect_body:
        return True
    body = json.loads(m["Body"])
    attrs = m.get("MessageAttributes", {})
    return True if body.get("drink") == "latte" and attrs.get("project", {}).get("StringValue") == "cloudcafe" \
        else False


def receive_empty(sqs, st):
    r = sqs.receive_message(QueueUrl=st["qurl"], MaxNumberOfMessages=1, WaitTimeSeconds=1)
    return True if not r.get("Messages") else False


def send_batch(sqs, st):
    r = sqs.send_message_batch(QueueUrl=st["qurl"], Entries=[
        {"Id": "m1", "MessageBody": "batch-1"}, {"Id": "m2", "MessageBody": "batch-2"}])
    return len(r.get("Successful", [])) == 2


def delete_batch(sqs, st):
    handles = []
    for _ in range(2):
        r = sqs.receive_message(QueueUrl=st["qurl"], MaxNumberOfMessages=2, WaitTimeSeconds=1)
        handles += [{"Id": f"d{i}", "ReceiptHandle": m["ReceiptHandle"]}
                    for i, m in enumerate(r.get("Messages", []))]
    if len(handles) < 2:
        return False
    r = sqs.delete_message_batch(QueueUrl=st["qurl"], Entries=handles[:2])
    return len(r.get("Successful", [])) == 2


def gone(sqs, name):
    try:
        sqs.get_queue_url(QueueName=name)
        return False
    except ClientError as e:
        return e.response["Error"]["Code"] in ("AWS.SimpleQueueService.NonExistentQueue", "QueueDoesNotExist")


def fifo_roundtrip(sqs):
    name = f"m44-orders-{SUFFIX}.fifo"
    url = sqs.create_queue(QueueName=name, Attributes={"FifoQueue": "true",
                                                       "ContentBasedDeduplication": "true"})["QueueUrl"]
    sqs.send_message(QueueUrl=url, MessageBody="first", MessageGroupId="g1")
    sqs.send_message(QueueUrl=url, MessageBody="second", MessageGroupId="g1")
    got = []
    for _ in range(3):
        r = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=1, WaitTimeSeconds=1)
        for m in r.get("Messages", []):
            got.append(m["Body"])
            sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])
    sqs.delete_queue(QueueUrl=url)
    return got == ["first", "second"]


# ------------------------------------------------------------------------------------------------ SNS
def sns_suite(sns, sqs) -> None:
    st: dict = {}
    qname = f"m44-fanout-{SUFFIX}"
    st["qurl"] = sqs.create_queue(QueueName=qname)["QueueUrl"]
    st["qarn"] = sqs.get_queue_attributes(QueueUrl=st["qurl"], AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]

    t("sns", "CreateTopic", lambda: st.update(topic=sns.create_topic(Name=f"m44-orders-{SUFFIX}",
        Tags=[{"Key": "project", "Value": "cloudcafe"}])["TopicArn"]) or st["topic"])
    t("sns", "ListTopics", lambda: any(t2["TopicArn"] == st["topic"] for t2 in sns.list_topics()["Topics"]))
    observe("sns", "topic-tags", lambda: tag_observation(sns, st))
    t("sns", "GetTopicAttributes", lambda: get_topic_attrs(sns, st))
    t("sns", "SetTopicAttributes", lambda: set_topic_attrs(sns, st))
    t("sns", "Subscribe(sqs)", lambda: st.update(sub=subscribe(sns, st)) or st["sub"])
    t("sns", "ListSubscriptionsByTopic", lambda: any(s["SubscriptionArn"] == st["sub"]
        for s in sns.list_subscriptions_by_topic(TopicArn=st["topic"])["Subscriptions"]) or 1 / 0)
    t("sns", "GetSubscriptionAttributes", lambda: "SubscriptionArn" in sns.get_subscription_attributes(
        SubscriptionArn=st["sub"])["Attributes"] or 1 / 0)
    t("sns", "Publish", lambda: st.update(mid=sns.publish(TopicArn=st["topic"], Subject="m44",
        Message=json.dumps({"drink": "latte"}))["MessageId"]) or st["mid"])
    t("sns", "Publish→SQS delivery", lambda: delivered(sqs, st))
    t("sns", "RawMessageDelivery", lambda: raw_delivery(sns, sqs, st))
    t("sns", "PublishBatch", lambda: len(sns.publish_batch(TopicArn=st["topic"], PublishBatchRequestEntries=[
        {"Id": "p1", "Message": "batch-1"}, {"Id": "p2", "Message": "batch-2"}])["Successful"]) == 2)
    t("sns", "Http subscription (management only)", lambda: http_subscribe(sns))
    t("sns", "Unsubscribe", lambda: sns.unsubscribe(SubscriptionArn=st["sub"]))
    t("sns", "ListSubscriptionsByTopic(after unsubscribe)", lambda: no_subs(sns, st))
    t("sns", "DeleteTopic", lambda: sns.delete_topic(TopicArn=st["topic"]))
    t("sns", "Publish(after delete refused)", lambda: publish_gone(sns, st))
    sqs.delete_queue(QueueUrl=st["qurl"])


def get_topic_attrs(sns, st):
    a = sns.get_topic_attributes(TopicArn=st["topic"])["Attributes"]
    st["topic_arn_seen"] = a.get("TopicArn")
    return True if a.get("TopicArn") == st["topic"] else False


def set_topic_attrs(sns, st):
    sns.set_topic_attributes(TopicArn=st["topic"], AttributeName="DisplayName", AttributeValue="M44 Orders")
    a = sns.get_topic_attributes(TopicArn=st["topic"])["Attributes"]
    return a.get("DisplayName") == "M44 Orders"


def subscribe(sns, st):
    r = sns.subscribe(TopicArn=st["topic"], Protocol="sqs", Endpoint=st["qarn"], ReturnSubscriptionArn=True)
    return r["SubscriptionArn"]


def observe(service: str, name: str, fn) -> None:
    """Record behaviour that is interesting but outside the M44 contract scope."""
    try:
        print(f"OBSERVE {service} {name}: {fn()}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"OBSERVE {service} {name}: {type(e).__name__}: {str(e)[:80]}", flush=True)


def tag_observation(sns, st) -> str:
    """Topic tags: create-time tags, TagResource and UntagResource, engine by engine."""
    def tags():
        return {t2["Key"]: t2["Value"] for t2 in sns.list_tags_for_resource(ResourceArn=st["topic"])["Tags"]}
    created = tags()
    out = f"create-time={created or 'ignored'}"
    try:
        sns.tag_resource(ResourceArn=st["topic"], Tags=[{"Key": "course", "Value": "cs101"}])
        out += ", TagResource=ok" if tags().get("course") == "cs101" else ", TagResource=silently ignored"
    except Exception as e:  # noqa: BLE001
        return out + f", TagResource={type(e).__name__}"
    try:
        sns.untag_resource(ResourceArn=st["topic"], TagKeys=["course"])
        out += ", UntagResource=ok" if "course" not in tags() else ", UntagResource=silently ignored"
    except Exception as e:  # noqa: BLE001
        out += f", UntagResource={type(e).__name__}"
    return out


def delivered(sqs, st):
    def poll():
        r = sqs.receive_message(QueueUrl=st["qurl"], MaxNumberOfMessages=1, WaitTimeSeconds=1)
        return r.get("Messages")
    msgs = wait_for(poll, timeout=10)
    if not msgs:
        return False
    m = msgs[0]
    sqs.delete_message(QueueUrl=st["qurl"], ReceiptHandle=m["ReceiptHandle"])
    st["receipt2"] = m["ReceiptHandle"]
    try:
        env = json.loads(msgs[0]["Body"])
        return True if env.get("Type") == "Notification" and env.get("TopicArn") == st["topic"] \
            and json.loads(env.get("Message", "{}")).get("drink") == "latte" else False
    except Exception:  # noqa: BLE001
        return False


def raw_delivery(sns, sqs, st):
    sns.set_subscription_attributes(SubscriptionArn=st["sub"], AttributeName="RawMessageDelivery",
                                    AttributeValue="true")
    sns.publish(TopicArn=st["topic"], Message="raw-payload")
    def poll():
        r = sqs.receive_message(QueueUrl=st["qurl"], MaxNumberOfMessages=1, WaitTimeSeconds=1)
        return r.get("Messages")
    msgs = wait_for(poll, timeout=10)
    if not msgs:
        return False
    m = msgs[0]
    sqs.delete_message(QueueUrl=st["qurl"], ReceiptHandle=m["ReceiptHandle"])
    body = m["Body"]
    if body != "raw-payload":
        print(f"   raw delivery body was: {body[:120]}", flush=True)
        return False
    return True


def no_subs(sns, st):
    subs = sns.list_subscriptions_by_topic(TopicArn=st["topic"])["Subscriptions"]
    return True if not [s for s in subs if s["SubscriptionArn"] == st["sub"]] else False


def publish_gone(sns, st):
    try:
        sns.publish(TopicArn=st["topic"], Message="x")
        return False
    except ClientError:
        return True


def http_subscribe(sns):
    """Management only: the sandbox has no egress, so nothing is ever delivered to http endpoints."""
    arn = sns.create_topic(Name=f"m44-http-{SUFFIX}")["TopicArn"]
    try:
        sub = sns.subscribe(TopicArn=arn, Protocol="http", Endpoint="http://10.0.0.1/hook")["SubscriptionArn"]
        sns.unsubscribe(SubscriptionArn=sub)
        return True
    finally:
        sns.delete_topic(TopicArn=arn)


def main() -> None:
    ec2 = boto3.client("ec2", **KW)
    sqs = boto3.client("sqs", **KW)
    sns = boto3.client("sns", **KW)
    print(f"PROBE endpoint={EP} suffix={SUFFIX}")
    vpc_suite(ec2)
    sqs_suite(sqs)
    sns_suite(sns, sqs)
    print("\nSUMMARY")
    for svc in ("vpc", "sqs", "sns"):
        rows = [r for r in results if r[0] == svc]
        passed = sum(1 for r in rows if r[2] == "PASS")
        print(f"{svc}: {passed}/{len(rows)} PASS")
    fails = [r for r in results if r[2] != "PASS"]
    if fails:
        print("NOT PASS:")
        for svc, op, status, detail in fails:
            print(f"  {svc} {op} {status} {detail}")
    print("\nUNSUPPORTED CANDIDATES (probed, expected absent)")
    for svc, op, status, detail in unsupported:
        print(f"  {svc} {op} {status} {detail}")


if __name__ == "__main__":
    main()
