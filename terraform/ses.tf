# ── SES: password-reset emails ────────────────────────────────────────────────
# Enabled only when var.ses_sender_email is set. After apply, AWS sends a
# verification email to that address: click the link before resets can work.
# A new account is in the SES sandbox (recipients must be verified too) until
# production access is requested in the SES console.

locals {
  ses_senders = var.ses_sender_email != "" ? { sender = var.ses_sender_email } : {}
}

resource "aws_sesv2_email_identity" "sender" {
  for_each       = local.ses_senders
  email_identity = each.value

  tags = {
    App = var.app_name
    Env = var.environment
  }
}

resource "aws_iam_role_policy" "ses" {
  for_each = aws_sesv2_email_identity.sender
  name     = "${var.app_name}-ses"
  role     = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ses:SendEmail"]
      Resource = each.value.arn
    }]
  })
}
