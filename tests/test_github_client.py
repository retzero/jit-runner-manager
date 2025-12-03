"""
GitHub 클라이언트 테스트

app/github_client.py의 GitHubClient 테스트
"""

import pytest
from unittest.mock import MagicMock, patch
import requests


class TestGitHubClient:
    """GitHubClient 테스트"""
    
    @pytest.fixture
    def github_client(self, app_config):
        """테스트용 GitHubClient 인스턴스"""
        from app.github_client import GitHubClient
        return GitHubClient()
    
    # ==================== 초기화 테스트 ====================
    
    def test_init_sets_base_url(self, github_client, app_config):
        """base_url 설정 확인"""
        assert github_client.base_url == app_config.github.api_url
    
    def test_init_sets_headers(self, github_client):
        """헤더 설정 확인"""
        assert "Authorization" in github_client.headers
        assert "Accept" in github_client.headers
        assert "X-GitHub-Api-Version" in github_client.headers
    
    # ==================== _request 메서드 테스트 ====================
    
    def test_request_get_success(self, github_client):
        """GET 요청 성공"""
        with patch("app.github_client.requests.request") as mock_request:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'{"data": "test"}'
            mock_response.json.return_value = {"data": "test"}
            mock_response.raise_for_status = MagicMock()
            mock_request.return_value = mock_response
            
            result = github_client._request("GET", "/test")
            
            assert result == {"data": "test"}
            mock_request.assert_called_once()
    
    def test_request_post_success(self, github_client):
        """POST 요청 성공"""
        with patch("app.github_client.requests.request") as mock_request:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.content = b'{"id": 1}'
            mock_response.json.return_value = {"id": 1}
            mock_response.raise_for_status = MagicMock()
            mock_request.return_value = mock_response
            
            result = github_client._request("POST", "/test", data={"name": "test"})
            
            assert result == {"id": 1}
            call_kwargs = mock_request.call_args.kwargs
            assert call_kwargs["json"] == {"name": "test"}
    
    def test_request_empty_response(self, github_client):
        """빈 응답 처리"""
        with patch("app.github_client.requests.request") as mock_request:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.content = b''
            mock_response.raise_for_status = MagicMock()
            mock_request.return_value = mock_response
            
            result = github_client._request("DELETE", "/test")
            
            assert result == {}
    
    def test_request_http_error(self, github_client):
        """HTTP 에러 처리"""
        with patch("app.github_client.requests.request") as mock_request:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.text = "Not Found"
            mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
                response=mock_response
            )
            mock_request.return_value = mock_response
            
            with pytest.raises(requests.exceptions.HTTPError):
                github_client._request("GET", "/test")
    
    def test_request_connection_error(self, github_client):
        """연결 에러 처리"""
        with patch("app.github_client.requests.request") as mock_request:
            mock_request.side_effect = requests.exceptions.ConnectionError("Connection refused")
            
            with pytest.raises(requests.exceptions.ConnectionError):
                github_client._request("GET", "/test")
    
    # ==================== Organization API 테스트 ====================
    
    def test_get_organization(self, github_client):
        """Organization 정보 조회"""
        with patch.object(github_client, "_request") as mock_request:
            mock_request.return_value = {"login": "test-org", "id": 1}
            
            result = github_client.get_organization("test-org")
            
            assert result["login"] == "test-org"
            mock_request.assert_called_with("GET", "/orgs/test-org")
    
    def test_list_org_runners(self, github_client):
        """Organization Runner 목록 조회"""
        with patch.object(github_client, "_request") as mock_request:
            mock_request.return_value = {
                "total_count": 2,
                "runners": [
                    {"id": 1, "name": "runner-1"},
                    {"id": 2, "name": "runner-2"}
                ]
            }
            
            result = github_client.list_org_runners("test-org")
            
            assert len(result) == 2
            assert result[0]["name"] == "runner-1"
    
    def test_get_runner(self, github_client):
        """특정 Runner 정보 조회"""
        with patch.object(github_client, "_request") as mock_request:
            mock_request.return_value = {"id": 1, "name": "runner-1", "status": "online"}
            
            result = github_client.get_runner("test-org", 1)
            
            assert result["name"] == "runner-1"
            mock_request.assert_called_with("GET", "/orgs/test-org/actions/runners/1")
    
    def test_delete_runner(self, github_client):
        """Runner 삭제"""
        with patch.object(github_client, "_request") as mock_request:
            mock_request.return_value = {}
            
            github_client.delete_runner("test-org", 1)
            
            mock_request.assert_called_with("DELETE", "/orgs/test-org/actions/runners/1")
    
    # ==================== Registration Token 테스트 ====================
    
    def test_create_registration_token(self, github_client):
        """Runner 등록 토큰 생성"""
        with patch.object(github_client, "_request") as mock_request:
            mock_request.return_value = {
                "token": "AABCD1234...",
                "expires_at": "2024-01-01T00:00:00Z"
            }
            
            result = github_client.create_registration_token("test-org")
            
            assert result == "AABCD1234..."
            mock_request.assert_called_with(
                "POST",
                "/orgs/test-org/actions/runners/registration-token"
            )
    
    # ==================== JIT Runner 설정 테스트 ====================
    
    def test_create_jit_runner_config(self, github_client):
        """JIT Runner 설정 생성"""
        with patch.object(github_client, "_request") as mock_request, \
             patch.object(github_client, "_get_runner_group_id") as mock_get_group:
            
            mock_get_group.return_value = 1
            mock_request.return_value = {
                "runner": {"id": 100, "name": "jit-runner-12345"},
                "encoded_jit_config": "base64encodedconfig=="
            }
            
            result = github_client.create_jit_runner_config(
                org_name="test-org",
                runner_name="jit-runner-12345",
                labels=["code-linux"],
                runner_group="default"
            )
            
            assert result["runner_name"] == "jit-runner-12345"
            assert result["runner_id"] == 100
            assert result["encoded_jit_config"] == "base64encodedconfig=="
            assert result["org_name"] == "test-org"
    
    def test_get_runner_group_id_found(self, github_client):
        """Runner 그룹 ID 조회 - 발견"""
        with patch.object(github_client, "_request") as mock_request:
            mock_request.return_value = {
                "runner_groups": [
                    {"id": 1, "name": "default", "default": True},
                    {"id": 2, "name": "custom-group", "default": False}
                ]
            }
            
            result = github_client._get_runner_group_id("test-org", "custom-group")
            
            assert result == 2
    
    def test_get_runner_group_id_fallback_to_default(self, github_client):
        """Runner 그룹 ID 조회 - 기본값 반환"""
        with patch.object(github_client, "_request") as mock_request:
            mock_request.return_value = {
                "runner_groups": [
                    {"id": 1, "name": "default", "default": True}
                ]
            }
            
            result = github_client._get_runner_group_id("test-org", "non-existent")
            
            assert result == 1
    
    def test_get_runner_group_id_not_found(self, github_client):
        """Runner 그룹 ID 조회 - 없음"""
        with patch.object(github_client, "_request") as mock_request:
            mock_request.return_value = {
                "runner_groups": []
            }
            
            with pytest.raises(ValueError, match="Runner 그룹을 찾을 수 없습니다"):
                github_client._get_runner_group_id("test-org", "non-existent")
    
    # ==================== Runner 삭제 (이름으로) 테스트 ====================
    
    def test_remove_runner_by_name_success(self, github_client):
        """이름으로 Runner 삭제 - 성공"""
        with patch.object(github_client, "list_org_runners") as mock_list, \
             patch.object(github_client, "delete_runner") as mock_delete:
            
            mock_list.return_value = [
                {"id": 1, "name": "runner-1"},
                {"id": 2, "name": "jit-runner-12345"}
            ]
            
            result = github_client.remove_runner_by_name("test-org", "jit-runner-12345")
            
            assert result is True
            mock_delete.assert_called_with("test-org", 2)
    
    def test_remove_runner_by_name_not_found(self, github_client):
        """이름으로 Runner 삭제 - 없음"""
        with patch.object(github_client, "list_org_runners") as mock_list:
            mock_list.return_value = [
                {"id": 1, "name": "runner-1"}
            ]
            
            result = github_client.remove_runner_by_name("test-org", "jit-runner-12345")
            
            assert result is False
    
    def test_remove_runner_by_name_error(self, github_client):
        """이름으로 Runner 삭제 - 에러"""
        with patch.object(github_client, "list_org_runners") as mock_list:
            mock_list.side_effect = Exception("API Error")
            
            result = github_client.remove_runner_by_name("test-org", "jit-runner-12345")
            
            assert result is False
    
    # ==================== Workflow API 테스트 ====================
    
    def test_get_workflow_job(self, github_client):
        """Workflow Job 정보 조회"""
        with patch.object(github_client, "_request") as mock_request:
            mock_request.return_value = {
                "id": 12345,
                "run_id": 67890,
                "name": "build",
                "status": "completed"
            }
            
            result = github_client.get_workflow_job("test-org", "test-repo", 12345)
            
            assert result["id"] == 12345
            mock_request.assert_called_with(
                "GET",
                "/repos/test-org/test-repo/actions/jobs/12345"
            )
    
    def test_list_workflow_runs(self, github_client):
        """Workflow Run 목록 조회"""
        with patch.object(github_client, "_request") as mock_request:
            mock_request.return_value = {
                "total_count": 2,
                "workflow_runs": [
                    {"id": 1, "status": "completed"},
                    {"id": 2, "status": "in_progress"}
                ]
            }
            
            result = github_client.list_workflow_runs("test-org", "test-repo")
            
            assert len(result) == 2
    
    def test_list_workflow_runs_with_status_filter(self, github_client):
        """Workflow Run 목록 조회 - 상태 필터"""
        with patch.object(github_client, "_request") as mock_request:
            mock_request.return_value = {
                "workflow_runs": [
                    {"id": 2, "status": "in_progress"}
                ]
            }
            
            github_client.list_workflow_runs("test-org", "test-repo", status="in_progress")
            
            call_args = mock_request.call_args
            assert call_args.kwargs["params"]["status"] == "in_progress"
