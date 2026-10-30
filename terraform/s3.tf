# ---------------------------------------------------------------- buckets
resource "aws_s3_bucket" "ingest" {
  bucket        = local.ingest_bucket_name
  force_destroy = var.force_destroy_buckets
}

resource "aws_s3_bucket" "processed" {
  bucket        = local.processed_bucket_name
  force_destroy = var.force_destroy_buckets
}

resource "aws_s3_bucket" "web" {
  bucket        = local.web_bucket_name
  force_destroy = var.force_destroy_buckets
}

locals {
  all_buckets = {
    ingest    = aws_s3_bucket.ingest.id
    processed = aws_s3_bucket.processed.id
    web       = aws_s3_bucket.web.id
  }
}

resource "aws_s3_bucket_public_access_block" "all" {
  for_each                = local.all_buckets
  bucket                  = each.value
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "all" {
  for_each = local.all_buckets
  bucket   = each.value
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "all" {
  for_each = local.all_buckets
  bucket   = each.value
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# ------------------------------------------------ ingest + processed (private)
data "aws_iam_policy_document" "tls_only" {
  for_each = {
    ingest    = aws_s3_bucket.ingest.arn
    processed = aws_s3_bucket.processed.arn
  }

  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [each.value, "${each.value}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "private" {
  for_each = data.aws_iam_policy_document.tls_only
  bucket   = local.all_buckets[each.key]
  policy   = each.value.json

  depends_on = [aws_s3_bucket_public_access_block.all]
}

resource "aws_s3_bucket_cors_configuration" "ingest" {
  bucket = aws_s3_bucket.ingest.id

  cors_rule {
    allowed_methods = ["POST"]
    allowed_origins = concat(["https://${aws_cloudfront_distribution.web.domain_name}"], var.cors_extra_origins)
    allowed_headers = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "ingest" {
  bucket = aws_s3_bucket.ingest.id

  rule {
    id     = "expire-originals"
    status = "Enabled"
    filter {}
    expiration {
      days = var.ingest_retention_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "processed" {
  bucket = aws_s3_bucket.processed.id

  rule {
    id     = "expire-processed"
    status = "Enabled"
    filter {}
    expiration {
      days = var.processed_retention_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# Object-created events -> EventBridge (the rule lives in eventbridge.tf).
resource "aws_s3_bucket_notification" "ingest" {
  bucket      = aws_s3_bucket.ingest.id
  eventbridge = true
}
