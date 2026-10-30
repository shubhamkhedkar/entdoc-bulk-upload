import json
import re

import presign
from conftest import INGEST, api_event


def call(body):
    resp = presign.handler(api_event(body), None)
    return resp["statusCode"], json.loads(resp["body"])


def test_presigned_posts_and_job_records(aws):
    code, body = call({"files": [{"name": "Q3 Report (final).PDF", "size": 2048}, {"name": "b.pdf", "size": 10}]})
    assert code == 200 and len(body["uploads"]) == 2 and body["rejected"] == []
    first = body["uploads"][0]
    assert re.fullmatch(r"[0-9a-f]{32}", first["job_id"])
    assert INGEST in first["url"] and "ap-south-1" in first["url"]
    fields = first["fields"]
    assert re.fullmatch(r"uploads/[0-9a-f]{32}/Q3_Report_final.pdf", fields["key"])
    assert fields["Content-Type"] == "application/pdf" and "policy" in fields and "x-amz-signature" in fields
    item = aws["table"].get_item(Key={"job_id": first["job_id"]})["Item"]
    assert item["status"] == "AWAITING_UPLOAD" and item["original_name"] == "Q3 Report (final).PDF"
    assert item["input_key"] == fields["key"] and item["expires_at"] > item["created_at"]


def test_policy_limits_size_and_content_type(aws):
    import base64

    _, body = call({"files": [{"name": "a.pdf", "size": 5}]})
    policy = json.loads(base64.b64decode(body["uploads"][0]["fields"]["policy"]))
    conditions = policy["conditions"]
    assert ["content-length-range", 1, presign.MAX_BYTES] in conditions
    assert {"Content-Type": "application/pdf"} in conditions


def test_rejections(aws):
    big = presign.MAX_BYTES + 1
    code, body = call(
        {"files": [{"name": "notes.txt", "size": 5}, {"name": "big.pdf", "size": big}, {"name": "z.pdf", "size": 0}, {"name": "ok.pdf", "size": 9}, "oops"]}
    )
    assert code == 200
    assert [r["index"] for r in body["rejected"]] == [0, 1, 2, 4]
    assert [u["index"] for u in body["uploads"]] == [3]
    assert aws["table"].scan()["Count"] == 1


def test_bad_requests(aws):
    assert call({"files": []})[0] == 400
    assert call({"nope": 1})[0] == 400
    assert call({"files": [{"name": f"{i}.pdf", "size": 1} for i in range(presign.MAX_FILES + 1)]})[0] == 400
    assert presign.handler({"body": "{not json"}, None)["statusCode"] == 400


def test_safe_filename_blocks_path_tricks():
    assert presign.safe_filename("../../etc/passwd.pdf") == "passwd.pdf"
    assert presign.safe_filename("..\\..\\x y.pdf") == "x_y.pdf"
    assert presign.safe_filename("日本語.pdf") == "document.pdf"
    assert presign.safe_filename("a.PDF").endswith(".pdf")
