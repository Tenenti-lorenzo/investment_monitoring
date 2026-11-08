resource "aws_dynamodb_table" "users" {
  name         = "${var.app_name}_users"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "username"

  attribute {
    name = "username"
    type = "S"
  }

  attribute {
    name = "email"
    type = "S"
  }

  attribute {
    name = "reset_token_hash"
    type = "S"
  }

  # Lookups by email (register, forgot-password) and by reset-token hash
  # without scanning the table. Names match backend/database.py.
  global_secondary_index {
    name            = "email-index"
    hash_key        = "email"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "reset_token_hash-index"
    hash_key        = "reset_token_hash"
    projection_type = "ALL"
  }

  tags = {
    App = var.app_name
    Env = var.environment
  }
}

# Server-side login sessions (rotating JWT). Idle sessions are removed by TTL.
resource "aws_dynamodb_table" "sessions" {
  name         = "${var.app_name}_sessions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "username"
  range_key    = "sid"

  attribute {
    name = "username"
    type = "S"
  }

  attribute {
    name = "sid"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = {
    App = var.app_name
    Env = var.environment
  }
}

resource "aws_dynamodb_table" "portfolios" {
  name         = "${var.app_name}_portfolios"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "username"
  range_key    = "portfolio_id"

  attribute {
    name = "username"
    type = "S"
  }

  attribute {
    name = "portfolio_id"
    type = "S"
  }

  tags = {
    App = var.app_name
    Env = var.environment
  }
}

# Hand-entered assets outside the market portfolio (life insurance, pension
# funds, real estate with mortgage, private investments). One item per asset.
resource "aws_dynamodb_table" "assets" {
  name         = "${var.app_name}_assets"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "username"
  range_key    = "asset_id"

  attribute {
    name = "username"
    type = "S"
  }

  attribute {
    name = "asset_id"
    type = "S"
  }

  tags = {
    App = var.app_name
    Env = var.environment
  }
}
