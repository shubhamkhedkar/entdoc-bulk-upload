# One role per Lambda, each limited to exactly what that function does.
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "presign" {
  name               = "${local.prefix}-presign-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role" "status" {
  name               = "${local.prefix}-status-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role" "processor" {
  name               = "${local.prefix}-processor-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# ---- presign: sign S3 POSTs for uploads/*, create job rows
data "aws_iam_policy_document" "presign" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.presign.arn}:*"]
  }
  statement {
    sid       = "SignUploadsOnly" # the presigned POST is only as powerful as this permission
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.ingest.arn}/uploads/*"]
  }
  statement {
    sid       = "CreateJobs"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.jobs.arn]
  }
}

resource "aws_iam_role_policy" "presign" {
  name   = "presign"
  role   = aws_iam_role.presign.id
  policy = data.aws_iam_policy_document.presign.json
}

# ---- status: read jobs, sign downloads of processed/*
data "aws_iam_policy_document" "status" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.status.arn}:*"]
  }
  statement {
    sid       = "ReadJobs"
    actions   = ["dynamodb:GetItem", "dynamodb:BatchGetItem"]
    resources = [aws_dynamodb_table.jobs.arn]
  }
  statement {
    sid       = "SignDownloads"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.processed.arn}/processed/*"]
  }
}

resource "aws_iam_role_policy" "status" {
  name   = "status"
  role   = aws_iam_role.status.id
  policy = data.aws_iam_policy_document.status.json
}

# ---- processor: read originals, write results, update job rows, report failures to DLQ
data "aws_iam_policy_document" "processor" {
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.processor.arn}:*"]
  }
  statement {
    sid       = "ReadOriginals"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.ingest.arn}/uploads/*"]
  }
  statement {
    sid       = "WriteResults"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.processed.arn}/processed/*"]
  }
  statement {
    sid       = "UpdateJobs"
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.jobs.arn]
  }
  statement {
    sid       = "AsyncFailureDestination"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }
}

resource "aws_iam_role_policy" "processor" {
  name   = "processor"
  role   = aws_iam_role.processor.id
  policy = data.aws_iam_policy_document.processor.json
}
