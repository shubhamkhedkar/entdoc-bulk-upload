"""Shared helpers for the API Lambdas (presign + status)."""
import decimal
import json
import os

import boto3
from botocore.config import Config

_cache = {}

JOB_ID_RE = r"^[0-9a-f]{32}$"


def region():
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-south-1"


def s3_client():
    # SigV4 + virtual-hosted style is required for presigned POST/GET in ap-south-1.
    if "s3" not in _cache:
        _cache["s3"] = boto3.client(
            "s3",
            region_name=region(),
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        )
    return _cache["s3"]


def ddb():
    if "ddb" not in _cache:
        _cache["ddb"] = boto3.resource("dynamodb", region_name=region())
    return _cache["ddb"]


def table():
    return ddb().Table(os.environ["JOBS_TABLE"])


class _Encoder(json.JSONEncoder):
    def default(self, o):  # DynamoDB returns Decimal
        if isinstance(o, decimal.Decimal):
            return int(o) if o == o.to_integral_value() else float(o)
        return super().default(o)


def response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
        "body": json.dumps(body, cls=_Encoder),
    }


def parse_json_body(event):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        import base64

        raw = base64.b64decode(raw).decode("utf-8", "replace")
    if len(raw) > 256 * 1024:
        raise ValueError("request body too large")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("body must be valid JSON") from exc
