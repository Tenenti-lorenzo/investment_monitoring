variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "eu-central-1"
}

variable "app_name" {
  description = "Application name — used as prefix for all resource names"
  type        = string
  default     = "portfoliolab"
}

variable "environment" {
  description = "Deployment environment tag"
  type        = string
  default     = "prod"
}

variable "anthropic_api_key" {
  description = "Anthropic API key for Claude AI document extraction"
  type        = string
  sensitive   = true
}

variable "jwt_secret_key" {
  description = "Secret key for signing JWT tokens (use a long random string)"
  type        = string
  sensitive   = true
}

variable "anthropic_model" {
  description = "Anthropic model ID to use for document extraction"
  type        = string
  default     = "claude-sonnet-4-6"
}

variable "app_url" {
  description = <<-EOT
    Public base URL (CloudFront domain). Leave empty on first deploy.
    After first 'terraform apply', get the CloudFront URL from outputs,
    set it here, and re-apply so password-reset emails use the correct link.
  EOT
  type    = string
  default = ""
}

variable "lambda_memory_mb" {
  description = "Lambda memory in MB (yfinance + pandas need headroom)"
  type        = number
  default     = 1024
}

variable "lambda_timeout_seconds" {
  description = "Lambda timeout — yfinance calls can be slow"
  type        = number
  default     = 30
}
