import logging
from datetime import datetime, timedelta, timezone

import boto3

logger = logging.getLogger()
logger.setLevel("INFO")

RISK_EVENTS = [
    "ConsoleLogin",
    "AuthorizeSecurityGroupIngress",
    "CreateUser",
    "CreateAccessKey",
    "PutUserPolicy",
    "AttachUserPolicy",
    "AttachRolePolicy",
    "PutBucketPolicy",
    "DeleteTrail",
    "StopLogging",
    "DisableKey",
]


def _is_open_sg_change(event):
    return any(
        cidr in event.get("CloudTrailEvent", "")
        for cidr in ('"CidrIp": "0.0.0.0/0"', '"CidrIpv6": "::/0"')
    )


def handler(event, context):
    region = event.get("region")
    ct = boto3.client("cloudtrail", region_name=region) if region else boto3.client("cloudtrail")
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=24)

    findings = []
    for name in RISK_EVENTS:
        paginator = ct.get_paginator("lookup_events")
        for page in paginator.paginate(
            StartTime=start,
            EndTime=now,
            LookupAttributes=[{"AttributeKey": "EventName", "AttributeValue": name}],
            PaginationConfig={"MaxItems": 50},
        ):
            for ev in page.get("Events", []):
                if name == "ConsoleLogin":
                    is_root = ev.get("Username") == "Root" or "<root_account>" in (
                        ev.get("Username") or ""
                    )
                    if not is_root:
                        continue
                if name == "AuthorizeSecurityGroupIngress" and not _is_open_sg_change(ev):
                    continue
                findings.append(
                    {
                        "event_name": ev["EventName"],
                        "time": ev["EventTime"].isoformat(),
                        "user": ev.get("Username"),
                        "source": ev.get("EventSource"),
                        "resources": [r.get("ResourceName") for r in ev.get("Resources", [])],
                    }
                )

    findings.sort(key=lambda f: f["time"], reverse=True)

    return {
        "section": "cloudtrail_risk",
        "window_hours": 24,
        "count": len(findings),
        "findings": findings,
    }
