"""
Webhook 핸들러 테스트

app/webhook_handler.py의 Webhook 처리 로직 테스트
"""

import json
import hashlib
import hmac
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient


def calculate_signature(payload_bytes: bytes, secret: str) -> str:
    """Webhook 서명 계산 헬퍼"""
    return "sha256=" + hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()


class TestVerifyWebhookSignature:
    """verify_webhook_signature 함수 테스트"""
    
    def test_valid_signature(self):
        """유효한 서명 검증"""
        from app.webhook_handler import verify_webhook_signature
        
        payload = b'{"test": "data"}'
        secret = "test-secret"
        
        # 올바른 서명 계산
        expected_signature = calculate_signature(payload, secret)
        
        result = verify_webhook_signature(payload, expected_signature, secret)
        
        assert result is True
    
    def test_invalid_signature(self):
        """잘못된 서명 검증"""
        from app.webhook_handler import verify_webhook_signature
        
        payload = b'{"test": "data"}'
        secret = "test-secret"
        invalid_signature = "sha256=invalid_signature"
        
        result = verify_webhook_signature(payload, invalid_signature, secret)
        
        assert result is False
    
    def test_missing_signature(self):
        """서명 누락"""
        from app.webhook_handler import verify_webhook_signature
        
        payload = b'{"test": "data"}'
        secret = "test-secret"
        
        result = verify_webhook_signature(payload, None, secret)
        
        assert result is False
    
    def test_invalid_signature_format(self):
        """잘못된 서명 형식 (sha256= prefix 없음)"""
        from app.webhook_handler import verify_webhook_signature
        
        payload = b'{"test": "data"}'
        secret = "test-secret"
        
        result = verify_webhook_signature(payload, "invalid_format", secret)
        
        assert result is False


