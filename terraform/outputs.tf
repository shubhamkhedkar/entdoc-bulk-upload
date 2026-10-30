output "web_url" {
  description = "Open this in a browser to use EntDoc Bulk Upload."
  value       = "https://${aws_cloudfront_distribution.web.domain_name}"
}

output "api_url" {
  value = aws_apigatewayv2_api.http.api_endpoint
}

output "ingest_bucket" {
  value = aws_s3_bucket.ingest.id
}

output "processed_bucket" {
  value = aws_s3_bucket.processed.id
}

output "jobs_table" {
  value = aws_dynamodb_table.jobs.name
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.id
}

output "alarm_topic_arn" {
  value = aws_sns_topic.alarms.arn
}
