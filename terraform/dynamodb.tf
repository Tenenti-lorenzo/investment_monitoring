resource "aws_dynamodb_table" "users" {
  name         = "${var.app_name}_users"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "username"

  attribute {
    name = "username"
    type = "S"
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
