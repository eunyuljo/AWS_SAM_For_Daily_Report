import logging

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel("INFO")


def _public_access_blocked(s3, bucket):
    try:
        cfg = s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
        return all(
            cfg.get(k, False)
            for k in (
                "BlockPublicAcls",
                "IgnorePublicAcls",
                "BlockPublicPolicy",
                "RestrictPublicBuckets",
            )
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchPublicAccessBlockConfiguration":
            return False
        return None


def _has_default_encryption(s3, bucket):
    try:
        s3.get_bucket_encryption(Bucket=bucket)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ServerSideEncryptionConfigurationNotFoundError":
            return False
        return None


def handler(event, context):
    s3 = boto3.client("s3")

    buckets = [b["Name"] for b in s3.list_buckets()["Buckets"]]

    no_public_block = []
    no_encryption = []
    inspect_errors = []

    for name in buckets:
        pab = _public_access_blocked(s3, name)
        if pab is False:
            no_public_block.append(name)
        elif pab is None:
            inspect_errors.append({"bucket": name, "check": "public_access_block"})

        enc = _has_default_encryption(s3, name)
        if enc is False:
            no_encryption.append(name)
        elif enc is None:
            inspect_errors.append({"bucket": name, "check": "encryption"})

    return {
        "section": "s3_hygiene",
        "total_buckets": len(buckets),
        "without_public_access_block": no_public_block,
        "without_default_encryption": no_encryption,
        "inspect_errors": inspect_errors,
    }
