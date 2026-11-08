# Dev environment overrides — applied on top of terraform.tfvars (secrets stay there).
# Used by: .\deploy.ps1 <command> -Environment dev  (Terraform workspace "dev", separate state)
app_name    = "dev-portfoliolab"
environment = "dev"
app_url     = ""
