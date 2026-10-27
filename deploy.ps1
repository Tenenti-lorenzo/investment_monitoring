<#
.SYNOPSIS
    Deploy PortfolioLab to AWS (Lambda + API Gateway + S3 + CloudFront)

.PARAMETER Command
    first-deploy  : Prima installazione completa
    deploy        : Aggiorna codice (image + static files)
    image-push    : Solo build e push Docker image
    upload-static : Solo upload file statici su S3
    tf-plan       : Mostra il piano Terraform
    tf-apply      : Applica Terraform
    set-app-url   : Imposta APP_URL su Lambda dopo il primo deploy
    outputs       : Mostra gli output Terraform

.PARAMETER Environment
    prod (default) : workspace Terraform "default", nomi portfoliolab-*
    dev            : workspace Terraform "dev" + terraform/env/dev.tfvars, nomi dev-portfoliolab-*

.EXAMPLE
    .\deploy.ps1 first-deploy
    .\deploy.ps1 deploy
    .\deploy.ps1 first-deploy -Environment dev
#>
param(
    [Parameter(Mandatory)]
    [ValidateSet("first-deploy","deploy","image-push","upload-static","tf-plan","tf-apply","set-app-url","outputs")]
    [string]$Command,

    [ValidateSet("prod","dev")]
    [string]$Environment = "prod"
)

$ErrorActionPreference = "Stop"

if ($env:AWS_REGION) { $REGION = $env:AWS_REGION } else { $REGION = "eu-central-1" }
$TF_DIR   = "terraform"
if ($Environment -eq "prod") {
    $APP_NAME     = "portfoliolab"
    $TF_WORKSPACE = "default"
    $TF_VAR_ARGS  = @()
} else {
    $APP_NAME     = "$Environment-portfoliolab"
    $TF_WORKSPACE = $Environment
    $TF_VAR_ARGS  = @("-var-file=env/$Environment.tfvars")
}

# Returns a terraform output value, empty string on failure.
# Uses -no-color to strip ANSI codes, checks exit code.
function Get-TfOutput([string]$name) {
    Push-Location $TF_DIR
    $val = terraform output -raw -no-color $name 2>$null
    $ok  = ($LASTEXITCODE -eq 0)
    Pop-Location
    if (-not $ok) { return "" }
    return $val
}

function Assert-TfOutput([string]$name, [string]$hint) {
    $val = Get-TfOutput $name
    if (-not $val) {
        throw "Output Terraform '$name' non trovato. $hint"
    }
    return $val
}

# Each environment has its own Terraform workspace (= separate state file).
function Select-TfWorkspace {
    Push-Location $TF_DIR
    terraform workspace select -or-create $TF_WORKSPACE | Out-Null
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { throw "terraform workspace select $TF_WORKSPACE fallito (esegui prima terraform init)" }
    Write-Host "==> Ambiente: $Environment (workspace '$TF_WORKSPACE')" -ForegroundColor Cyan
}

function Invoke-TfInit {
    Write-Host ""
    Write-Host "==> terraform init" -ForegroundColor Cyan
    Push-Location $TF_DIR
    terraform init
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { throw "terraform init fallito (exit $code)" }
}

function Invoke-TfApply([string]$target = "") {
    Push-Location $TF_DIR
    if ($target -ne "") {
        terraform apply @TF_VAR_ARGS -target $target -auto-approve
    } else {
        terraform apply @TF_VAR_ARGS
    }
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { throw "terraform apply fallito (exit $code)" }
}

function Invoke-ImagePush {
    $ecrUrl = Assert-TfOutput "ecr_repository_url" "Esegui prima: terraform apply -target aws_ecr_repository.app"

    Write-Host ""
    Write-Host "==> ECR login" -ForegroundColor Cyan
    # Usa cmd /c per il pipe nativo — PowerShell mangia il token se lo passa via oggetti
    cmd /c "aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ecrUrl"
    if ($LASTEXITCODE -ne 0) { throw "ECR login fallito. Verifica che le credenziali AWS abbiano permessi ECR." }

    Write-Host ""
    Write-Host "==> Docker build (linux/amd64)" -ForegroundColor Cyan
    docker buildx build --platform linux/amd64 --provenance=false -t "${APP_NAME}:latest" .
    if ($LASTEXITCODE -ne 0) { throw "docker build fallito. Docker Desktop e' avviato?" }

    Write-Host ""
    Write-Host "==> Docker push" -ForegroundColor Cyan
    docker tag "${APP_NAME}:latest" "${ecrUrl}:latest"
    docker push "${ecrUrl}:latest"
    if ($LASTEXITCODE -ne 0) { throw "docker push fallito" }

    return $ecrUrl
}

