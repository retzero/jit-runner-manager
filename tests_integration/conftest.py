"""
Integration Test Configuration and Fixtures

통합 테스트를 위한 pytest fixtures 및 설정
실제 Redis, Kubernetes, Mock GitHub API 서버를 사용합니다.
"""

import json
import os
import sys
import time
from typing import Dict, Generator

import httpx
import pytest
import redis

# 프로젝트 루트를 Python path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# Pytest Markers
# =============================================================================

def pytest_configure(config):
    """커스텀 마커 등록"""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (requires external services)"
    )
    config.addinivalue_line(
        "markers", "redis: mark test as requiring Redis"
    )
    config.addinivalue_line(
        "markers", "kubernetes: mark test as requiring Kubernetes cluster"
    )
    config.addinivalue_line(
        "markers", "github_mock: mark test as requiring GitHub Mock server"
    )


def pytest_collection_modifyitems(config, items):
    """
    --integration 옵션이 없으면 integration 테스트 스킵
    """
    if not config.getoption("--integration", default=False):
        skip_integration = pytest.mark.skip(
            reason="Integration tests require --integration option"
        )
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)


def pytest_addoption(parser):
    """커스텀 pytest 옵션 추가"""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests"
    )


# =============================================================================
# Environment Configuration
# =============================================================================

@pytest.fixture(scope="session")
def integration_env() -> Dict[str, str]:
    """통합 테스트용 환경 변수"""
    return {
        "GHES_URL": os.getenv("GHES_URL", "http://localhost:8080"),
        "GHES_API_URL": os.getenv("GHES_API_URL", "http://localhost:8080/api/v3"),
        "GITHUB_PAT": os.getenv("GITHUB_PAT", "test-integration-token"),
        "WEBHOOK_SECRET": os.getenv("WEBHOOK_SECRET", "test-webhook-secret"),
        "REDIS_URL": os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        "REDIS_PASSWORD": os.getenv("REDIS_PASSWORD", "testpassword"),
        "ADMIN_API_KEY": os.getenv("ADMIN_API_KEY", "test-admin-key"),
        "RUNNER_NAMESPACE": os.getenv("RUNNER_NAMESPACE", "jit-runners"),
        "MAX_RUNNERS_PER_ORG": os.getenv("MAX_RUNNERS_PER_ORG", "10"),
        "MAX_TOTAL_RUNNERS": os.getenv("MAX_TOTAL_RUNNERS", "50"),
        "RUNNER_LABELS": os.getenv("RUNNER_LABELS", "code-linux,integration-test"),
    }


@pytest.fixture(scope="session", autouse=True)
def setup_env(integration_env):
    """테스트 전에 환경 변수 설정"""
    for key, value in integration_env.items():
        os.environ[key] = value
    yield
    # 테스트 후 정리 (필요한 경우)


# =============================================================================
# Redis Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def redis_client(integration_env) -> Generator[redis.Redis, None, None]:
    """실제 Redis 클라이언트"""
    client = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        password=integration_env.get("REDIS_PASSWORD"),
        db=0,
        decode_responses=True
    )
    
    # 연결 확인
    max_retries = 10
    for i in range(max_retries):
        try:
            client.ping()
            break
        except redis.ConnectionError:
            if i == max_retries - 1:
                pytest.fail("Redis 서버에 연결할 수 없습니다.")
            time.sleep(1)
    
    yield client
    
    # 테스트 후 정리
    client.close()


@pytest.fixture
def clean_redis(redis_client) -> Generator[redis.Redis, None, None]:
    """각 테스트 전에 Redis 데이터 정리"""
    # 테스트 전 정리
    for key in redis_client.scan_iter("*"):
        redis_client.delete(key)
    
    yield redis_client
    
    # 테스트 후 정리
    for key in redis_client.scan_iter("*"):
        redis_client.delete(key)


# =============================================================================
# GitHub Mock Server Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def github_mock_url(integration_env) -> str:
    """GitHub Mock 서버 URL"""
    return integration_env["GHES_URL"]


@pytest.fixture(scope="session")
def github_mock_api_url(integration_env) -> str:
    """GitHub Mock API URL"""
    return integration_env["GHES_API_URL"]


