"""
Admin API 라우터 테스트

app/admin_router.py의 Admin API 엔드포인트 테스트
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient


class TestVerifyAdminKey:
    """verify_admin_key 의존성 테스트"""
    
    @pytest.fixture
    def client(self, app_config):
        """테스트 클라이언트"""
        from app.main import app
        return TestClient(app)
    
    def test_valid_admin_key(self, client):
        """유효한 Admin Key"""
        with patch("app.admin_router.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_all_org_limits = AsyncMock(return_value={})
            mock_redis.return_value = mock_client
            
            response = client.get(
                "/admin/org-limits",
                headers={"X-Admin-Key": "test-admin-key"}
            )
            
            assert response.status_code == 200
    
    def test_invalid_admin_key(self, client):
        """잘못된 Admin Key"""
        response = client.get(
            "/admin/org-limits",
            headers={"X-Admin-Key": "wrong-key"}
        )
        
        assert response.status_code == 403
    
    def test_missing_admin_key(self, client):
        """Admin Key 누락"""
        response = client.get("/admin/org-limits")
        
        assert response.status_code == 401
    
    def test_no_auth_when_admin_key_not_configured(self, monkeypatch):
        """ADMIN_API_KEY 미설정 시 인증 생략"""
        monkeypatch.setenv("ADMIN_API_KEY", "")
        
        # Config 리셋
        import app.config as config_module
        config_module._config = None
        
        from app.main import app
        client = TestClient(app)
        
        with patch("app.admin_router.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_all_org_limits = AsyncMock(return_value={})
            mock_redis.return_value = mock_client
            
            response = client.get("/admin/org-limits")
            
            assert response.status_code == 200


class TestGetAllOrgLimits:
    """GET /admin/org-limits 테스트"""
    
    @pytest.fixture
    def client(self, app_config):
        """테스트 클라이언트"""
        from app.main import app
        return TestClient(app)
    
    def test_get_all_org_limits_empty(self, client):
        """빈 커스텀 제한"""
        with patch("app.admin_router.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_all_org_limits = AsyncMock(return_value={})
            mock_redis.return_value = mock_client
            
            response = client.get(
                "/admin/org-limits",
                headers={"X-Admin-Key": "test-admin-key"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["default_limit"] == 10
            assert data["custom_limits"] == {}
            assert data["total_custom_orgs"] == 0
    
    def test_get_all_org_limits_with_data(self, client):
        """커스텀 제한 있음"""
        with patch("app.admin_router.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_all_org_limits = AsyncMock(return_value={
                "org-a": 25,
                "org-b": 50
            })
            mock_redis.return_value = mock_client
            
            response = client.get(
                "/admin/org-limits",
                headers={"X-Admin-Key": "test-admin-key"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["custom_limits"]["org-a"] == 25
            assert data["custom_limits"]["org-b"] == 50
            assert data["total_custom_orgs"] == 2


class TestGetOrgLimit:
    """GET /admin/org-limits/{org_name} 테스트"""
    
    @pytest.fixture
    def client(self, app_config):
        """테스트 클라이언트"""
        from app.main import app
        return TestClient(app)
    
    def test_get_org_limit_custom(self, client):
        """커스텀 제한 있는 Organization"""
        with patch("app.admin_router.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_org_max_limit = AsyncMock(return_value=25)
            mock_client.get_org_running_count = AsyncMock(return_value=5)
            mock_redis.return_value = mock_client
            
            response = client.get(
                "/admin/org-limits/test-org",
                headers={"X-Admin-Key": "test-admin-key"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["organization"] == "test-org"
            assert data["limit"] == 25
            assert data["is_custom"] is True
            assert data["current_running"] == 5
            assert data["available"] == 20
    
    def test_get_org_limit_default(self, client):
        """기본 제한 사용하는 Organization"""
        with patch("app.admin_router.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_org_max_limit = AsyncMock(return_value=None)
            mock_client.get_org_running_count = AsyncMock(return_value=2)
            mock_redis.return_value = mock_client
            
            response = client.get(
                "/admin/org-limits/test-org",
                headers={"X-Admin-Key": "test-admin-key"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["limit"] == 10  # 기본값
            assert data["is_custom"] is False
            assert data["available"] == 8


class TestSetOrgLimit:
    """PUT /admin/org-limits/{org_name} 테스트"""
    
    @pytest.fixture
    def client(self, app_config):
        """테스트 클라이언트"""
        from app.main import app
        return TestClient(app)
    
    def test_set_org_limit_success(self, client):
        """커스텀 제한 설정 성공"""
        with patch("app.admin_router.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_org_max_limit = AsyncMock(return_value=None)
            mock_client.set_org_max_limit = AsyncMock()
            mock_redis.return_value = mock_client
            
            response = client.put(
                "/admin/org-limits/test-org",
                json={"limit": 50},
                headers={"X-Admin-Key": "test-admin-key"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["organization"] == "test-org"
            assert data["limit"] == 50
            assert data["previous_limit"] == 10  # 기본값
            assert data["is_custom"] is True
    
    def test_set_org_limit_update_existing(self, client):
        """기존 커스텀 제한 업데이트"""
        with patch("app.admin_router.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_org_max_limit = AsyncMock(return_value=25)
            mock_client.set_org_max_limit = AsyncMock()
            mock_redis.return_value = mock_client
            
            response = client.put(
                "/admin/org-limits/test-org",
                json={"limit": 100},
                headers={"X-Admin-Key": "test-admin-key"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["limit"] == 100
            assert data["previous_limit"] == 25
    
    def test_set_org_limit_invalid_value(self, client):
        """유효하지 않은 제한 값"""
        response = client.put(
            "/admin/org-limits/test-org",
            json={"limit": 0},  # 0은 유효하지 않음
            headers={"X-Admin-Key": "test-admin-key"}
        )
        
        assert response.status_code == 422
    
    def test_set_org_limit_exceeds_max(self, client):
        """최대값 초과"""
        response = client.put(
            "/admin/org-limits/test-org",
            json={"limit": 1001},  # 최대 1000
            headers={"X-Admin-Key": "test-admin-key"}
        )
        
        assert response.status_code == 422


class TestDeleteOrgLimit:
    """DELETE /admin/org-limits/{org_name} 테스트"""
    
    @pytest.fixture
    def client(self, app_config):
        """테스트 클라이언트"""
        from app.main import app
        return TestClient(app)
    
    def test_delete_org_limit_success(self, client):
        """커스텀 제한 삭제 성공"""
        with patch("app.admin_router.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_org_max_limit = AsyncMock(return_value=25)
            mock_client.delete_org_max_limit = AsyncMock()
            mock_redis.return_value = mock_client
            
            response = client.delete(
                "/admin/org-limits/test-org",
                headers={"X-Admin-Key": "test-admin-key"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["organization"] == "test-org"
            assert data["limit"] == 10  # 기본값으로 돌아감
            assert data["previous_limit"] == 25
            assert data["is_custom"] is False
    
    def test_delete_org_limit_already_default(self, client):
        """이미 기본값 사용 중"""
        with patch("app.admin_router.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_org_max_limit = AsyncMock(return_value=None)
            mock_redis.return_value = mock_client
            
            response = client.delete(
                "/admin/org-limits/test-org",
                headers={"X-Admin-Key": "test-admin-key"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "이미 기본값" in data["message"]


class TestSetOrgLimitsBulk:
    """PUT /admin/org-limits (bulk) 테스트"""
    
    @pytest.fixture
    def client(self, app_config):
        """테스트 클라이언트"""
        from app.main import app
        return TestClient(app)
    
    def test_set_org_limits_bulk_success(self, client):
        """벌크 설정 성공"""
        with patch("app.admin_router.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.set_org_limits_bulk = AsyncMock()
            mock_redis.return_value = mock_client
            
            response = client.put(
                "/admin/org-limits",
                json={"limits": {"org-a": 25, "org-b": 50}},
                headers={"X-Admin-Key": "test-admin-key"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["updated"] == 2
            assert data["limits"]["org-a"] == 25
            assert data["limits"]["org-b"] == 50
    
    def test_set_org_limits_bulk_filters_invalid(self, client):
        """유효하지 않은 값 필터링"""
        with patch("app.admin_router.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.set_org_limits_bulk = AsyncMock()
            mock_redis.return_value = mock_client
            
            response = client.put(
                "/admin/org-limits",
                json={"limits": {"valid-org": 25, "invalid-org": -5}},
                headers={"X-Admin-Key": "test-admin-key"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["updated"] == 1
            assert "valid-org" in data["limits"]
            assert "invalid-org" not in data["limits"]
    
    def test_set_org_limits_bulk_all_invalid(self, client):
        """모두 유효하지 않은 경우"""
        response = client.put(
            "/admin/org-limits",
            json={"limits": {"org-a": -5, "org-b": 0}},
            headers={"X-Admin-Key": "test-admin-key"}
        )
        
        assert response.status_code == 400


class TestReloadOrgLimitsFromFile:
    """POST /admin/org-limits/reload 테스트"""
    
    @pytest.fixture
    def client(self, app_config):
        """테스트 클라이언트"""
        from app.main import app
        return TestClient(app)
    
    def test_reload_success(self, client):
        """리로드 성공"""
        with patch("app.admin_router.get_redis_client") as mock_redis, \
             patch("app.org_limits.get_org_limits_manager") as mock_manager:
            
            mock_client = AsyncMock()
            mock_redis.return_value = mock_client
            
            manager = MagicMock()
            manager.initialize_from_file = AsyncMock(return_value=5)
            mock_manager.return_value = manager
            
            response = client.post(
                "/admin/org-limits/reload",
                headers={"X-Admin-Key": "test-admin-key"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["loaded"] == 5
    
    def test_reload_force(self, client):
        """강제 리로드"""
        with patch("app.admin_router.get_redis_client") as mock_redis, \
             patch("app.org_limits.get_org_limits_manager") as mock_manager:
            
            mock_client = AsyncMock()
            mock_client.set_org_limits_bulk = AsyncMock()
            mock_redis.return_value = mock_client
            
            manager = MagicMock()
            manager.load_from_file.return_value = {"org-a": 25, "org-b": 50}
            mock_manager.return_value = manager
            
            response = client.post(
                "/admin/org-limits/reload?force=true",
                headers={"X-Admin-Key": "test-admin-key"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["loaded"] == 2
            mock_client.set_org_limits_bulk.assert_called_once()
    
    def test_reload_skips_when_redis_has_data(self, client):
        """Redis에 데이터가 있으면 건너뜀"""
        with patch("app.admin_router.get_redis_client") as mock_redis, \
             patch("app.org_limits.get_org_limits_manager") as mock_manager:
            
            mock_client = AsyncMock()
            mock_redis.return_value = mock_client
            
            manager = MagicMock()
            manager.initialize_from_file = AsyncMock(return_value=0)
            mock_manager.return_value = manager
            
            response = client.post(
                "/admin/org-limits/reload",
                headers={"X-Admin-Key": "test-admin-key"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["loaded"] == 0
            assert "force=true" in data["message"]
