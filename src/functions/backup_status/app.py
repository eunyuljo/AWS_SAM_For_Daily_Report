import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel("INFO")

WINDOW_HOURS = 24


def _list_backup_jobs(backup, since):
    jobs = []
    paginator = backup.get_paginator("list_backup_jobs")
    for page in paginator.paginate(ByCreatedAfter=since):
        for j in page.get("BackupJobs", []):
            jobs.append(
                {
                    "job_id": j.get("BackupJobId"),
                    "state": j.get("State"),
                    "resource_arn": j.get("ResourceArn"),
                    "resource_type": j.get("ResourceType"),
                    "vault": j.get("BackupVaultName"),
                    "created": j["CreationDate"].isoformat() if j.get("CreationDate") else None,
                    "completed": j["CompletionDate"].isoformat()
                    if j.get("CompletionDate")
                    else None,
                    "status_message": (j.get("StatusMessage") or "")[:200],
                    "bytes": j.get("BackupSizeInBytes", 0),
                }
            )
    return jobs


def _list_protected(backup):
    items = []
    paginator = backup.get_paginator("list_protected_resources")
    for page in paginator.paginate():
        for r in page.get("Results", []):
            items.append(
                {
                    "type": r.get("ResourceType"),
                    "arn": r.get("ResourceArn"),
                    "last_backup": r["LastBackupTime"].isoformat()
                    if r.get("LastBackupTime")
                    else None,
                }
            )
    return items


def handler(event, context):
    backup = boto3.client("backup")
    since = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)

    try:
        jobs = _list_backup_jobs(backup, since)
        protected = _list_protected(backup)
        enabled = True
        error = None
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("AccessDeniedException", "ResourceNotFoundException"):
            jobs, protected, enabled, error = [], [], False, code
        else:
            raise

    state_counts = Counter(j["state"] for j in jobs)
    by_type = Counter(j["resource_type"] for j in jobs if j.get("resource_type"))
    failed = [j for j in jobs if j["state"] in ("FAILED", "ABORTED", "EXPIRED")]
    failed.sort(key=lambda j: j.get("completed") or "", reverse=True)

    protected_by_type = Counter(p["type"] for p in protected if p.get("type"))

    return {
        "section": "backup_status",
        "enabled": enabled,
        "error": error,
        "window_hours": WINDOW_HOURS,
        "jobs": {
            "total": len(jobs),
            "by_state": dict(state_counts),
            "by_resource_type": dict(by_type),
            "failed": failed[:20],
        },
        "protected": {
            "total": len(protected),
            "by_type": dict(protected_by_type),
            "items": protected[:50],
        },
    }