@pytest.fixture(scope="session")
def github_mock_client(github_mock_url) -> Generator[httpx.Client, None, None]:
    """GitHub Mock 서버 HTTP 클라이언트"""
    client = httpx.Client(base_url=github_mock_url, timeout=30.0)
    
    # 연결 확인
    max_retries = 10
    for i in range(max_retries):
        try:
            response = client.get("/")
            if response.status_code == 200:
                break
        except httpx.ConnectError:
            if i == max_retries - 1:
                pytest.fail("GitHub Mock 서버에 연결할 수 없습니다.")
            time.sleep(1)
    
    yield client
    client.close()


@pytest.fixture
def clean_github_mock(github_mock_client) -> Generator[httpx.Client, None, None]:
    """각 테스트 전에 GitHub Mock 상태 초기화"""
    github_mock_client.post("/test/reset")
    github_mock_client.delete("/test/api-calls")
    yield github_mock_client


# =============================================================================
# Application Client Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def app_url() -> str:
    """JIT Runner Manager 앱 URL"""
    return os.getenv("APP_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def app_client(app_url) -> Generator[httpx.Client, None, None]:
    """JIT Runner Manager HTTP 클라이언트"""
    client = httpx.Client(base_url=app_url, timeout=30.0)
    
    # 연결 확인
    max_retries = 15
    for i in range(max_retries):
        try:
            response = client.get("/health")
            if response.status_code == 200:
                break
        except httpx.ConnectError:
            if i == max_retries - 1:
                pytest.fail("JIT Runner Manager 앱에 연결할 수 없습니다.")
            time.sleep(2)
    
    yield client
    client.close()


# =============================================================================
# Kubernetes Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def k8s_available() -> bool:
    """Kubernetes 클러스터 사용 가능 여부"""
    try:
        from kubernetes import client, config as k8s_config
        
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()
        
        v1 = client.CoreV1Api()
        v1.list_namespace(limit=1)
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def k8s_client(k8s_available):
    """Kubernetes 클라이언트 (사용 가능한 경우)"""
    if not k8s_available:
        pytest.skip("Kubernetes 클러스터를 사용할 수 없습니다.")
    
    from kubernetes import client, config as k8s_config
    
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()
    
    return client.CoreV1Api()


@pytest.fixture
def clean_k8s_namespace(k8s_client, integration_env):
    """테스트용 namespace의 Pod 정리"""
    namespace = integration_env["RUNNER_NAMESPACE"]
    
    # 기존 jit-runner Pod 삭제
    try:
        pods = k8s_client.list_namespaced_pod(
            namespace=namespace,
            label_selector="app=jit-runner"
        )
        for pod in pods.items:
            k8s_client.delete_namespaced_pod(
                name=pod.metadata.name,
                namespace=namespace
            )
    except Exception:
        pass  # namespace가 없으면 무시
    
    yield k8s_client


# =============================================================================
# Webhook Helpers
# =============================================================================

@pytest.fixture
def webhook_helper(app_client, integration_env):
    """Webhook 전송 헬퍼"""
    
    class WebhookHelper:
        def __init__(self):
            self.client = app_client
            self.secret = integration_env["WEBHOOK_SECRET"]
        
        def send_workflow_job(
            self,
            action: str = "queued",
            job_id: int = 12345,
            run_id: int = 67890,
            org_name: str = "test-org",
            repo_name: str = "test-repo",
            labels: list = None
        ) -> httpx.Response:
            """Workflow Job webhook 전송"""
            import hashlib
            import hmac
            
            if labels is None:
                labels = ["code-linux", "integration-test"]
            
            payload = {
                "action": action,
                "workflow_job": {
                    "id": job_id,
                    "run_id": run_id,
                    "name": "build",
                    "labels": labels,
                    "runner_name": None if action == "queued" else f"jit-runner-{job_id}",
                    "conclusion": None if action != "completed" else "success"
                },
                "repository": {
                    "id": 1,
                    "name": repo_name,
                    "full_name": f"{org_name}/{repo_name}",
                    "owner": {
                        "login": org_name,
                        "type": "Organization"
                    }
                },
                "organization": {
                    "login": org_name
                },
                "sender": {
                    "login": "test-user"
                }
            }
            
            payload_bytes = json.dumps(payload).encode()
            signature = "sha256=" + hmac.new(
                self.secret.encode(),
                payload_bytes,
                hashlib.sha256
            ).hexdigest()
            
            return self.client.post(
                "/webhook",
                content=payload_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "workflow_job",
                    "X-GitHub-Delivery": f"test-delivery-{job_id}",
                    "X-Hub-Signature-256": signature
                }
            )
    
    return WebhookHelper()
