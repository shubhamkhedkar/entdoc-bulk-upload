"""EventBridge-triggered Lambda: ingest bucket 'Object Created' -> processed PDF.

Error handling contract
  * Bad input (not a PDF, encrypted, too big...) -> job marked FAILED, return normally
    (retrying cannot help, so no DLQ noise).
  * Anything unexpected -> job marked RETRYING and the exception is re-raised so the
    async invoke retries; after the retries are exhausted the event lands in the DLQ.
  * Duplicate deliveries are harmless: a job already PROCESSED is skipped.
"""
import logging
import os
import re
import time

import boto3
from botocore.exceptions import ClientError

import pdf_pipeline
from pdf_pipeline import PdfValidationError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

KEY_RE = re.compile(r"^uploads/([0-9a-f]{32})/([A-Za-z0-9._-]{1,128}\.pdf)$")
_cache = {}


def _region():
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-south-1"


def s3():
    if "s3" not in _cache:
        _cache["s3"] = boto3.client("s3", region_name=_region())
    return _cache["s3"]


def table():
    if "table" not in _cache:
        _cache["table"] = boto3.resource("dynamodb", region_name=_region()).Table(os.environ["JOBS_TABLE"])
    return _cache["table"]


def _update(job_id, status, extra=None, only_if_not_processed=False):
    values = {":s": status, ":u": int(time.time())}
    names = {"#s": "status"}
    sets = ["#s = :s", "updated_at = :u"]
    for i, (k, v) in enumerate((extra or {}).items()):
        sets.append(f"#a{i} = :v{i}")  # placeholders: e.g. "error" is a DynamoDB reserved word
        names[f"#a{i}"] = k
        values[f":v{i}"] = v
    cond = "attribute_exists(job_id)"
    if only_if_not_processed:
        cond += " AND #s <> :done"
        values[":done"] = "PROCESSED"
    table().update_item(
        Key={"job_id": job_id},
        UpdateExpression="SET " + ", ".join(sets),
        ConditionExpression=cond,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def handler(event, context):
    detail = event.get("detail") or {}
    bucket = (detail.get("bucket") or {}).get("name")
    key = (detail.get("object") or {}).get("key", "")

    if bucket != os.environ["INGEST_BUCKET"]:
        logger.warning("ignoring event from unexpected bucket %s", bucket)
        return {"skipped": "unexpected bucket"}
    match = KEY_RE.match(key)  # EventBridge delivers the raw (not URL-encoded) key
    if not match:
        logger.warning("ignoring unexpected key %s", key)
        return {"skipped": "unexpected key"}
    job_id, filename = match.groups()

    try:
        _update(job_id, "PROCESSING", {"started_at": int(time.time())}, only_if_not_processed=True)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.info("job %s unknown or already processed; skipping", job_id)
            return {"skipped": "unknown or already processed"}
        raise

    max_bytes = int(os.environ.get("MAX_FILE_BYTES", str(50 * 1024 * 1024)))
    try:
        obj = s3().get_object(Bucket=bucket, Key=key)
        if obj["ContentLength"] > max_bytes:
            raise PdfValidationError(f"file is larger than {max_bytes // (1024 * 1024)} MB")
        result = pdf_pipeline.process_pdf(
            obj["Body"].read(),
            max_bytes=max_bytes,
            max_pages=int(os.environ.get("MAX_PAGES", "500")),
            image_quality=int(os.environ.get("IMAGE_QUALITY", "70")),
        )
        out_key = f"processed/{job_id}/{filename}"
        s3().put_object(
            Bucket=os.environ["OUTPUT_BUCKET"],
            Key=out_key,
            Body=result.data,
            ContentType="application/pdf",
            ServerSideEncryption="AES256",
            Metadata={"job-id": job_id},
        )
        _update(
            job_id,
            "PROCESSED",
            {
                "output_key": out_key,
                "pages": result.pages,
                "input_bytes": result.input_bytes,
                "output_bytes": result.output_bytes,
                "finished_at": int(time.time()),
            },
        )
        logger.info("job %s processed: %d pages, %d -> %d bytes", job_id, result.pages, result.input_bytes, result.output_bytes)
        return {"job_id": job_id, "status": "PROCESSED"}
    except PdfValidationError as exc:
        logger.warning("job %s rejected: %s", job_id, exc)
        _update(job_id, "FAILED", {"error": str(exc)[:500], "finished_at": int(time.time())})
        return {"job_id": job_id, "status": "FAILED"}
    except Exception as exc:
        logger.exception("job %s failed unexpectedly", job_id)
        try:
            _update(job_id, "RETRYING", {"error": f"{type(exc).__name__}: {str(exc)[:300]}"})
        except Exception:  # never mask the original error
            logger.exception("could not record RETRYING state")
        raise
