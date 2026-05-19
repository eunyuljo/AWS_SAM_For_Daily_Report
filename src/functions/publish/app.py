import logging
import os

import boto3
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel("INFO")

BUCKET = os.environ["REPORTS_BUCKET"]
URL_TTL = int(os.environ.get("PRESIGNED_URL_TTL", "604800"))
REGION = os.environ["AWS_REGION"]


def handler(event, context):
    date = event["date"]
    html_body = event["html"]
    json_body = event.get("json")

    s3 = boto3.client(
        "s3",
        region_name=REGION,
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
    )

    html_key = f"reports/{date}.html"
    s3.put_object(
        Bucket=BUCKET,
        Key=html_key,
        Body=html_body.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
        ServerSideEncryption="AES256",
    )

    json_key = None
    if json_body:
        json_key = f"reports/{date}.json"
        s3.put_object(
            Bucket=BUCKET,
            Key=json_key,
            Body=json_body.encode("utf-8"),
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )

    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET, "Key": html_key},
        ExpiresIn=URL_TTL,
    )
    return {
        "bucket": BUCKET,
        "html_key": html_key,
        "json_key": json_key,
        "url": url,
        "ttl_seconds": URL_TTL,
    }
