import json

import status
from conftest import OUTPUT, api_event

JOB = "a" * 32
JOB2 = "b" * 32


def seed(aws, job_id, **kw):
    item = {"job_id": job_id, "status": "AWAITING_UPLOAD", "original_name": "x.pdf", "created_at": 1, "updated_at": 2}
    item.update(kw)
    aws["table"].put_item(Item=item)


def get(event):
    resp = status.handler(event, None)
    return resp["statusCode"], json.loads(resp["body"])


def test_single_job_pending(aws):
    seed(aws, JOB)
    code, body = get(api_event(path_params={"job_id": JOB}))
    assert code == 200 and body["status"] == "AWAITING_UPLOAD" and "result" not in body
    assert "input_key" not in body  # internal fields are not exposed


def test_processed_job_has_presigned_download(aws):
    seed(aws, JOB, status="PROCESSED", output_key=f"processed/{JOB}/x.pdf", pages=3, input_bytes=1000, output_bytes=400)
    code, body = get(api_event(path_params={"job_id": JOB}))
    assert code == 200
    r = body["result"]
    assert r["pages"] == 3 and r["reduction_pct"] == 60.0
    assert OUTPUT in r["download_url"] and "X-Amz-Signature" in r["download_url"]


def test_failed_job_exposes_error(aws):
    seed(aws, JOB, status="FAILED", error="PDF is password-protected")
    _, body = get(api_event(path_params={"job_id": JOB}))
    assert body["status"] == "FAILED" and "password" in body["error"]


def test_not_found_and_invalid_ids(aws):
    assert get(api_event(path_params={"job_id": "c" * 32}))[0] == 404
    assert get(api_event(path_params={"job_id": "../etc"}))[0] == 400
    assert get(api_event(query={"ids": "nope"}))[0] == 400
    assert get(api_event())[0] == 400
    assert get(api_event(query={"ids": ",".join(f"{i:032x}" for i in range(51))}))[0] == 400


def test_batch_lookup_keeps_order_and_skips_missing(aws):
    seed(aws, JOB)
    seed(aws, JOB2, status="PROCESSING")
    code, body = get(api_event(query={"ids": f"{JOB2},{'c' * 32},{JOB},{JOB2}"}))
    assert code == 200
    assert [j["job_id"] for j in body["jobs"]] == [JOB2, JOB]
