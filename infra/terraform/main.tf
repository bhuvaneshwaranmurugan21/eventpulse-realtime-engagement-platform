data "aws_caller_identity" "current" {}

resource "random_id" "suffix" {
  byte_length = 4
}

locals {
  name   = "eventpulse-${var.environment}"
  prefix = "${local.name}-${data.aws_caller_identity.current.account_id}-${random_id.suffix.hex}"
  tags = {
    Project     = "EventPulse"
    RunId       = var.run_id
    Environment = var.environment
    ExpiresAt   = var.expires_at
    ManagedBy   = "Terraform"
  }
}

resource "aws_s3_bucket" "archive" {
  bucket        = "${local.prefix}-archive"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "archive" {
  bucket                  = aws_s3_bucket.archive.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    id     = "expire-lab-data"
    status = "Enabled"
    expiration {
      days = 7
    }
  }
}

resource "aws_kinesis_stream" "events" {
  name             = "${local.name}-events-${random_id.suffix.hex}"
  shard_count      = 1
  retention_period = 24
  encryption_type  = "KMS"
  kms_key_id       = "alias/aws/kinesis"
  stream_mode_details {
    stream_mode = "PROVISIONED"
  }
}

resource "aws_dynamodb_table" "state" {
  name         = "${local.name}-state-${random_id.suffix.hex}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "state_key"
  attribute {
    name = "state_key"
    type = "S"
  }
  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_sqs_queue" "quarantine" {
  name                      = "${local.name}-quarantine-${random_id.suffix.hex}"
  message_retention_seconds = 604800
  kms_master_key_id         = "alias/aws/sqs"
}

resource "aws_cloudwatch_log_group" "consumer" {
  name              = "/aws/eventpulse/${var.run_id}"
  retention_in_days = 7
}

resource "aws_cloudwatch_metric_alarm" "iterator_age" {
  alarm_name          = "${local.name}-iterator-age-${random_id.suffix.hex}"
  namespace           = "AWS/Kinesis"
  metric_name         = "GetRecords.IteratorAgeMilliseconds"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  period              = 60
  statistic           = "Maximum"
  threshold           = 60000
  treat_missing_data  = "notBreaching"
  dimensions = {
    StreamName = aws_kinesis_stream.events.name
  }
}

resource "aws_cloudwatch_metric_alarm" "quarantine_depth" {
  alarm_name          = "${local.name}-quarantine-depth-${random_id.suffix.hex}"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  dimensions = {
    QueueName = aws_sqs_queue.quarantine.name
  }
}

