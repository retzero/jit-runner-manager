# Integration Tests Runner Script (PowerShell)
# Windows 환경에서 통합 테스트를 실행하기 위한 스크립트

param(
    [switch]$All,
    [switch]$Redis,
    [switch]$GitHub,
    [switch]$K8s,
    [switch]$E2E,
    [switch]$Setup,
    [switch]$Teardown,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Get-Item "$ScriptDir\..\..").FullName
$LocalInfraDir = "$ProjectRoot\local-infra"

function Write-Info { param($Message) Write-Host "[INFO] $Message" -ForegroundColor Green }
function Write-Warn { param($Message) Write-Host "[WARN] $Message" -ForegroundColor Yellow }
function Write-Err { param($Message) Write-Host "[ERROR] $Message" -ForegroundColor Red }

function Show-Usage {
    Write-Host @"
Usage: .\run-integration-tests.ps1 [OPTIONS]

Options:
  -All           Run all integration tests
  -Redis         Run Redis integration tests only
  -GitHub        Run GitHub Mock integration tests only
  -K8s           Run Kubernetes integration tests only
  -E2E           Run End-to-End tests only
  -Setup         Setup infrastructure only (don't run tests)
  -Teardown      Teardown infrastructure only
  -Help          Show this help message

Environment variables:
  SKIP_INFRA_SETUP    Skip infrastructure setup (default: false)
  SKIP_K8S            Skip Kubernetes cluster setup (default: false)
"@
}

function Setup-Infrastructure {
    Write-Info "Setting up test infrastructure..."
    
    # Docker Compose로 Redis와 GitHub Mock 시작
    Write-Info "Starting Redis and GitHub Mock server..."
    Push-Location $LocalInfraDir
    docker-compose up -d redis github-mock
    
    # 서비스 준비 대기
    Write-Info "Waiting for services to be ready..."
    $maxRetries = 30
    
    for ($i = 0; $i -lt $maxRetries; $i++) {
        try {
            $result = docker-compose exec -T redis redis-cli -a testpassword ping 2>$null
            if ($result -match "PONG") {
                Write-Info "Redis is ready"
                break
            }
        } catch {}
        Start-Sleep -Seconds 1
    }
    
    for ($i = 0; $i -lt $maxRetries; $i++) {
        try {
            $response = Invoke-RestMethod -Uri "http://localhost:8080/" -TimeoutSec 2
            Write-Info "GitHub Mock server is ready"
            break
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    
    # Kind 클러스터 설정 (옵션)
    if ($env:SKIP_K8S -ne "true") {
        Write-Info "Setting up Kind cluster..."
        try {
            kind create cluster --config "$LocalInfraDir\kind\cluster-config.yaml" --name jit-runner-test --wait 120s
            kubectl create namespace jit-runners --context kind-jit-runner-test
        } catch {
            Write-Warn "Kind cluster setup failed (may already exist): $_"
        }
    }
    
    Pop-Location
}

function Teardown-Infrastructure {
    Write-Info "Tearing down test infrastructure..."
    
    # Docker Compose 종료
    Push-Location $LocalInfraDir
    docker-compose down -v 2>$null
    Pop-Location
    
    # Kind 클러스터 삭제
    if ($env:SKIP_K8S -ne "true") {
        try {
            kind delete cluster --name jit-runner-test
        } catch {}
    }
}

function Setup-Env {
    $env:GHES_URL = if ($env:GHES_URL) { $env:GHES_URL } else { "http://localhost:8080" }
    $env:GHES_API_URL = if ($env:GHES_API_URL) { $env:GHES_API_URL } else { "http://localhost:8080/api/v3" }
    $env:GITHUB_PAT = if ($env:GITHUB_PAT) { $env:GITHUB_PAT } else { "test-integration-token" }
    $env:WEBHOOK_SECRET = if ($env:WEBHOOK_SECRET) { $env:WEBHOOK_SECRET } else { "test-webhook-secret" }
    $env:REDIS_URL = if ($env:REDIS_URL) { $env:REDIS_URL } else { "redis://localhost:6379/0" }
    $env:REDIS_PASSWORD = if ($env:REDIS_PASSWORD) { $env:REDIS_PASSWORD } else { "testpassword" }
    $env:ADMIN_API_KEY = if ($env:ADMIN_API_KEY) { $env:ADMIN_API_KEY } else { "test-admin-key" }
    $env:APP_URL = if ($env:APP_URL) { $env:APP_URL } else { "http://localhost:8000" }
    $env:RUNNER_NAMESPACE = if ($env:RUNNER_NAMESPACE) { $env:RUNNER_NAMESPACE } else { "jit-runners" }
}

function Run-Tests {
    param($Target)
    
    Push-Location $ProjectRoot
    Setup-Env
    
    $exitCode = 0
    
    switch ($Target) {
        "all" {
            Write-Info "Running all integration tests..."
            python -m pytest tests_integration/ -v --integration --tb=short
            $exitCode = $LASTEXITCODE
        }
        "redis" {
            Write-Info "Running Redis integration tests..."
            python -m pytest tests_integration/test_redis_integration.py -v --integration --tb=short
            $exitCode = $LASTEXITCODE
        }
        "github" {
            Write-Info "Running GitHub Mock integration tests..."
            python -m pytest tests_integration/test_github_mock_integration.py -v --integration --tb=short
            $exitCode = $LASTEXITCODE
        }
        "k8s" {
            Write-Info "Running Kubernetes integration tests..."
            python -m pytest tests_integration/test_kubernetes_integration.py -v --integration --tb=short
            $exitCode = $LASTEXITCODE
        }
        "e2e" {
            Write-Info "Running End-to-End tests..."
            Write-Info "Starting application server..."
            $appProcess = Start-Process -FilePath "uvicorn" -ArgumentList "app.main:app --host 0.0.0.0 --port 8000" -PassThru -NoNewWindow
            Start-Sleep -Seconds 5
            
            python -m pytest tests_integration/test_end_to_end.py -v --integration --tb=short
            $exitCode = $LASTEXITCODE
            
            Stop-Process -Id $appProcess.Id -Force -ErrorAction SilentlyContinue
        }
    }
    
    Pop-Location
    return $exitCode
}

# 메인 로직
if ($Help) {
    Show-Usage
    exit 0
}

if ($Teardown) {
    Teardown-Infrastructure
    exit 0
}

$testTarget = "all"
if ($Redis) { $testTarget = "redis" }
elseif ($GitHub) { $testTarget = "github" }
elseif ($K8s) { $testTarget = "k8s" }
elseif ($E2E) { $testTarget = "e2e" }

if ($env:SKIP_INFRA_SETUP -ne "true") {
    Setup-Infrastructure
}

if ($Setup) {
    Write-Info "Infrastructure setup complete. Run tests manually."
    exit 0
}

$exitCode = Run-Tests -Target $testTarget

if ($exitCode -eq 0) {
    Write-Info "All tests passed!"
} else {
    Write-Err "Some tests failed!"
}

exit $exitCode
