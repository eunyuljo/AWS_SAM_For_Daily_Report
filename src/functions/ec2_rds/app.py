import logging
from collections import Counter

import boto3

logger = logging.getLogger()
logger.setLevel("INFO")


def handler(event, context):
    region = event.get("region")
    ec2 = boto3.client("ec2", region_name=region) if region else boto3.client("ec2")
    rds = boto3.client("rds", region_name=region) if region else boto3.client("rds")

    instances = []
    for page in ec2.get_paginator("describe_instances").paginate():
        for r in page["Reservations"]:
            for i in r["Instances"]:
                instances.append(
                    {
                        "id": i["InstanceId"],
                        "type": i["InstanceType"],
                        "state": i["State"]["Name"],
                        "az": i.get("Placement", {}).get("AvailabilityZone"),
                        "name": next(
                            (t["Value"] for t in i.get("Tags", []) if t["Key"] == "Name"),
                            "",
                        ),
                    }
                )

    state_counts = Counter(i["state"] for i in instances)
    type_counts = Counter(i["type"] for i in instances)

    unattached_volumes = []
    for page in ec2.get_paginator("describe_volumes").paginate(
        Filters=[{"Name": "status", "Values": ["available"]}]
    ):
        for v in page["Volumes"]:
            unattached_volumes.append(
                {"id": v["VolumeId"], "size": v["Size"], "type": v["VolumeType"]}
            )

    eips = ec2.describe_addresses()["Addresses"]
    unassociated_eips = [e["PublicIp"] for e in eips if "AssociationId" not in e]

    rds_instances = []
    for page in rds.get_paginator("describe_db_instances").paginate():
        for db in page["DBInstances"]:
            rds_instances.append(
                {
                    "id": db["DBInstanceIdentifier"],
                    "engine": f"{db['Engine']} {db.get('EngineVersion', '')}",
                    "class": db["DBInstanceClass"],
                    "status": db["DBInstanceStatus"],
                    "multi_az": db["MultiAZ"],
                }
            )

    return {
        "section": "ec2_rds",
        "ec2": {
            "total": len(instances),
            "by_state": dict(state_counts),
            "by_type": dict(type_counts),
            "instances": instances,
        },
        "rds": {
            "total": len(rds_instances),
            "instances": rds_instances,
        },
        "waste": {
            "unattached_volumes": unattached_volumes,
            "unattached_volume_size_gb": sum(v["size"] for v in unattached_volumes),
            "unassociated_eips": unassociated_eips,
        },
    }
