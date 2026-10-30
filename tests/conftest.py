import io
import json
import os

import boto3
import pytest
from moto import mock_aws

REGION = "ap-south-1"
ACCOUNT = "123456789012"
INGEST = f"entdoc-prod-pdf-ingest-{ACCOUNT}"
OUTPUT = f"entdoc-prod-pdf-processed-{ACCOUNT}"
TABLE = "entdoc-prod-pdf-jobs"


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    for k, v in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": REGION,
        "AWS_REGION": REGION,
        "INGEST_BUCKET": INGEST,
        "OUTPUT_BUCKET": OUTPUT,
        "JOBS_TABLE": TABLE,
    }.items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def aws(aws_env):
    """Mocked ingest/output buckets and jobs table; fresh client caches per test."""
    import common
    import processor

    with mock_aws():
        common._cache.clear()
        processor._cache.clear()
        s3 = boto3.client("s3", region_name=REGION)
        for b in (INGEST, OUTPUT):
            s3.create_bucket(Bucket=b, CreateBucketConfiguration={"LocationConstraint": REGION})
        ddb = boto3.resource("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "job_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield {"s3": s3, "table": ddb.Table(TABLE)}
        common._cache.clear()
        processor._cache.clear()


def api_event(body=None, path_params=None, query=None):
    return {
        "version": "2.0",
        "body": json.dumps(body) if body is not None else None,
        "pathParameters": path_params,
        "queryStringParameters": query,
        "isBase64Encoded": False,
    }


def s3_created_event(key, bucket=INGEST, size=1000):
    return {
        "version": "0",
        "detail-type": "Object Created",
        "source": "aws.s3",
        "detail": {"bucket": {"name": bucket}, "object": {"key": key, "size": size}},
    }


def make_pdf(pages=((612, 792),), title="Secret Title", author="Jane Doe", image=False, text="Hello EntDoc"):
    """Build a PDF with reportlab (page sizes in points)."""
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=pages[0])
    c.setTitle(title)
    c.setAuthor(author)
    for i, size in enumerate(pages):
        c.setPageSize(size)
        c.drawString(72, 72, f"{text} page {i + 1}")
        if image:
            from PIL import Image
            from reportlab.lib.utils import ImageReader

            img = Image.effect_noise((600, 600), 80).convert("RGB")
            c.drawImage(ImageReader(img), 50, 150, width=300, height=300)
        c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture
def pdf_factory():
    return make_pdf
