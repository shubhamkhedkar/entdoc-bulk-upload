# Note: "wildcard" matches prefix AND suffix; two entries in a pattern array would be an OR.
resource "aws_cloudwatch_event_rule" "pdf_uploaded" {
  name        = "${local.prefix}-pdf-uploaded"
  description = "New PDF in the ingest bucket -> processing Lambda"

  event_pattern = jsonencode({
    source        = ["aws.s3"]
    "detail-type" = ["Object Created"]
    detail = {
      bucket = { name = [aws_s3_bucket.ingest.id] }
      object = { key = [{ wildcard = "uploads/*.pdf" }] }
    }
  })
}

resource "aws_cloudwatch_event_target" "processor" {
  rule = aws_cloudwatch_event_rule.pdf_uploaded.name
  arn  = aws_lambda_function.processor.arn

  retry_policy {
    maximum_retry_attempts       = 3
    maximum_event_age_in_seconds = 3600
  }

  dead_letter_config {
    arn = aws_sqs_queue.dlq.arn
  }
}

resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.processor.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.pdf_uploaded.arn
}