function Invoke-LambdaUpdate([string]$ecrUrl) {
    $lambdaFn = Assert-TfOutput "lambda_function_name" ""
    Write-Host ""
    Write-Host "==> Aggiorno Lambda image" -ForegroundColor Cyan
    aws lambda update-function-code `
        --function-name $lambdaFn `
        --image-uri "${ecrUrl}:latest" `
        --region $REGION | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "lambda update-function-code fallito" }
    Write-Host "    Lambda aggiornata."
}

function Invoke-UploadStatic {
    $bucket = Assert-TfOutput "s3_bucket_name" "Esegui prima terraform apply."

    Write-Host ""
    Write-Host "==> Upload static files su S3" -ForegroundColor Cyan
    aws s3 sync frontend/static "s3://$bucket/static" --delete
    if ($LASTEXITCODE -ne 0) { throw "s3 sync fallito" }
    aws s3 cp frontend/index.html "s3://$bucket/index.html"
    aws s3 cp frontend/login.html "s3://$bucket/login.html"
    aws s3 cp frontend/analisi.html "s3://$bucket/analisi.html"
    aws s3 cp frontend/rendimenti.html "s3://$bucket/rendimenti.html"
    Write-Host "    File caricati su s3://$bucket"
}

# ── Commands ──────────────────────────────────────────────────────────────────

if ($Command -ne "first-deploy") { Select-TfWorkspace }

switch ($Command) {

    "tf-plan" {
        Push-Location $TF_DIR
        terraform plan @TF_VAR_ARGS
        Pop-Location
    }

    "tf-apply" {
        Invoke-TfApply
    }

    "outputs" {
        Push-Location $TF_DIR
        terraform output
        Pop-Location
    }

    "image-push" {
        # NB: non catturare Invoke-ImagePush in una variabile — l'output di docker
        # finirebbe nel valore di ritorno. L'URL ECR si rilegge pulito da Terraform.
        Invoke-ImagePush
        $url = Assert-TfOutput "ecr_repository_url" ""
        Invoke-LambdaUpdate $url
    }

    "upload-static" {
        Invoke-UploadStatic
    }

    "set-app-url" {
        $cfUrl    = Assert-TfOutput "cloudfront_url" ""
        $lambdaFn = Assert-TfOutput "lambda_function_name" ""
        Write-Host ""
        Write-Host "==> Imposto APP_URL=$cfUrl su Lambda" -ForegroundColor Cyan

        $currentEnvJson = aws lambda get-function-configuration `
            --function-name $lambdaFn `
            --query "Environment.Variables" `
            --output json
        $currentEnv = $currentEnvJson | ConvertFrom-Json

        $envHash = @{}
        $currentEnv.PSObject.Properties | ForEach-Object {
            $envHash[$_.Name] = $_.Value
        }
        $envHash["APP_URL"] = $cfUrl

        $pairs     = $envHash.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }
        $envString = $pairs -join ","

        aws lambda update-function-configuration `
            --function-name $lambdaFn `
            --environment "Variables={$envString}" `
            --region $REGION | Out-Null

        Write-Host "    APP_URL impostato correttamente." -ForegroundColor Green
    }

    "first-deploy" {
        Write-Host ""
        Write-Host "========================================"  -ForegroundColor Yellow
        Write-Host "  PortfolioLab - Primo deploy su AWS"     -ForegroundColor Yellow
        Write-Host "========================================"  -ForegroundColor Yellow

        # Verifica che Docker sia avviato prima di procedere
        docker info 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Docker Desktop non e' in esecuzione. Avvialo e riprova."
        }

        # Step 1: init + crea solo ECR
        Invoke-TfInit
        Select-TfWorkspace
        Write-Host ""
        Write-Host "==> Creo ECR repository..." -ForegroundColor Cyan
        Invoke-TfApply "aws_ecr_repository.app"

        # Step 2: build e push Docker image
        # (non catturare in variabile: l'output di docker inquinerebbe il ritorno)
        Invoke-ImagePush

        # Step 3: deploy tutta l'infrastruttura
        Write-Host ""
        Write-Host "==> Deploy infrastruttura completa..." -ForegroundColor Cyan
        Invoke-TfApply

        # Step 4: upload static files su S3
        Invoke-UploadStatic

        $cfUrl = Assert-TfOutput "cloudfront_url" ""
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "  Deploy completato!" -ForegroundColor Green
        Write-Host "  URL: $cfUrl" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Green
        Write-Host ""
        Write-Host "Prossimo passo:" -ForegroundColor Yellow
        Write-Host "  1. Aggiungi questa riga a terraform/$(if ($Environment -eq "prod") { "terraform.tfvars" } else { "env/$Environment.tfvars" }):" -ForegroundColor Yellow
        Write-Host "     app_url = `"$cfUrl`"" -ForegroundColor White
        Write-Host "  2. Esegui: .\deploy.ps1 set-app-url" -ForegroundColor Yellow
        Write-Host ""
    }

    "deploy" {
        Write-Host ""
        Write-Host "==> Aggiornamento in corso..." -ForegroundColor Cyan
        # NB: non catturare Invoke-ImagePush (l'output di docker inquinerebbe il
        # valore di ritorno); l'URL ECR si rilegge pulito da Terraform.
        Invoke-ImagePush
        $ecrUrl = Assert-TfOutput "ecr_repository_url" ""
        Invoke-LambdaUpdate $ecrUrl
        Invoke-UploadStatic
        $cfUrl = Get-TfOutput "cloudfront_url"
        Write-Host ""
        Write-Host "Deploy completato! App: $cfUrl" -ForegroundColor Green
        Write-Host ""
    }
}
