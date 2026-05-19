import csv
import io
import logging
import time
from datetime import datetime, timedelta, timezone

import boto3

logger = logging.getLogger()
logger.setLevel("INFO")

STALE_KEY_DAYS = 90


def _get_credential_report(iam):
    for _ in range(20):
        try:
            return iam.get_credential_report()["Content"].decode("utf-8")
        except iam.exceptions.CredentialReportNotPresentException:
            iam.generate_credential_report()
        except iam.exceptions.CredentialReportExpiredException:
            iam.generate_credential_report()
        except iam.exceptions.CredentialReportNotReadyException:
            pass
        time.sleep(2)
    raise RuntimeError("credential report not ready")


def _to_dt(value):
    if not value or value in ("N/A", "no_information", "not_supported"):
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def handler(event, context):
    iam = boto3.client("iam")
    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(days=STALE_KEY_DAYS)

    report_csv = _get_credential_report(iam)
    rows = list(csv.DictReader(io.StringIO(report_csv)))

    root_row = next((r for r in rows if r["user"] == "<root_account>"), {})
    root_findings = {
        "mfa_enabled": root_row.get("mfa_active") == "true",
        "access_key_1_active": root_row.get("access_key_1_active") == "true",
        "access_key_2_active": root_row.get("access_key_2_active") == "true",
        "last_used": root_row.get("password_last_used")
        if root_row.get("password_last_used") not in ("no_information", "N/A")
        else None,
    }

    users_no_mfa = []
    stale_keys = []
    for r in rows:
        if r["user"] == "<root_account>":
            continue
        if r.get("password_enabled") == "true" and r.get("mfa_active") != "true":
            users_no_mfa.append(r["user"])
        for n in ("1", "2"):
            if r.get(f"access_key_{n}_active") != "true":
                continue
            last_used = _to_dt(r.get(f"access_key_{n}_last_used_date"))
            rotated = _to_dt(r.get(f"access_key_{n}_last_rotated"))
            reference = last_used or rotated
            if reference and reference < stale_threshold:
                stale_keys.append(
                    {
                        "user": r["user"],
                        "key_index": int(n),
                        "last_used": last_used.isoformat() if last_used else None,
                        "last_rotated": rotated.isoformat() if rotated else None,
                    }
                )

    return {
        "section": "iam_hygiene",
        "root": root_findings,
        "users_console_no_mfa": users_no_mfa,
        "stale_access_keys": stale_keys,
        "stale_threshold_days": STALE_KEY_DAYS,
    }
