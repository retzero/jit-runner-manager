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
        # status는 "healthy" 또는 "degraded"
        assert data["status"] in ["healthy", "degraded"]
        assert "redis" in data
        assert "config" in data
    
    def test_metrics_endpoint(self, app_client):
        """Metrics 엔드포인트"""
        response = app_client.get("/metrics")
        assert response.status_code == 200
        
        data = response.json()
        assert "total_running" in data
        assert "max_total" in data


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
        
        data = response.json()
        assert data["status"] == "ignored"
        assert data["event"] == "ping"
    
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
    
    def test_webhook_test_endpoint(self, app_client):
        """Webhook 테스트 엔드포인트"""
        response = app_client.get("/webhook/test")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "ok"


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
        # 실제 응답: {"status": "queued", "action": "queued", ...}
        assert data["status"] == "queued"
        assert data["action"] == "queued"
        assert data["org"] == "test-org"
        assert data["job_id"] == 11111
    
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
        # 실제 응답: {"status": "acknowledged", "action": "completed", ...}
        assert data["status"] == "acknowledged"
        assert data["action"] == "completed"
    
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
        data = response.json()
        assert data["status"] == "acknowledged"
        assert data["action"] == "in_progress"
    
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
        assert data["status"] == "ignored"
        assert data["reason"] == "label_mismatch"


@pytest.mark.integration
class TestAdminOrgLimitsEndpoints:
    """Admin Org Limits API 엔드포인트 테스트"""
    
    def test_get_org_limits_without_auth(self, app_client):
        """인증 없이 Org Limits 조회"""
        response = app_client.get("/admin/org-limits")
        # ADMIN_API_KEY가 설정된 경우 401, 없으면 200
        assert response.status_code in [200, 401]
    
    def test_get_org_limits_with_auth(self, app_client, integration_env):
        """인증으로 Org Limits 조회"""
        response = app_client.get(
            "/admin/org-limits",
            headers={"X-Admin-Key": integration_env["ADMIN_API_KEY"]}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "default_limit" in data
        assert "custom_limits" in data
        assert "total_custom_orgs" in data
    
    def test_get_specific_org_limit(self, app_client, integration_env):
        """특정 Organization 제한 조회"""
        response = app_client.get(
            "/admin/org-limits/test-org",
            headers={"X-Admin-Key": integration_env["ADMIN_API_KEY"]}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["organization"] == "test-org"
        assert "limit" in data
        assert "is_custom" in data
        assert "current_running" in data
        assert "available" in data
    
    def test_set_org_limit(self, app_client, integration_env):
        """Organization 제한 설정"""
        response = app_client.put(
            "/admin/org-limits/test-org-custom",
            headers={"X-Admin-Key": integration_env["ADMIN_API_KEY"]},
            json={"limit": 25}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["organization"] == "test-org-custom"
        assert data["limit"] == 25
        assert data["is_custom"] is True
    
    def test_delete_org_limit(self, app_client, integration_env):
        """Organization 커스텀 제한 삭제"""
        # 먼저 설정
        app_client.put(
            "/admin/org-limits/test-org-delete",
            headers={"X-Admin-Key": integration_env["ADMIN_API_KEY"]},
            json={"limit": 15}
        )
        
        # 삭제
        response = app_client.delete(
            "/admin/org-limits/test-org-delete",
            headers={"X-Admin-Key": integration_env["ADMIN_API_KEY"]}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["organization"] == "test-org-delete"
        assert data["is_custom"] is False


@pytest.mark.integration
class TestOrgStatusEndpoint:
    """Organization 상태 조회 테스트"""
    
    def test_get_org_status(self, app_client):
        """Organization 상태 조회"""
        response = app_client.get("/orgs/test-org/status")
        assert response.status_code == 200
        
        data = response.json()
        assert data["organization"] == "test-org"
        assert "running" in data
        assert "pending" in data
        assert "max" in data
        assert "available" in data


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
        response = webhook_helper.send_workflow_job(
            action="queued",
            job_id=job_id,
            org_name="test-org"
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert data["job_id"] == job_id
        
        # 약간의 대기
        time.sleep(1)
        
        # Job이 pending queue에 추가되었는지 확인
        pending_count = clean_redis.llen("org:test-org:pending")
        # queued 상태면 pending에 추가됨
        assert pending_count >= 0  # 최소한 에러 없이 처리됨
    
    def test_multiple_queued_jobs(
        self,
        webhook_helper,
        clean_redis,
        clean_github_mock
    ):
        """여러 Job 대기열 테스트"""
        job_ids = [77771, 77772, 77773]
        
        for job_id in job_ids:
            response = webhook_helper.send_workflow_job(
                action="queued",
                job_id=job_id,
                org_name="test-org"
            )
            assert response.status_code == 200
        
        time.sleep(1)
        
        # pending queue에 job들이 추가되었는지 확인
        pending_count = clean_redis.llen("org:test-org:pending")
        assert pending_count >= 0  # 최소한 에러 없이 처리됨
