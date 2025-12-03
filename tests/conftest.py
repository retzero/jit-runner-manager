"""
테스트 설정 및 공통 fixtures

pytest 전역 fixtures 및 테스트 환경 설정
"""

import os
import sys
import json
import pytest
import asyncio
from typing import Dict, Any, AsyncGenerator, Generator
from unittest.mock import MagicMock, AsyncMock, patch

# 환경 변수 설정 (테스트용)
os.environ.setdefault("GHES_URL", "https://github.example.com")
os.environ.setdefault("GHES_API_URL", "https://github.example.com/api/v3")
os.environ.setdefault("GITHUB_PAT", "test-pat-token")
os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

# 프로젝트 루트를 Python path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# Async Support - 이벤트 루프 재사용
# =============================================================================

@pytest.fixture(scope="session")
def event_loop():
    """세션 스코프의 이벤트 루프 - 모든 테스트에서 재사용"""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


# =============================================================================
# Config Fixtures
# =============================================================================

@pytest.fixture
def mock_env_vars(monkeypatch):
    """테스트용 환경 변수 설정"""
    env_vars = {
        "GHES_URL": "https://github.example.com",
        "GHES_API_URL": "https://github.example.com/api/v3",
        "GITHUB_PAT": "test-pat-token",
        "WEBHOOK_SECRET": "test-webhook-secret",
        "REDIS_URL": "redis://localhost:6379/0",
        "REDIS_PASSWORD": "",
        "MAX_RUNNERS_PER_ORG": "10",
        "MAX_TOTAL_RUNNERS": "200",
        "MAX_BATCH_SIZE": "10",
        "RUNNER_LABELS": "code-linux",
        "RUNNER_GROUP": "default",
        "RUNNER_NAMESPACE": "jit-runners",
        "ADMIN_API_KEY": "test-admin-key",
        "ORG_LIMITS_FILE": "config/org-limits.yaml",
    }
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)
    return env_vars


@pytest.fixture
def app_config(mock_env_vars):
    """테스트용 앱 설정"""
    # Config 모듈의 캐시 초기화
    import app.config as config_module
    config_module._config = None
    
    from app.config import get_config
    return get_config()


# =============================================================================
# Redis Fixtures
# =============================================================================

@pytest.fixture
def mock_redis_client():
    """Mock 비동기 Redis 클라이언트"""
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(return_value=True)
    mock_client.get = AsyncMock(return_value=None)
    mock_client.set = AsyncMock(return_value=True)
    mock_client.incr = AsyncMock(return_value=1)
    mock_client.decr = AsyncMock(return_value=0)
    mock_client.hget = AsyncMock(return_value=None)
    mock_client.hset = AsyncMock(return_value=1)
    mock_client.hgetall = AsyncMock(return_value={})
    mock_client.hdel = AsyncMock(return_value=1)
    mock_client.llen = AsyncMock(return_value=0)
    mock_client.rpush = AsyncMock(return_value=1)
    mock_client.lpop = AsyncMock(return_value=None)
    mock_client.lrange = AsyncMock(return_value=[])
    mock_client.delete = AsyncMock(return_value=1)
    mock_client.expire = AsyncMock(return_value=True)
    mock_client.scan_iter = MagicMock(return_value=iter([]))
    
    return mock_client


@pytest.fixture
def mock_redis_client_sync():
    """Mock 동기 Redis 클라이언트"""
    mock_client = MagicMock()
    mock_client.ping = MagicMock(return_value=True)
    mock_client.get = MagicMock(return_value=None)
    mock_client.set = MagicMock(return_value=True)
    mock_client.incr = MagicMock(return_value=1)
    mock_client.decr = MagicMock(return_value=0)
    mock_client.hget = MagicMock(return_value=None)
    mock_client.hset = MagicMock(return_value=1)
    mock_client.hgetall = MagicMock(return_value={})
    mock_client.hdel = MagicMock(return_value=1)
    mock_client.llen = MagicMock(return_value=0)
    mock_client.rpush = MagicMock(return_value=1)
    mock_client.lpop = MagicMock(return_value=None)
    mock_client.lrange = MagicMock(return_value=[])
    mock_client.delete = MagicMock(return_value=1)
    mock_client.expire = MagicMock(return_value=True)
    mock_client.scan_iter = MagicMock(return_value=iter([]))
    mock_client.pipeline = MagicMock()
    
    return mock_client


# =============================================================================
# GitHub Fixtures
# =============================================================================

