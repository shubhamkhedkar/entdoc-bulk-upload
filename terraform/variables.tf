variable "aws_region" {
  description = "AWS region for every resource (CloudFront is global)."
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  type    = string
  default = "entdoc"
}

variable "environment" {
  type    = string
  default = "prod"
}

variable "max_file_size_mb" {
  description = "Largest PDF accepted (enforced by the presigned POST policy and again by the processor)."
  type        = number
  default     = 50
}

variable "max_files_per_request" {
  type    = number
  default = 25
}

variable "max_pages" {
  description = "Reject PDFs with more pages than this."
  type        = number
  default     = 500
}

variable "image_quality" {
  description = "JPEG quality (1-100) used when recompressing embedded images; 0 disables recompression."
  type        = number
  default     = 70
}

variable "processor_memory_mb" {
  type    = number
  default = 2048
}

variable "processor_timeout_seconds" {
  type    = number
  default = 120
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "job_ttl_days" {
  description = "Job records are deleted by DynamoDB TTL after this many days."
  type        = number
  default     = 30
}

variable "ingest_retention_days" {
  description = "Uploaded originals are deleted from the ingest bucket after this many days."
  type        = number
  default     = 7
}

variable "processed_retention_days" {
  description = "Processed PDFs are deleted after this many days."
  type        = number
  default     = 30
}

variable "alert_email" {
  description = "Optional address subscribed to the alarm SNS topic (must confirm the subscription email)."
  type        = string
  default     = ""
}

variable "cors_extra_origins" {
  description = "Extra browser origins allowed to call the API / upload to S3 (e.g. local dev)."
  type        = list(string)
  default     = ["http://localhost:8080"]
}

variable "api_throttle_rate_limit" {
  type    = number
  default = 25
}

variable "api_throttle_burst_limit" {
  type    = number
  default = 50
}

variable "force_destroy_buckets" {
  description = "Let `terraform destroy` delete buckets that still contain objects. Set false to protect data."
  type        = bool
  default     = true
}
