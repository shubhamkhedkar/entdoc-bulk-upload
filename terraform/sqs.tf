resource "aws_sqs_queue" "dlq" {
  name                      = "${local.prefix}-pdf-processing-dlq"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true
}

# Lets the EventBridge rule park events it could not deliver to the Lambda.
data "aws_iam_policy_document" "dlq" {
  statement {
    sid       = "AllowEventBridgeRule"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.pdf_uploaded.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id
  policy    = data.aws_iam_policy_document.dlq.json
}
