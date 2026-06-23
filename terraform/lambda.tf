# ── IAM Role ──────────────────────────────────────────────────────────────────

resource "aws_iam_role" "lambda" {
  name = "${var.app_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = {
    App = var.app_name
    Env = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "dynamodb" {
  name = "${var.app_name}-dynamodb"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query",
        "dynamodb:Scan",
        "dynamodb:DescribeTable",
      ]
      Resource = [
        aws_dynamodb_table.users.arn,
        aws_dynamodb_table.portfolios.arn,
      ]
    }]
  })
}

resource "aws_iam_role_policy" "secrets" {
  name = "${var.app_name}-secrets"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = aws_secretsmanager_secret.app.arn
    }]
  })
}

# ── CloudWatch Log Group ───────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.app_name}"
  retention_in_days = 14

  tags = {
    App = var.app_name
    Env = var.environment
  }
}

# ── Lambda Function ────────────────────────────────────────────────────────────

resource "aws_lambda_function" "app" {
  function_name = var.app_name
  role          = aws_iam_role.lambda.arn

  package_type = "Image"
  image_uri    = "${aws_ecr_repository.app.repository_url}:latest"

  timeout     = var.lambda_timeout_seconds
  memory_size = var.lambda_memory_mb

  environment {
    variables = merge(
      {
        SECRETS_ARN               = aws_secretsmanager_secret.app.arn
        ANTHROPIC_MODEL           = var.anthropic_model
        DYNAMODB_TABLE            = aws_dynamodb_table.users.name
        DYNAMODB_PORTFOLIOS_TABLE = aws_dynamodb_table.portfolios.name
      },
      # APP_URL is set only after first deploy when CloudFront URL is known.
      # Leave empty on first apply; set in terraform.tfvars and re-apply.
      var.app_url != "" ? { APP_URL = var.app_url } : {}
    )
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_logs,
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy.secrets,
  ]

  tags = {
    App = var.app_name
    Env = var.environment
  }
}

# ── Permission for API Gateway → Lambda ───────────────────────────────────────

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.app.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.app.execution_arn}/*/*"
}
