# Static UI: private S3 bucket served through CloudFront (Origin Access Control).
locals {
  mime_types = {
    html = "text/html; charset=utf-8"
    css  = "text/css; charset=utf-8"
    js   = "application/javascript; charset=utf-8"
    svg  = "image/svg+xml"
  }
  web_files = toset([for f in fileset("${path.module}/../web", "*") : f if f != "config.js"])
}

resource "aws_s3_object" "web" {
  for_each     = local.web_files
  bucket       = aws_s3_bucket.web.id
  key          = each.value
  source       = "${path.module}/../web/${each.value}"
  etag         = filemd5("${path.module}/../web/${each.value}")
  content_type = lookup(local.mime_types, regex("[^.]+$", each.value), "application/octet-stream")
}

# Runtime config generated from the deployed API URL (web/config.js is only a local-dev stub).
resource "aws_s3_object" "web_config" {
  bucket       = aws_s3_bucket.web.id
  key          = "config.js"
  content_type = "application/javascript; charset=utf-8"
  content      = "window.ENTDOC_CONFIG = ${jsonencode({ apiBaseUrl = aws_apigatewayv2_api.http.api_endpoint })};\n"
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_response_headers_policy" "security" {
  name = "Managed-SecurityHeadersPolicy"
}

resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "${local.prefix}-web-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "web" {
  enabled             = true
  comment             = "EntDoc Bulk Upload UI"
  default_root_object = "index.html"
  price_class         = "PriceClass_200" # includes India edge locations; PriceClass_100 is cheaper
  http_version        = "http2and3"

  origin {
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_id                = "web-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  default_cache_behavior {
    target_origin_id           = "web-s3"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.disabled.id # tiny site; avoids stale config.js
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

data "aws_iam_policy_document" "web" {
  statement {
    sid       = "AllowCloudFrontRead"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.web.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.web.arn]
    }
  }
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.web.arn, "${aws_s3_bucket.web.arn}/*"]
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

resource "aws_s3_bucket_policy" "web" {
  bucket     = aws_s3_bucket.web.id
  policy     = data.aws_iam_policy_document.web.json
  depends_on = [aws_s3_bucket_public_access_block.all]
}
