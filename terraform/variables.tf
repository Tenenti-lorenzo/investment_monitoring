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

  validation {
    condition     = length(var.jwt_secret_key) >= 32
    error_message = "jwt_secret_key must be at least 32 characters (the backend refuses to start otherwise)."
  }
}

variable "anthropic_model" {
  description = "Anthropic model ID to use for document extraction"
  type        = string
  default     = "claude-sonnet-4-6"
}

variable "fred_api_key" {
  description = "FRED API key for live sovereign-bond yields (free: fred.stlouisfed.org/docs/api/api_key.html). Leave empty to disable sovereign risk."
  type        = string
  sensitive   = true
  default     = ""
}

variable "app_url" {
  description = <<-EOT
    Public base URL (CloudFront domain). Leave empty on first deploy.
    After first 'terraform apply', get the CloudFront URL from outputs,
    set it here, and re-apply so password-reset emails use the correct link.
  EOT
  type        = string
  default     = ""
}

variable "recaptcha_site_key" {
  description = "Google reCAPTCHA v3 site key (public). Register the CloudFront domain at google.com/recaptcha/admin."
  type        = string

  validation {
    condition     = length(var.recaptcha_site_key) > 0
    error_message = "recaptcha_site_key is required (create v3 keys at google.com/recaptcha/admin)."
  }
}

variable "recaptcha_secret_key" {
  description = "Google reCAPTCHA v3 secret key. Required: on AWS, login/register are rejected without it."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.recaptcha_secret_key) > 0
    error_message = "recaptcha_secret_key is required (create v3 keys at google.com/recaptcha/admin)."
  }
}

variable "enable_waf" {
  description = "Per-IP rate limiting with AWS WAF on CloudFront (about 6 USD/month + 0.60 USD per million requests)."
  type        = bool
  default     = true
}

variable "waf_auth_limit" {
  description = "Max /api/auth/* requests per IP in 5 minutes before WAF blocks it."
  type        = number
  default     = 100
}

variable "waf_global_limit" {
  description = "Max requests of any kind per IP in 5 minutes before WAF blocks it."
  type        = number
  default     = 2000
}

variable "api_throttle_rate" {
  description = "API Gateway steady-state request rate (req/s, all clients together)."
  type        = number
  default     = 50
}

variable "api_throttle_burst" {
  description = "API Gateway burst capacity (requests, all clients together)."
  type        = number
  default     = 100
}

variable "ses_sender_email" {
  description = "Verified SES sender for password-reset emails. Empty = reset by email disabled (API answers 503)."
  type        = string
  default     = ""
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