@pytest.fixture
def sample_workflow_job_payload():
    """샘플 Workflow Job 페이로드"""
    return {
        "action": "queued",
        "workflow_job": {
            "id": 12345,
            "run_id": 67890,
            "name": "build",
            "labels": ["code-linux"],
            "runner_name": None,
            "conclusion": None
        },
        "repository": {
            "id": 1,
            "name": "test-repo",
            "full_name": "test-org/test-repo",
            "owner": {
                "login": "test-org",
                "type": "Organization"
            }
        },
        "organization": {
            "login": "test-org"
        },
        "sender": {
            "login": "test-user"
        }
    }


@pytest.fixture
def sample_jit_config():
    """샘플 JIT Runner 설정"""
    return {
        "runner_name": "jit-runner-12345",
        "runner_id": 100,
        "encoded_jit_config": "base64encodedconfig==",
        "org_name": "test-org",
        "labels": ["code-linux"]
    }


# =============================================================================
# Kubernetes Fixtures
# =============================================================================

@pytest.fixture
def mock_k8s_client():
    """Mock Kubernetes 클라이언트"""
    mock_client = MagicMock()
    mock_client.enabled = True
    mock_client.namespace = "jit-runners"
    
    # Mock Pod 객체
    mock_pod = MagicMock()
    mock_pod.metadata.name = "jit-runner-12345"
    mock_pod.metadata.labels = {"app": "jit-runner", "org": "test-org", "job-id": "12345"}
    mock_pod.status.phase = "Running"
    
    mock_client.create_runner_pod = MagicMock(return_value=mock_pod)
    mock_client.delete_runner_pod = MagicMock()
    mock_client.get_runner_pod = MagicMock(return_value=mock_pod)
    mock_client.list_runner_pods = MagicMock(return_value=[mock_pod])
    mock_client.get_pod_status = MagicMock(return_value="Running")
    
    return mock_client


@pytest.fixture
def mock_pod():
    """Mock Kubernetes Pod 객체"""
    pod = MagicMock()
    pod.metadata.name = "jit-runner-12345"
    pod.metadata.namespace = "jit-runners"
    pod.metadata.labels = {
        "app": "jit-runner",
        "org": "test-org",
        "job-id": "12345",
        "runner-name": "jit-runner-12345"
    }
    pod.metadata.creation_timestamp = "2024-01-01T00:00:00Z"
    pod.status.phase = "Running"
    return pod


# =============================================================================
# FastAPI Test Client
# =============================================================================

@pytest.fixture
def test_client():
    """FastAPI 테스트 클라이언트"""
    from fastapi.testclient import TestClient
    from app.main import app
    
    with TestClient(app) as client:
        yield client


# =============================================================================
# Webhook Fixtures
# =============================================================================

@pytest.fixture
def webhook_headers():
    """Webhook 요청 헤더"""
    return {
        "X-GitHub-Event": "workflow_job",
        "X-GitHub-Delivery": "test-delivery-id",
        "X-Hub-Signature-256": "",  # 테스트에서 계산 필요
        "Content-Type": "application/json"
    }


def calculate_webhook_signature(payload: bytes, secret: str) -> str:
    """Webhook 서명 계산 헬퍼"""
    import hashlib
    import hmac
    
    signature = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256
    ).hexdigest()
    return signature


# =============================================================================
# Helper Functions
# =============================================================================

@pytest.fixture
def create_webhook_payload():
    """Webhook 페이로드 생성 헬퍼"""
    def _create(
        action: str = "queued",
        job_id: int = 12345,
        run_id: int = 67890,
        org_name: str = "test-org",
        labels: list = None
    ) -> Dict[str, Any]:
        if labels is None:
            labels = ["code-linux"]
        
        return {
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
                "name": "test-repo",
                "full_name": f"{org_name}/test-repo",
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
    
    return _create


# =============================================================================
# Cleanup
# =============================================================================

@pytest.fixture(autouse=True)
def reset_singletons():
    """각 테스트 전에 싱글톤 인스턴스 초기화"""
    # Config 싱글톤 리셋
    try:
        import app.config as config_module
        config_module._config = None
    except ImportError:
        pass
    
    # Redis 클라이언트 싱글톤 리셋
    try:
        import app.redis_client as redis_module
        redis_module._async_client = None
        redis_module._sync_client = None
    except ImportError:
        pass
    
    # OrgLimitsManager 싱글톤 리셋
    try:
        import app.org_limits as org_limits_module
        org_limits_module._manager = None
    except ImportError:
        pass
    
    yield
    
    # 테스트 후에도 정리
    try:
        import app.config as config_module
        config_module._config = None
    except ImportError:
        pass
    
    try:
        import app.redis_client as redis_module
        redis_module._async_client = None
        redis_module._sync_client = None
    except ImportError:
        pass
    
    try:
        import app.org_limits as org_limits_module
        org_limits_module._manager = None
    except ImportError:
        pass
