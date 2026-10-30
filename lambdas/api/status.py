"""GET /jobs/{job_id} and GET /jobs?ids=a,b,c - job status + download links."""
import logging
import os
import re

from common import JOB_ID_RE, ddb, response, s3_client, table

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DOWNLOAD_TTL = int(os.environ.get("DOWNLOAD_URL_TTL_SECONDS", "900"))
MAX_IDS = 50


def _public_view(item):
    out = {
        "job_id": item["job_id"],
        "status": item["status"],
        "original_name": item.get("original_name"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }
    if item.get("error"):
        out["error"] = item["error"]
    if item["status"] == "PROCESSED" and item.get("output_key"):
        url = s3_client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": os.environ["OUTPUT_BUCKET"],
                "Key": item["output_key"],
                "ResponseContentDisposition": 'attachment; filename="%s"' % item["output_key"].rsplit("/", 1)[-1],
            },
            ExpiresIn=DOWNLOAD_TTL,
        )
        in_b, out_b = item.get("input_bytes"), item.get("output_bytes")
        reduction = round((1 - out_b / in_b) * 100, 1) if in_b and out_b is not None else None
        out["result"] = {
            "pages": item.get("pages"),
            "input_bytes": in_b,
            "output_bytes": out_b,
            "reduction_pct": reduction,
            "download_url": url,
            "download_expires_in": DOWNLOAD_TTL,
        }
    return out


def handler(event, context):
    path_params = event.get("pathParameters") or {}
    if "job_id" in path_params:
        job_id = path_params["job_id"]
        if not re.match(JOB_ID_RE, job_id):
            return response(400, {"error": "invalid job id"})
        item = table().get_item(Key={"job_id": job_id}).get("Item")
        if not item:
            return response(404, {"error": "job not found"})
        return response(200, _public_view(item))

    raw = (event.get("queryStringParameters") or {}).get("ids", "")
    ids = [i for i in dict.fromkeys(raw.split(",")) if i]
    if not ids:
        return response(400, {"error": "provide ?ids=<job_id>,<job_id>"})
    if len(ids) > MAX_IDS:
        return response(400, {"error": f"at most {MAX_IDS} ids per request"})
    if not all(re.match(JOB_ID_RE, i) for i in ids):
        return response(400, {"error": "invalid job id"})

    name = os.environ["JOBS_TABLE"]
    result = ddb().batch_get_item(RequestItems={name: {"Keys": [{"job_id": i} for i in ids]}})
    items = {i["job_id"]: i for i in result["Responses"].get(name, [])}
    # Unprocessed keys (throttling) are simply omitted; the client polls again.
    return response(200, {"jobs": [_public_view(items[i]) for i in ids if i in items]})
