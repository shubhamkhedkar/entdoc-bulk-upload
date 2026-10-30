"""POST /uploads - create job records and return presigned S3 POST forms.

Request:  {"files": [{"name": "a.pdf", "size": 12345}, ...]}
Response: {"uploads": [{"index", "job_id", "url", "fields", "original_name"}],
           "rejected": [{"index", "name", "reason"}]}
"""
import logging
import os
import re
import time
import uuid

from common import parse_json_body, response, s3_client, table

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MAX_FILES = int(os.environ.get("MAX_FILES_PER_REQUEST", "25"))
MAX_BYTES = int(os.environ.get("MAX_FILE_BYTES", str(50 * 1024 * 1024)))
URL_TTL = int(os.environ.get("UPLOAD_URL_TTL_SECONDS", "900"))
JOB_TTL_DAYS = int(os.environ.get("JOB_TTL_DAYS", "30"))


def safe_filename(name: str) -> str:
    """Return an S3-key-safe name that always ends in lowercase '.pdf'."""
    base = os.path.basename(name.replace("\\", "/"))
    stem = re.sub(r"\.pdf$", "", base, flags=re.IGNORECASE)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "document"
    return stem[:100] + ".pdf"


def handler(event, context):
    try:
        body = parse_json_body(event)
    except ValueError as exc:
        return response(400, {"error": str(exc)})

    files = body.get("files") if isinstance(body, dict) else None
    if not isinstance(files, list) or not files:
        return response(400, {"error": "'files' must be a non-empty list"})
    if len(files) > MAX_FILES:
        return response(400, {"error": f"at most {MAX_FILES} files per request"})

    bucket = os.environ["INGEST_BUCKET"]
    s3, tbl = s3_client(), table()
    now = int(time.time())
    uploads, rejected = [], []

    for index, f in enumerate(files):
        name = f.get("name") if isinstance(f, dict) else None
        size = f.get("size") if isinstance(f, dict) else None
        if not isinstance(name, str) or not name.lower().endswith(".pdf"):
            rejected.append({"index": index, "name": str(name), "reason": "only .pdf files are accepted"})
            continue
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            rejected.append({"index": index, "name": name, "reason": "size must be a positive integer"})
            continue
        if size > MAX_BYTES:
            rejected.append({"index": index, "name": name, "reason": f"file exceeds {MAX_BYTES // (1024 * 1024)} MB limit"})
            continue

        job_id = uuid.uuid4().hex
        key = f"uploads/{job_id}/{safe_filename(name)}"
        post = s3.generate_presigned_post(
            Bucket=bucket,
            Key=key,
            Fields={"Content-Type": "application/pdf"},
            Conditions=[
                {"Content-Type": "application/pdf"},
                ["content-length-range", 1, MAX_BYTES],
            ],
            ExpiresIn=URL_TTL,
        )
        tbl.put_item(
            Item={
                "job_id": job_id,
                "status": "AWAITING_UPLOAD",
                "original_name": name[:255],
                "input_key": key,
                "declared_size": size,
                "created_at": now,
                "updated_at": now,
                "expires_at": now + JOB_TTL_DAYS * 86400,
            }
        )
        uploads.append(
            {"index": index, "job_id": job_id, "url": post["url"], "fields": post["fields"], "original_name": name}
        )

    logger.info("presigned %d uploads, rejected %d", len(uploads), len(rejected))
    return response(200, {"uploads": uploads, "rejected": rejected, "expires_in": URL_TTL})
