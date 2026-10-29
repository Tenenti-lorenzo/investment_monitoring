locals {
  s3_origin_id    = "S3-frontend"
  apigw_origin_id = "APIGateway"
}

# Origin Access Control for S3 (modern replacement for OAI)
resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${var.app_name}-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# CloudFront Function: rewrite /login, /analisi, /rendimenti, /altri-investimenti, /patrimonio → *.html (no .html in browser)
resource "aws_cloudfront_function" "url_rewrite" {
  name    = "${var.app_name}-url-rewrite"
  runtime = "cloudfront-js-2.0"
  publish = true

  code = <<-EOT
    function handler(event) {
      var req = event.request;
      if (req.uri === '/login') { req.uri = '/login.html'; }
      if (req.uri === '/analisi') { req.uri = '/analisi.html'; }
      if (req.uri === '/rendimenti') { req.uri = '/rendimenti.html'; }
      if (req.uri === '/altri-investimenti') { req.uri = '/altri-investimenti.html'; }
      if (req.uri === '/patrimonio') { req.uri = '/patrimonio.html'; }
      return req;
    }
  EOT
}

# Security headers on every response (pages and API). The CSP whitelists only
# the hosts the pages really load: jsDelivr (Chart.js, D3, world atlas), Google
# Fonts and reCAPTCHA. 'unsafe-inline' is still needed for the inline handlers
# and <style> blocks in the pages.
resource "aws_cloudfront_response_headers_policy" "security" {
  name = "${var.app_name}-security-headers"

  security_headers_config {
    content_security_policy {
      override = true
      content_security_policy = join("; ", [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://www.google.com/recaptcha/ https://www.gstatic.com/recaptcha/",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data: https:",
        "connect-src 'self' https://cdn.jsdelivr.net https://www.google.com/recaptcha/",
        "frame-src https://www.google.com/recaptcha/ https://recaptcha.google.com/recaptcha/",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
      ])
    }

    strict_transport_security {
      override                   = true
      access_control_max_age_sec = 63072000 # 2 years
      include_subdomains         = true
      preload                    = false
    }

    content_type_options {
      override = true
    }

    frame_options {
      override     = true
      frame_option = "DENY"
    }

    referrer_policy {
      override        = true
      referrer_policy = "strict-origin-when-cross-origin"
    }
  }
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  web_acl_id          = var.enable_waf ? aws_wafv2_web_acl.edge["main"].arn : null
  default_root_object = "index.html"
  price_class         = "PriceClass_100" # EU + North America only (cheapest)
  comment             = "${var.app_name} ${var.environment}"

  # ── Origin 1: S3 static files ───────────────────────────────────────────────
  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = local.s3_origin_id
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  # ── Origin 2: API Gateway (Lambda) ──────────────────────────────────────────
  origin {
    domain_name = replace(aws_apigatewayv2_api.app.api_endpoint, "https://", "")
    origin_id   = local.apigw_origin_id

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # ── Default behavior: S3 static files ───────────────────────────────────────
  default_cache_behavior {
    target_origin_id           = local.s3_origin_id
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    viewer_protocol_policy     = "redirect-to-https"
    compress                   = true
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id

    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }

    min_ttl     = 0
    default_ttl = 86400   # 1 day
    max_ttl     = 2592000 # 30 days

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.url_rewrite.arn
    }
  }

  # ── /api/* behavior: forward to API Gateway, no caching ─────────────────────
  ordered_cache_behavior {
    path_pattern               = "/api/*"
    target_origin_id           = local.apigw_origin_id
    allowed_methods            = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods             = ["GET", "HEAD"]
    viewer_protocol_policy     = "redirect-to-https"
    compress                   = true
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id

    forwarded_values {
      query_string = true
      headers      = ["Authorization", "Content-Type", "Origin"]
      cookies { forward = "none" }
    }

    # No caching for API responses
    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = {
    App = var.app_name
    Env = var.environment
  }
}
