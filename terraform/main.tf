terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# WAF for CloudFront must live in us-east-1 (waf.tf).
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

resource "random_id" "suffix" {
  byte_length = 4
}
