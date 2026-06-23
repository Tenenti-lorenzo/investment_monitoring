output "cloudfront_url" {
  description = "Public URL of the app — set this as app_url in terraform.tfvars and re-apply"
  value       = "https://${aws_cloudfront_distribution.frontend.domain_name}"
}

output "cloudfront_domain" {
  value = aws_cloudfront_distribution.frontend.domain_name
}

output "api_gateway_endpoint" {
  description = "Direct API Gateway URL (for debugging — use CloudFront URL in production)"
  value       = aws_apigatewayv2_api.app.api_endpoint
}

output "ecr_repository_url" {
  description = "ECR repository URL — used by Makefile to push Docker images"
  value       = aws_ecr_repository.app.repository_url
}

output "s3_bucket_name" {
  description = "S3 bucket for static frontend files"
  value       = aws_s3_bucket.frontend.bucket
}

output "lambda_function_name" {
  value = aws_lambda_function.app.function_name
}
