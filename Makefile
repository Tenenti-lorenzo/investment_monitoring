REGION  ?= eu-central-1
APP     := portfoliolab
TF_DIR  := terraform

# ── Helpers ────────────────────────────────────────────────────────────────────
ecr_url    = $(shell cd $(TF_DIR) && terraform output -raw ecr_repository_url)
bucket     = $(shell cd $(TF_DIR) && terraform output -raw s3_bucket_name)
cf_url     = $(shell cd $(TF_DIR) && terraform output -raw cloudfront_url)
lambda_fn  = $(shell cd $(TF_DIR) && terraform output -raw lambda_function_name)

# ── Terraform ──────────────────────────────────────────────────────────────────
.PHONY: tf-init tf-plan tf-apply tf-destroy

tf-init:
	cd $(TF_DIR) && terraform init

tf-plan:
	cd $(TF_DIR) && terraform plan

tf-apply:
	cd $(TF_DIR) && terraform apply

tf-destroy:
	cd $(TF_DIR) && terraform destroy

# ── Docker image ───────────────────────────────────────────────────────────────
.PHONY: ecr-login image-build image-push lambda-update

ecr-login:
	aws ecr get-login-password --region $(REGION) | \
	  docker login --username AWS --password-stdin $(ecr_url)

image-build:
	docker buildx build --platform linux/amd64 -t $(APP):latest .

image-push: ecr-login image-build
	docker tag $(APP):latest $(ecr_url):latest
	docker push $(ecr_url):latest

# Force Lambda to pull the new image (Terraform won't detect :latest tag change)
lambda-update:
	aws lambda update-function-code \
	  --function-name $(lambda_fn) \
	  --image-uri $(ecr_url):latest \
	  --region $(REGION)

# ── Static files ───────────────────────────────────────────────────────────────
.PHONY: upload-static

upload-static:
	aws s3 sync frontend/static s3://$(bucket)/static --delete
	aws s3 cp frontend/index.html  s3://$(bucket)/index.html
	aws s3 cp frontend/login.html  s3://$(bucket)/login.html
	@echo "Static files uploaded to s3://$(bucket)"

# ── Full deploy workflow ────────────────────────────────────────────────────────
#
# First deploy (no ECR image yet):
#   make first-deploy
#
# Subsequent deploys (infra unchanged, just new code/assets):
#   make deploy
#
.PHONY: first-deploy deploy set-app-url

# Step 1: create ECR repo, push image, deploy everything, upload static files
first-deploy: tf-init
	@echo "==> Creating ECR repository..."
	cd $(TF_DIR) && terraform apply -target=aws_ecr_repository.app -auto-approve
	@echo "==> Building and pushing Docker image..."
	$(MAKE) image-push
	@echo "==> Deploying full infrastructure..."
	cd $(TF_DIR) && terraform apply -auto-approve
	@echo "==> Uploading static files to S3..."
	$(MAKE) upload-static
	@echo ""
	@echo "✅  Deploy complete!"
	@echo "    CloudFront URL: $(cf_url)"
	@echo ""
	@echo "👉  Next: add the CloudFront URL to terraform/terraform.tfvars as app_url"
	@echo "    then run 'make set-app-url' to update the Lambda env var."

# Subsequent deploys: push new image + upload static files
deploy: image-push lambda-update upload-static
	@echo "✅  Deploy complete! App: $(cf_url)"

# Set APP_URL in Lambda after CloudFront URL is known (run once after first-deploy)
set-app-url:
	@CF=$$(cd $(TF_DIR) && terraform output -raw cloudfront_url) && \
	echo "Setting APP_URL=$$CF on Lambda..." && \
	aws lambda update-function-configuration \
	  --function-name $(lambda_fn) \
	  --environment "Variables={$$(aws lambda get-function-configuration \
	    --function-name $(lambda_fn) \
	    --query 'Environment.Variables' \
	    --output json | python3 -c \
	    'import sys,json; v=json.load(sys.stdin); v["APP_URL"]=sys.argv[1]; \
	     print(",".join(f"{k}={v2}" for k,v2 in v.items()))' $$CF)}" \
	  --region $(REGION) > /dev/null && \
	echo "✅  APP_URL set to $$CF"
