# Packages are produced by `make build` (scripts/build_lambdas.sh) before plan/apply.
data "archive_file" "api" {
  type        = "zip"
  source_dir  = "${path.module}/../build/api"
  output_path = "${path.module}/../build/api.zip"
}

data "archive_file" "processor" {
  type        = "zip"
  source_dir  = "${path.module}/../build/processor"
  output_path = "${path.module}/../build/processor.zip"
}

resource "aws_cloudwatch_log_group" "presign" {
  name              = "/aws/lambda/${local.prefix}-presign"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "status" {
  name              = "/aws/lambda/${local.prefix}-status"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "processor" {
  name              = "/aws/lambda/${local.prefix}-processor"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "presign" {
  function_name    = "${local.prefix}-presign"
  role             = aws_iam_role.presign.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "presign.handler"
  filename         = data.archive_file.api.output_path
  source_code_hash = data.archive_file.api.output_base64sha256
  memory_size      = 256
  timeout          = 10

  environment {
    variables = {
      INGEST_BUCKET         = aws_s3_bucket.ingest.id
      JOBS_TABLE            = aws_dynamodb_table.jobs.name
      MAX_FILE_BYTES        = tostring(local.max_file_bytes)
      MAX_FILES_PER_REQUEST = tostring(var.max_files_per_request)
      JOB_TTL_DAYS          = tostring(var.job_ttl_days)
    }
  }

  depends_on = [aws_cloudwatch_log_group.presign, aws_iam_role_policy.presign]
}

resource "aws_lambda_function" "status" {
  function_name    = "${local.prefix}-status"
  role             = aws_iam_role.status.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "status.handler"
  filename         = data.archive_file.api.output_path
  source_code_hash = data.archive_file.api.output_base64sha256
  memory_size      = 256
  timeout          = 10

  environment {
    variables = {
      OUTPUT_BUCKET = aws_s3_bucket.processed.id
      JOBS_TABLE    = aws_dynamodb_table.jobs.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.status, aws_iam_role_policy.status]
}

resource "aws_lambda_function" "processor" {
  function_name    = "${local.prefix}-processor"
  role             = aws_iam_role.processor.arn
  runtime          = "python3.12"
  architectures    = ["arm64"] # must match the wheels fetched by scripts/build_lambdas.sh
  handler          = "processor.handler"
  filename         = data.archive_file.processor.output_path
  source_code_hash = data.archive_file.processor.output_base64sha256
  memory_size      = var.processor_memory_mb
  timeout          = var.processor_timeout_seconds

  environment {
    variables = {
      INGEST_BUCKET  = aws_s3_bucket.ingest.id
      OUTPUT_BUCKET  = aws_s3_bucket.processed.id
      JOBS_TABLE     = aws_dynamodb_table.jobs.name
      MAX_FILE_BYTES = tostring(local.max_file_bytes)
      MAX_PAGES      = tostring(var.max_pages)
      IMAGE_QUALITY  = tostring(var.image_quality)
    }
  }

  depends_on = [aws_cloudwatch_log_group.processor, aws_iam_role_policy.processor]
}

# EventBridge invokes asynchronously: retry twice, then park the event in the DLQ.
resource "aws_lambda_function_event_invoke_config" "processor" {
  function_name                = aws_lambda_function.processor.function_name
  maximum_retry_attempts       = 2
  maximum_event_age_in_seconds = 3600

  destination_config {
    on_failure {
      destination = aws_sqs_queue.dlq.arn
    }
  }
}
