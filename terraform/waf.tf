# ── AWS WAF on CloudFront: per-IP rate limits ────────────────────────────────
# API Gateway HTTP APIs cannot take a WAF directly, so it sits on CloudFront
# (scope CLOUDFRONT, which AWS requires in us-east-1). A client over a limit is
# blocked for the rest of the 5-minute window. Toggle with var.enable_waf.

locals {
  waf = var.enable_waf ? { main = true } : {}
}

resource "aws_wafv2_web_acl" "edge" {
  for_each = local.waf
  provider = aws.us_east_1
  name     = "${var.app_name}-edge"
  scope    = "CLOUDFRONT"

  default_action {
    allow {}
  }

  # Login, sign-up and reset: tight limit against brute force and mass sign-ups.
  rule {
    name     = "auth-rate-limit"
    priority = 1

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit                 = var.waf_auth_limit
        aggregate_key_type    = "IP"
        evaluation_window_sec = 300

        scope_down_statement {
          byte_match_statement {
            search_string         = "/api/auth/"
            positional_constraint = "STARTS_WITH"

            field_to_match {
              uri_path {}
            }

            text_transformation {
              priority = 0
              type     = "LOWERCASE"
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.app_name}-auth-rate-limit"
      sampled_requests_enabled   = true
    }
  }

  # Everything else: generous ceiling against scraping and floods.
  rule {
    name     = "global-rate-limit"
    priority = 2

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit                 = var.waf_global_limit
        aggregate_key_type    = "IP"
        evaluation_window_sec = 300
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.app_name}-global-rate-limit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.app_name}-edge"
    sampled_requests_enabled   = true
  }

  tags = {
    App = var.app_name
    Env = var.environment
  }
}
