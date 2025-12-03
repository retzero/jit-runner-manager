#!/bin/bash
# Integration Tests Runner Script
# 로컬 환경에서 통합 테스트를 쉽게 실행하기 위한 스크립트

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LOCAL_INFRA_DIR="${PROJECT_ROOT}/local-infra"

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 로그 함수
log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 사용법
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --all           Run all integration tests"
    echo "  --redis         Run Redis integration tests only"
    echo "  --github        Run GitHub Mock integration tests only"
    echo "  --k8s           Run Kubernetes integration tests only"
    echo "  --e2e           Run End-to-End tests only"
    echo "  --setup         Setup infrastructure only (don't run tests)"
    echo "  --teardown      Teardown infrastructure only"
    echo "  -h, --help      Show this help message"
    echo ""
    echo "Environment variables:"
    echo "  SKIP_INFRA_SETUP    Skip infrastructure setup (default: false)"
    echo "  SKIP_K8S            Skip Kubernetes cluster setup (default: false)"
    echo ""
}

# 인프라 시작
setup_infrastructure() {
    log_info "Setting up test infrastructure..."
    
    # Docker Compose로 Redis와 GitHub Mock 시작
    log_info "Starting Redis and GitHub Mock server..."
    cd "${LOCAL_INFRA_DIR}"
    docker-compose up -d redis github-mock
    
    # 서비스 준비 대기
    log_info "Waiting for services to be ready..."
    for i in {1..30}; do
        if docker-compose exec -T redis redis-cli -a testpassword ping 2>/dev/null | grep -q PONG; then
            log_info "Redis is ready"
            break
        fi
        sleep 1
    done
    
    for i in {1..30}; do
        if curl -s http://localhost:8080/ > /dev/null 2>&1; then
            log_info "GitHub Mock server is ready"
            break
        fi
        sleep 1
    done
    
    # Kubernetes 클러스터 설정 (옵션)
    if [ "${SKIP_K8S}" != "true" ]; then
        log_info "Setting up Kind cluster..."
        "${LOCAL_INFRA_DIR}/kind/setup-cluster.sh" || log_warn "Kind cluster setup failed (may already exist)"
    fi
    
    cd "${PROJECT_ROOT}"
}

# 인프라 종료
teardown_infrastructure() {
    log_info "Tearing down test infrastructure..."
    
    # Docker Compose 종료
    cd "${LOCAL_INFRA_DIR}"
    docker-compose down -v || true
    
    # Kind 클러스터 삭제
    if [ "${SKIP_K8S}" != "true" ]; then
        "${LOCAL_INFRA_DIR}/kind/teardown-cluster.sh" || true
    fi
    
    cd "${PROJECT_ROOT}"
}

# 환경 변수 설정
setup_env() {
    export GHES_URL="${GHES_URL:-http://localhost:8080}"
    export GHES_API_URL="${GHES_API_URL:-http://localhost:8080/api/v3}"
    export GITHUB_PAT="${GITHUB_PAT:-test-integration-token}"
    export WEBHOOK_SECRET="${WEBHOOK_SECRET:-test-webhook-secret}"
    export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
    export REDIS_PASSWORD="${REDIS_PASSWORD:-testpassword}"
    export ADMIN_API_KEY="${ADMIN_API_KEY:-test-admin-key}"
    export APP_URL="${APP_URL:-http://localhost:8000}"
    export RUNNER_NAMESPACE="${RUNNER_NAMESPACE:-jit-runners}"
}

# 테스트 실행
run_tests() {
    local test_target="$1"
    
    cd "${PROJECT_ROOT}"
    setup_env
    
    case "${test_target}" in
        "all")
            log_info "Running all integration tests..."
            python -m pytest tests_integration/ -v --integration --tb=short
            ;;
        "redis")
            log_info "Running Redis integration tests..."
            python -m pytest tests_integration/test_redis_integration.py -v --integration --tb=short
            ;;
        "github")
            log_info "Running GitHub Mock integration tests..."
            python -m pytest tests_integration/test_github_mock_integration.py -v --integration --tb=short
            ;;
        "k8s")
            log_info "Running Kubernetes integration tests..."
            python -m pytest tests_integration/test_kubernetes_integration.py -v --integration --tb=short
            ;;
        "e2e")
            log_info "Running End-to-End tests..."
            # E2E 테스트를 위해 앱 서버 시작
            log_info "Starting application server..."
            uvicorn app.main:app --host 0.0.0.0 --port 8000 &
            APP_PID=$!
            sleep 5
            
            python -m pytest tests_integration/test_end_to_end.py -v --integration --tb=short
            TEST_EXIT_CODE=$?
            
            # 앱 서버 종료
            kill $APP_PID 2>/dev/null || true
            return $TEST_EXIT_CODE
            ;;
        *)
            log_error "Unknown test target: ${test_target}"
            exit 1
            ;;
    esac
}

# 메인 로직
main() {
    local test_target="all"
    local setup_only=false
    local teardown_only=false
    
    # 인자 파싱
    while [[ $# -gt 0 ]]; do
        case $1 in
            --all)
                test_target="all"
                shift
                ;;
            --redis)
                test_target="redis"
                shift
                ;;
            --github)
                test_target="github"
                shift
                ;;
            --k8s)
                test_target="k8s"
                shift
                ;;
            --e2e)
                test_target="e2e"
                shift
                ;;
            --setup)
                setup_only=true
                shift
                ;;
            --teardown)
                teardown_only=true
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done
    
    # 실행
    if [ "${teardown_only}" = true ]; then
        teardown_infrastructure
        exit 0
    fi
    
    if [ "${SKIP_INFRA_SETUP}" != "true" ]; then
        setup_infrastructure
    fi
    
    if [ "${setup_only}" = true ]; then
        log_info "Infrastructure setup complete. Run tests manually."
        exit 0
    fi
    
    # 테스트 실행
    run_tests "${test_target}"
    TEST_EXIT_CODE=$?
    
    # 결과 출력
    if [ $TEST_EXIT_CODE -eq 0 ]; then
        log_info "All tests passed!"
    else
        log_error "Some tests failed!"
    fi
    
    exit $TEST_EXIT_CODE
}

main "$@"
