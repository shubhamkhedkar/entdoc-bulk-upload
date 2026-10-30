resource "aws_dynamodb_table" "jobs" {
  name         = "${local.prefix}-pdf-jobs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "job_id"

  attribute {
    name = "job_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true # AWS-owned key (no extra cost); use a CMK for stricter compliance
  }
}
