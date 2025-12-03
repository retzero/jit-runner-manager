"""
GitHub Mock Server Integration Tests

GitHub Mock API 서버와의 통합 테스트
"""

import base64
import json
import pytest


@pytest.mark.integration
@pytest.mark.github_mock
class TestGitHubMockServer:
    """GitHub Mock 서버 기본 테스트"""
    
    def test_health_check(self, github_mock_client):
        """서버 상태 확인"""
        response = github_mock_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "github-mock"
    
    def test_api_root(self, github_mock_client):
        """API 루트 엔드포인트"""
        response = github_mock_client.get("/api/v3")
        assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.github_mock
class TestOrganizationEndpoints:
    """Organization 관련 엔드포인트 테스트"""
    
    def test_get_existing_organization(self, clean_github_mock):
        """기존 Organization 조회"""
        response = clean_github_mock.get("/api/v3/orgs/test-org")
        assert response.status_code == 200
        
        data = response.json()
        assert data["login"] == "test-org"
        assert data["type"] == "Organization"
    
    def test_get_nonexistent_organization(self, clean_github_mock):
        """존재하지 않는 Organization 조회"""
        response = clean_github_mock.get("/api/v3/orgs/nonexistent-org")
        assert response.status_code == 404
    
    def test_create_test_organization(self, clean_github_mock):
        """테스트용 Organization 생성"""
        response = clean_github_mock.post("/test/organizations/new-test-org")
        assert response.status_code == 200
        
        data = response.json()
        assert data["login"] == "new-test-org"
        
        # 조회 확인
        response = clean_github_mock.get("/api/v3/orgs/new-test-org")
        assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.github_mock
class TestRunnerGroupEndpoints:
    """Runner Group 관련 엔드포인트 테스트"""
    
    def test_list_runner_groups(self, clean_github_mock):
        """Runner 그룹 목록 조회"""
        response = clean_github_mock.get("/api/v3/orgs/test-org/actions/runner-groups")
        assert response.status_code == 200
        
        data = response.json()
        assert data["total_count"] >= 1
        
        # default 그룹이 있어야 함
        default_groups = [g for g in data["runner_groups"] if g["default"]]
        assert len(default_groups) == 1


