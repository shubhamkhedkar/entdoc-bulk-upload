terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "EntDoc Bulk Upload"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  prefix     = "${var.project_name}-${var.environment}"
  account_id = data.aws_caller_identity.current.account_id

  ingest_bucket_name    = "${local.prefix}-pdf-ingest-${local.account_id}"
  processed_bucket_name = "${local.prefix}-pdf-processed-${local.account_id}"
  web_bucket_name       = "${local.prefix}-web-${local.account_id}"

  max_file_bytes = var.max_file_size_mb * 1024 * 1024
}
