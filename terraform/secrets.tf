resource "aws_secretsmanager_secret" "app" {
  name        = "${var.app_name}/secrets"
  description = "ANTHROPIC_API_KEY and SECRET_KEY for ${var.app_name}"

  tags = {
    App = var.app_name
    Env = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    ANTHROPIC_API_KEY = var.anthropic_api_key
    SECRET_KEY        = var.jwt_secret_key
    FRED_API_KEY      = var.fred_api_key
  })
}