@pytest.mark.integration
@pytest.mark.github_mock
class TestRunnerEndpoints:
    """Runner 관련 엔드포인트 테스트"""
    
    def test_list_runners_empty(self, clean_github_mock):
        """빈 Runner 목록 조회"""
        response = clean_github_mock.get("/api/v3/orgs/test-org/actions/runners")
        assert response.status_code == 200
        
        data = response.json()
        assert data["total_count"] == 0
        assert data["runners"] == []
    
    def test_create_registration_token(self, clean_github_mock):
        """등록 토큰 생성"""
        response = clean_github_mock.post(
            "/api/v3/orgs/test-org/actions/runners/registration-token"
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "token" in data
        assert data["token"].startswith("AAAAAA")
    
    def test_generate_jit_config(self, clean_github_mock):
        """JIT Config 생성"""
        # Runner 그룹 ID 조회
        groups_response = clean_github_mock.get(
            "/api/v3/orgs/test-org/actions/runner-groups"
        )
        default_group = [
            g for g in groups_response.json()["runner_groups"] 
            if g["default"]
        ][0]
        
        # JIT Config 생성
        response = clean_github_mock.post(
            "/api/v3/orgs/test-org/actions/runners/generate-jitconfig",
            json={
                "name": "jit-runner-test-001",
                "runner_group_id": default_group["id"],
                "labels": ["code-linux", "integration-test"],
                "work_folder": "_work"
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "runner" in data
        assert data["runner"]["name"] == "jit-runner-test-001"
        assert data["runner"]["id"] is not None
        
        # encoded_jit_config 검증
        assert "encoded_jit_config" in data
        decoded = json.loads(base64.b64decode(data["encoded_jit_config"]))
        assert decoded["runner_name"] == "jit-runner-test-001"
        assert decoded["labels"] == ["code-linux", "integration-test"]
    
    def test_list_runners_after_create(self, clean_github_mock):
        """Runner 생성 후 목록 조회"""
        # Runner 그룹 ID 조회
        groups_response = clean_github_mock.get(
            "/api/v3/orgs/test-org/actions/runner-groups"
        )
        default_group = [
            g for g in groups_response.json()["runner_groups"] 
            if g["default"]
        ][0]
        
        # JIT Runner 생성
        clean_github_mock.post(
            "/api/v3/orgs/test-org/actions/runners/generate-jitconfig",
            json={
                "name": "jit-runner-list-test",
                "runner_group_id": default_group["id"],
                "labels": ["code-linux"],
                "work_folder": "_work"
            }
        )
        
        # 목록 조회
        response = clean_github_mock.get("/api/v3/orgs/test-org/actions/runners")
        assert response.status_code == 200
        
        data = response.json()
        assert data["total_count"] >= 1
        
        runner_names = [r["name"] for r in data["runners"]]
        assert "jit-runner-list-test" in runner_names
    
    def test_delete_runner(self, clean_github_mock):
        """Runner 삭제"""
        # Runner 그룹 ID 조회
        groups_response = clean_github_mock.get(
            "/api/v3/orgs/test-org/actions/runner-groups"
        )
        default_group = [
            g for g in groups_response.json()["runner_groups"] 
            if g["default"]
        ][0]
        
        # Runner 생성
        create_response = clean_github_mock.post(
            "/api/v3/orgs/test-org/actions/runners/generate-jitconfig",
            json={
                "name": "jit-runner-delete-test",
                "runner_group_id": default_group["id"],
                "labels": ["code-linux"],
                "work_folder": "_work"
            }
        )
        runner_id = create_response.json()["runner"]["id"]
        
        # Runner 삭제
        response = clean_github_mock.delete(
            f"/api/v3/orgs/test-org/actions/runners/{runner_id}"
        )
        assert response.status_code == 204
        
        # 삭제 확인
        response = clean_github_mock.get(
            f"/api/v3/orgs/test-org/actions/runners/{runner_id}"
        )
        assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.github_mock
class TestApiCallTracking:
    """API 호출 추적 테스트"""
    
    def test_api_calls_are_tracked(self, clean_github_mock):
        """API 호출이 추적되는지 확인"""
        # API 호출 기록 초기화
        clean_github_mock.delete("/test/api-calls")
        
        # 몇 가지 API 호출
        clean_github_mock.get("/api/v3/orgs/test-org")
        clean_github_mock.get("/api/v3/orgs/test-org/actions/runners")
        
        # 호출 기록 확인
        response = clean_github_mock.get("/test/api-calls")
        assert response.status_code == 200
        
        data = response.json()
        assert data["total_count"] == 2
        
        endpoints = [call["endpoint"] for call in data["calls"]]
        assert "/orgs/test-org" in endpoints
        assert "/orgs/test-org/actions/runners" in endpoints


@pytest.mark.integration
@pytest.mark.github_mock
class TestWorkflowJobEndpoints:
    """Workflow Job 관련 엔드포인트 테스트"""
    
    def test_get_default_workflow_job(self, clean_github_mock):
        """기본 Workflow Job 조회"""
        response = clean_github_mock.get(
            "/api/v3/repos/test-org/test-repo/actions/jobs/12345"
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["id"] == 12345
        assert data["status"] == "queued"
    
    def test_set_custom_workflow_job(self, clean_github_mock):
        """커스텀 Workflow Job 설정"""
        # Job 설정
        clean_github_mock.post(
            "/test/workflow-jobs/test-org/test-repo/99999",
            json={
                "run_id": 999990,
                "name": "custom-job",
                "status": "in_progress",
                "labels": ["custom-label"],
                "runner_id": 100,
                "runner_name": "jit-runner-custom"
            }
        )
        
        # Job 조회
        response = clean_github_mock.get(
            "/api/v3/repos/test-org/test-repo/actions/jobs/99999"
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["id"] == 99999
        assert data["name"] == "custom-job"
        assert data["status"] == "in_progress"
        assert data["runner_name"] == "jit-runner-custom"
