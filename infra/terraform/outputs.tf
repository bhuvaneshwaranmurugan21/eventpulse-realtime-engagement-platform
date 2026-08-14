output "archive_bucket" {
  value = aws_s3_bucket.archive.id
}

output "stream_name" {
  value = aws_kinesis_stream.events.name
}

output "state_table" {
  value = aws_dynamodb_table.state.name
}

output "quarantine_queue_url" {
  value     = aws_sqs_queue.quarantine.url
  sensitive = true
}

