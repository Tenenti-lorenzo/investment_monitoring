# HTTP API (v2) — cheaper and lower latency than REST API
resource "aws_apigatewayv2_api" "app" {
  name          = "${var.app_name}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_headers = ["Authorization", "Content-Type"]
    allow_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    allow_origins = ["*"]
    max_age       = 300
  }

  tags = {
    App = var.app_name
    Env = var.environment
  }
}

# Lambda integration
resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.app.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.app.invoke_arn
  payload_format_version = "2.0"
}

# Route: all /api/* paths → Lambda
resource "aws_apigatewayv2_route" "api_proxy" {
  api_id    = aws_apigatewayv2_api.app.id
  route_key = "ANY /api/{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

# $default stage with auto-deploy
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.app.id
  name        = "$default"
  auto_deploy = true

  tags = {
    App = var.app_name
    Env = var.environment
  }
}
