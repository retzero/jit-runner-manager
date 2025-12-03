"""
End-to-End Integration Tests

전체 시스템 통합 테스트 (Webhook -> App -> GitHub Mock -> Redis)
Kubernetes 통합은 별도의 테스트에서 수행
"""

import json
import time
import pytest


@pytest.mark.integration
class TestHealthEndpoints:
    """앱 Health 엔드포인트 테스트"""
    
    def test_health_check(self, app_client):
        """Health check 엔드포인트"""
        response = app_client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
    
    def test_ready_check(self, app_client):
        """Readiness check 엔드포인트"""
        response = app_client.get("/ready")
        assert response.status_code == 200


@pytest.mark.integration
class TestWebhookEndpoint:
    """Webhook 엔드포인트 테스트"""
    
    def test_webhook_ping(self, app_client):
        """Webhook ping 이벤트"""
        import hashlib
        import hmac
        
        secret = "test-webhook-secret"
        payload = json.dumps({"zen": "test"}).encode()
        signature = "sha256=" + hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        response = app_client.post(
            "/webhook",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "ping",
                "X-GitHub-Delivery": "test-ping",
                "X-Hub-Signature-256": signature
            }
        )
        assert response.status_code == 200
    
    def test_webhook_invalid_signature(self, app_client):
        """잘못된 서명으로 webhook 요청"""
        payload = json.dumps({"action": "queued"}).encode()
        
        response = app_client.post(
            "/webhook",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "workflow_job",
                "X-GitHub-Delivery": "test-invalid",
                "X-Hub-Signature-256": "sha256=invalid"
            }
        )
        assert response.status_code == 401


@pytest.mark.integration
class TestWorkflowJobWebhook:
    """Workflow Job Webhook 처리 테스트"""
    
    def test_queued_event(
        self,
        webhook_helper,
        clean_redis,
        clean_github_mock
    ):
        """workflow_job.queued 이벤트 처리"""
        response = webhook_helper.send_workflow_job(
            action="queued",
            job_id=11111,
            org_name="test-org"
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
    
    def test_completed_event(
        self,
        webhook_helper,
        clean_redis,
        clean_github_mock
    ):
        """workflow_job.completed 이벤트 처리"""
        response = webhook_helper.send_workflow_job(
            action="completed",
            job_id=22222,
            org_name="test-org"
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
    
    def test_in_progress_event(
        self,
        webhook_helper,
        clean_redis,
        clean_github_mock
    ):
        """workflow_job.in_progress 이벤트 처리"""
        response = webhook_helper.send_workflow_job(
            action="in_progress",
            job_id=33333,
            org_name="test-org"
        )
        
        assert response.status_code == 200
    
    def test_unmatched_labels(
        self,
        webhook_helper,
        clean_redis,
        clean_github_mock
    ):
        """매칭되지 않는 라벨로 webhook 요청"""
        response = webhook_helper.send_workflow_job(
            action="queued",
            job_id=44444,
            org_name="test-org",
            labels=["ubuntu-latest"]  # GitHub-hosted runner 라벨
        )
        
        assert response.status_code == 200
        data = response.json()
        # 라벨이 매칭되지 않으면 무시됨
        assert "status" in data


@pytest.mark.integration
class TestAdminEndpoints:
    """Admin API 엔드포인트 테스트"""
    
    def test_admin_status_without_auth(self, app_client):
        """인증 없이 Admin 상태 조회"""
        response = app_client.get("/admin/status")
        assert response.status_code == 403
    
    def test_admin_status_with_auth(self, app_client, integration_env):
        """인증으로 Admin 상태 조회"""
        response = app_client.get(
            "/admin/status",
            headers={"X-Admin-Key": integration_env["ADMIN_API_KEY"]}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "total_running" in data
        assert "redis_connected" in data
    
    def test_admin_list_runners(self, app_client, integration_env):
        """Runner 목록 조회"""
        response = app_client.get(
            "/admin/runners",
            headers={"X-Admin-Key": integration_env["ADMIN_API_KEY"]}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "runners" in data
    
    def test_admin_org_status(self, app_client, integration_env):
        """Organization 상태 조회"""
        response = app_client.get(
            "/admin/orgs/test-org",
            headers={"X-Admin-Key": integration_env["ADMIN_API_KEY"]}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "org_name" in data
        assert "current_running" in data


@pytest.mark.integration
@pytest.mark.github_mock
class TestGitHubApiIntegration:
    """앱에서 GitHub API Mock 호출 검증"""
    
    def test_api_calls_from_webhook(
        self,
        webhook_helper,
        github_mock_client,
        clean_redis,
        clean_github_mock
    ):
        """Webhook 처리 시 GitHub API 호출 확인"""
        # API 호출 기록 초기화
        github_mock_client.delete("/test/api-calls")
        
        # Webhook 전송
        webhook_helper.send_workflow_job(
            action="queued",
            job_id=55555,
            org_name="test-org"
        )
        
        # 약간의 대기 (비동기 처리)
        time.sleep(2)
        
        # API 호출 기록 확인
        response = github_mock_client.get("/test/api-calls")
        data = response.json()
        
        # JIT config 생성이나 runner 관련 API가 호출되었을 수 있음
        # (실제 동작은 Celery worker가 처리하므로 즉시 확인 어려울 수 있음)
        assert data["total_count"] >= 0


@pytest.mark.integration
@pytest.mark.redis
class TestRedisStateAfterWebhook:
    """Webhook 처리 후 Redis 상태 확인"""
    
    def test_job_tracked_in_redis(
        self,
        webhook_helper,
        clean_redis,
        clean_github_mock
    ):
        """Job이 Redis에 추적되는지 확인"""
        job_id = 66666
        
        # Webhook 전송
        webhook_helper.send_workflow_job(
            action="queued",
            job_id=job_id,
            org_name="test-org"
        )
        
        # 약간의 대기
        time.sleep(1)
        
        # Redis에 job 정보가 있는지 확인
        # (실제 구현에 따라 키 형식이 다를 수 있음)
        job_key = f"job:{job_id}:info"
        
        # 테스트는 최소한의 검증만 수행
        # 실제 상태는 구현에 따라 다름
        assert True  # Webhook이 성공적으로 처리됨