class TestWebhookHandler:
    """Webhook 핸들러 엔드포인트 테스트"""
    
    @pytest.fixture
    def client(self, app_config):
        """테스트 클라이언트"""
        from app.main import app
        return TestClient(app)
    
    def _make_signed_request(self, client, payload: dict, event_type: str = "workflow_job"):
        """서명된 요청 생성 헬퍼"""
        payload_bytes = json.dumps(payload).encode()
        signature = calculate_signature(payload_bytes, "test-webhook-secret")
        
        headers = {
            "X-GitHub-Event": event_type,
            "X-GitHub-Delivery": "test-delivery-123",
            "X-Hub-Signature-256": signature,
            "Content-Type": "application/json"
        }
        
        return client.post("/webhook", content=payload_bytes, headers=headers)
    
    # ==================== 서명 검증 테스트 ====================
    
    def test_webhook_invalid_signature_returns_401(self, client, sample_workflow_job_payload):
        """잘못된 서명으로 401 반환"""
        headers = {
            "X-GitHub-Event": "workflow_job",
            "X-GitHub-Delivery": "test-delivery-123",
            "X-Hub-Signature-256": "sha256=invalid",
            "Content-Type": "application/json"
        }
        
        response = client.post(
            "/webhook",
            json=sample_workflow_job_payload,
            headers=headers
        )
        
        assert response.status_code == 401
    
    # ==================== 이벤트 타입 테스트 ====================
    
    def test_webhook_ignores_non_workflow_job_events(self, client, sample_workflow_job_payload):
        """workflow_job 외 이벤트 무시"""
        response = self._make_signed_request(client, sample_workflow_job_payload, "push")
        
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
        assert response.json()["event"] == "push"
    
    # ==================== Organization 확인 테스트 ====================
    
    def test_webhook_ignores_no_organization(self, client):
        """Organization 없는 페이로드 무시"""
        payload = {
            "action": "queued",
            "workflow_job": {
                "id": 12345,
                "run_id": 67890,
                "name": "build",
                "labels": ["code-linux"]
            },
            "repository": {
                "id": 1,
                "name": "test-repo",
                "full_name": "user/test-repo",
                "owner": {
                    "login": "user",
                    "type": "User"  # Organization이 아님
                }
            },
            "sender": {"login": "user"}
        }
        
        response = self._make_signed_request(client, payload)
        
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
        assert response.json()["reason"] == "no_organization"
    
    # ==================== 라벨 확인 테스트 ====================
    
    def test_webhook_ignores_label_mismatch(self, client):
        """지원하지 않는 라벨 무시"""
        payload = {
            "action": "queued",
            "workflow_job": {
                "id": 12345,
                "run_id": 67890,
                "name": "build",
                "labels": ["ubuntu-latest"]  # 지원하지 않는 라벨
            },
            "repository": {
                "id": 1,
                "name": "test-repo",
                "full_name": "test-org/test-repo",
                "owner": {"login": "test-org", "type": "Organization"}
            },
            "organization": {"login": "test-org"},
            "sender": {"login": "user"}
        }
        
        response = self._make_signed_request(client, payload)
        
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
        assert response.json()["reason"] == "label_mismatch"
    
    # ==================== Action 처리 테스트 ====================
    
    def test_webhook_queued_action(self, client, sample_workflow_job_payload):
        """queued 액션 처리"""
        with patch("app.webhook_handler.get_redis_client") as mock_get_redis:
            mock_redis = AsyncMock()
            mock_redis.add_pending_job = AsyncMock()
            mock_get_redis.return_value = mock_redis
            
            response = self._make_signed_request(client, sample_workflow_job_payload)
            
            assert response.status_code == 200
            assert response.json()["status"] == "queued"
            assert response.json()["action"] == "queued"
            mock_redis.add_pending_job.assert_called_once()
    
    def test_webhook_in_progress_action(self, client, create_webhook_payload):
        """in_progress 액션 처리"""
        payload = create_webhook_payload(action="in_progress")
        
        response = self._make_signed_request(client, payload)
        
        assert response.status_code == 200
        assert response.json()["status"] == "acknowledged"
        assert response.json()["action"] == "in_progress"
    
    def test_webhook_completed_action(self, client, create_webhook_payload):
        """completed 액션 처리"""
        payload = create_webhook_payload(action="completed")
        payload["workflow_job"]["conclusion"] = "success"
        
        response = self._make_signed_request(client, payload)
        
        assert response.status_code == 200
        assert response.json()["status"] == "acknowledged"
        assert response.json()["action"] == "completed"
        assert response.json()["conclusion"] == "success"
    
    def test_webhook_unknown_action(self, client, create_webhook_payload):
        """알 수 없는 액션 무시"""
        payload = create_webhook_payload(action="waiting")
        
        response = self._make_signed_request(client, payload)
        
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
        assert response.json()["action"] == "waiting"
    
    # ==================== 에러 처리 테스트 ====================
    
    def test_webhook_invalid_payload(self, client):
        """잘못된 페이로드 형식"""
        payload = {"invalid": "payload"}
        
        response = self._make_signed_request(client, payload)
        
        assert response.status_code == 400


class TestWebhookTestEndpoint:
    """Webhook 테스트 엔드포인트 테스트"""
    
    def test_webhook_test_endpoint(self, app_config):
        """테스트 엔드포인트"""
        from app.main import app
        client = TestClient(app)
        
        response = client.get("/webhook/test")
        
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestWorkflowJobPayload:
    """WorkflowJobPayload 모델 테스트"""
    
    def test_workflow_job_payload_validation(self, sample_workflow_job_payload):
        """페이로드 검증"""
        from app.webhook_handler import WorkflowJobPayload
        
        payload = WorkflowJobPayload(**sample_workflow_job_payload)
        
        assert payload.action == "queued"
        assert payload.workflow_job["id"] == 12345
        assert payload.organization["login"] == "test-org"
    
    def test_workflow_job_payload_without_organization(self):
        """organization 필드 없는 페이로드"""
        from app.webhook_handler import WorkflowJobPayload
        
        payload_data = {
            "action": "queued",
            "workflow_job": {"id": 12345, "run_id": 67890, "name": "build", "labels": []},
            "repository": {"id": 1, "full_name": "org/repo"},
            "sender": {"login": "user"}
        }
        
        payload = WorkflowJobPayload(**payload_data)
        
        assert payload.organization is None
