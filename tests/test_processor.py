import json

import pytest

import pdf_pipeline
import presign
import processor
import status
from conftest import INGEST, OUTPUT, api_event, s3_created_event


def stage_upload(aws, data, name="doc.pdf", size_declared=None):
    """Create the job via the presign Lambda, then 'upload' straight into the bucket."""
    resp = presign.handler(api_event({"files": [{"name": name, "size": size_declared or len(data) or 1}]}), None)
    up = json.loads(resp["body"])["uploads"][0]
    aws["s3"].put_object(Bucket=INGEST, Key=up["fields"]["key"], Body=data)
    return up["job_id"], up["fields"]["key"]


def job(aws, job_id):
    return aws["table"].get_item(Key={"job_id": job_id})["Item"]


def test_happy_path(aws, pdf_factory):
    data = pdf_factory(pages=[(612, 792), (842, 1191)], image=True)
    job_id, key = stage_upload(aws, data)
    out = processor.handler(s3_created_event(key), None)
    assert out == {"job_id": job_id, "status": "PROCESSED"}
    item = job(aws, job_id)
    assert item["status"] == "PROCESSED" and item["pages"] == 2
    obj = aws["s3"].get_object(Bucket=OUTPUT, Key=item["output_key"])
    assert obj["ContentType"] == "application/pdf" and obj["ServerSideEncryption"] == "AES256"
    assert obj["ContentLength"] == item["output_bytes"] < item["input_bytes"]


def test_invalid_pdf_marks_failed_without_raising(aws):
    job_id, key = stage_upload(aws, b"this is not a pdf")
    assert processor.handler(s3_created_event(key), None)["status"] == "FAILED"
    item = job(aws, job_id)
    assert item["status"] == "FAILED" and "PDF" in item["error"]
    assert "Contents" not in aws["s3"].list_objects_v2(Bucket=OUTPUT)


def test_unexpected_error_marks_retrying_and_raises(aws, pdf_factory, monkeypatch):
    job_id, key = stage_upload(aws, pdf_factory())

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(pdf_pipeline, "process_pdf", boom)
    with pytest.raises(RuntimeError):
        processor.handler(s3_created_event(key), None)
    item = job(aws, job_id)
    assert item["status"] == "RETRYING" and "kaboom" in item["error"]


def test_retry_after_failure_succeeds(aws, pdf_factory, monkeypatch):
    job_id, key = stage_upload(aws, pdf_factory())
    with monkeypatch.context() as m:
        m.setattr(pdf_pipeline, "process_pdf", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
        with pytest.raises(RuntimeError):
            processor.handler(s3_created_event(key), None)
    assert processor.handler(s3_created_event(key), None)["status"] == "PROCESSED"


def test_duplicate_event_is_idempotent(aws, pdf_factory):
    job_id, key = stage_upload(aws, pdf_factory())
    processor.handler(s3_created_event(key), None)
    first = job(aws, job_id)["finished_at"]
    assert processor.handler(s3_created_event(key), None) == {"skipped": "unknown or already processed"}
    assert job(aws, job_id)["finished_at"] == first


@pytest.mark.parametrize(
    "event",
    [
        s3_created_event("uploads/" + "d" * 32 + "/ghost.pdf"),  # no job record
        s3_created_event("random/file.pdf"),
        s3_created_event("uploads/" + "d" * 32 + "/x.pdf", bucket="someone-elses-bucket"),
        {},
    ],
)
def test_unknown_events_are_ignored(aws, event):
    assert "skipped" in processor.handler(event, None)
    assert aws["table"].scan()["Count"] == 0


def test_oversized_object_rejected(aws, pdf_factory, monkeypatch):
    monkeypatch.setenv("MAX_FILE_BYTES", "200")
    job_id, key = stage_upload(aws, pdf_factory(), size_declared=100)
    assert processor.handler(s3_created_event(key), None)["status"] == "FAILED"
    assert "larger" in job(aws, job_id)["error"]


def test_end_to_end_batch_with_status_api(aws, pdf_factory):
    inputs = {"good.pdf": pdf_factory(), "bad.pdf": b"%PDF-1.4 nope", "also-good.pdf": pdf_factory(pages=[(300, 400)] * 2)}
    ids = {}
    for name, data in inputs.items():
        ids[name], key = stage_upload(aws, data, name=name)
        processor.handler(s3_created_event(key), None)

    resp = status.handler(api_event(query={"ids": ",".join(ids.values())}), None)
    jobs = {j["original_name"]: j for j in json.loads(resp["body"])["jobs"]}
    assert jobs["good.pdf"]["status"] == "PROCESSED" and jobs["also-good.pdf"]["result"]["pages"] == 2
    assert jobs["bad.pdf"]["status"] == "FAILED"
    assert "download_url" in jobs["good.pdf"]["result"]
