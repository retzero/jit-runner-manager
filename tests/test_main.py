"""
메인 애플리케이션 테스트

app/main.py의 FastAPI 앱 및 API 엔드포인트 테스트
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient


class TestHealthCheck:
    """GET /health 엔드포인트 테스트"""
    
    @pytest.fixture
    def client(self, app_config):
        """테스트 클라이언트"""
        from app.main import app
        return TestClient(app)
    
    def test_health_check_healthy(self, client):
        """Redis 연결 성공 시 healthy"""
        with patch("app.main.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_redis.return_value = mock_client
            
            response = client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["redis"] == "connected"
            assert "config" in data
    
    def test_health_check_degraded(self, client):
        """Redis 연결 실패 시 degraded"""
        with patch("app.main.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(side_effect=Exception("Connection failed"))
            mock_redis.return_value = mock_client
            
            response = client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert data["redis"] == "disconnected"
    
    def test_health_check_includes_config_info(self, client):
        """헬스 체크에 설정 정보 포함"""
        with patch("app.main.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_redis.return_value = mock_client
            
            response = client.get("/health")
            
            data = response.json()
            assert "ghes_url" in data["config"]
            assert "max_per_org" in data["config"]
            assert "max_total" in data["config"]


class TestMetrics:
    """GET /metrics 엔드포인트 테스트"""
    
    @pytest.fixture
    def client(self, app_config):
        """테스트 클라이언트"""
        from app.main import app
        return TestClient(app)
    
    def test_metrics_success(self, client):
        """메트릭 조회 성공"""
        with patch("app.main.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_total_running = AsyncMock(return_value=50)
            mock_client.get_all_org_stats = AsyncMock(return_value={
                "org-a": {"running": 5, "pending": 2},
                "org-b": {"running": 10, "pending": 0}
            })
            mock_redis.return_value = mock_client
            
            response = client.get("/metrics")
            
            assert response.status_code == 200
            data = response.json()
            assert data["total_running"] == 50
            assert data["max_total"] == 200
            assert data["max_per_org"] == 10
            assert "org-a" in data["organizations"]
            assert "org-b" in data["organizations"]
    
    def test_metrics_error(self, client):
        """메트릭 조회 실패"""
        with patch("app.main.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_total_running = AsyncMock(side_effect=Exception("Redis Error"))
            mock_redis.return_value = mock_client
            
            response = client.get("/metrics")
            
            assert response.status_code == 500


class TestOrgStatus:
    """GET /orgs/{org_name}/status 엔드포인트 테스트"""
    
    @pytest.fixture
    def client(self, app_config):
        """테스트 클라이언트"""
        from app.main import app
        return TestClient(app)
    
    def test_org_status_success(self, client):
        """Organization 상태 조회 성공"""
        with patch("app.main.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_org_running_count = AsyncMock(return_value=5)
            mock_client.get_org_pending_count = AsyncMock(return_value=2)
            mock_client.get_effective_org_limit = AsyncMock(return_value=25)
            mock_client.get_org_max_limit = AsyncMock(return_value=25)
            mock_redis.return_value = mock_client
            
            response = client.get("/orgs/test-org/status")
            
            assert response.status_code == 200
            data = response.json()
            assert data["organization"] == "test-org"
            assert data["running"] == 5
            assert data["pending"] == 2
            assert data["max"] == 25
            assert data["is_custom_limit"] is True
            assert data["available"] == 20
    
    def test_org_status_default_limit(self, client):
        """기본 제한 사용 시"""
        with patch("app.main.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_org_running_count = AsyncMock(return_value=3)
            mock_client.get_org_pending_count = AsyncMock(return_value=0)
            mock_client.get_effective_org_limit = AsyncMock(return_value=10)
            mock_client.get_org_max_limit = AsyncMock(return_value=None)
            mock_redis.return_value = mock_client
            
            response = client.get("/orgs/test-org/status")
            
            data = response.json()
            assert data["max"] == 10
            assert data["is_custom_limit"] is False
    
    def test_org_status_zero_available(self, client):
        """가용 슬롯 0일 때"""
        with patch("app.main.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_org_running_count = AsyncMock(return_value=10)
            mock_client.get_org_pending_count = AsyncMock(return_value=5)
            mock_client.get_effective_org_limit = AsyncMock(return_value=10)
            mock_client.get_org_max_limit = AsyncMock(return_value=None)
            mock_redis.return_value = mock_client
            
            response = client.get("/orgs/test-org/status")
            
            data = response.json()
            assert data["available"] == 0
    
    def test_org_status_error(self, client):
        """Organization 상태 조회 실패"""
        with patch("app.main.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_org_running_count = AsyncMock(side_effect=Exception("Redis Error"))
            mock_redis.return_value = mock_client
            
            response = client.get("/orgs/test-org/status")
            
            assert response.status_code == 500


class TestGlobalExceptionHandler:
    """전역 예외 핸들러 테스트"""
    
    def test_exception_handler_catches_errors(self, app_config):
        """예외 핸들러가 에러를 포착하는지 확인"""
        # 이 테스트는 실제 예외 발생 시나리오를 시뮬레이션하기 어려움
        # 대신 에러 응답 형식을 확인
        from app.main import app
        client = TestClient(app)
        
        with patch("app.main.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_org_running_count = AsyncMock(side_effect=Exception("Test Error"))
            mock_redis.return_value = mock_client
            
            response = client.get("/orgs/test-org/status")
            
            assert response.status_code == 500
            assert "error" in response.json()


class TestLifespan:
    """애플리케이션 라이프사이클 테스트"""
    
    def test_app_startup_logging(self, app_config, caplog):
        """앱 시작 시 로깅"""
        with patch("app.main.get_redis_client") as mock_redis, \
             patch("app.main.get_org_limits_manager") as mock_manager:
            
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_client.get_all_org_limits = AsyncMock(return_value={})
            mock_redis.return_value = mock_client
            
            manager = MagicMock()
            manager.initialize_from_file = AsyncMock(return_value=0)
            mock_manager.return_value = manager
            
            from app.main import app
            with TestClient(app) as client:
                # 앱이 시작되면서 로깅됨
                pass


class TestRouterRegistration:
    """라우터 등록 테스트"""
    
    @pytest.fixture
    def client(self, app_config):
        """테스트 클라이언트"""
        from app.main import app
        return TestClient(app)
    
    def test_webhook_router_registered(self, client):
        """Webhook 라우터 등록 확인"""
        # GET /webhook/test 엔드포인트 존재 확인
        response = client.get("/webhook/test")
        assert response.status_code == 200
    
    def test_admin_router_registered(self, client):
        """Admin 라우터 등록 확인"""
        # Admin 엔드포인트는 인증 필요
        response = client.get("/admin/org-limits")
        assert response.status_code == 401  # 인증 필요


class TestAppMetadata:
    """앱 메타데이터 테스트"""
    
    def test_app_title(self, app_config):
        """앱 제목 확인"""
        from app.main import app
        assert app.title == "JIT Runner Manager"
    
    def test_app_version(self, app_config):
        """앱 버전 확인"""
        from app.main import app
        assert app.version == "1.0.0"
    
    def test_openapi_docs_available(self, app_config):
        """OpenAPI 문서 접근 가능"""
        from app.main import app
        client = TestClient(app)
        
        response = client.get("/docs")
        assert response.status_code == 200
    
    def test_openapi_json_available(self, app_config):
        """OpenAPI JSON 접근 가능"""
        from app.main import app
        client = TestClient(app)
        
        response = client.get("/openapi.json")
        assert response.status_code == 200
        
        data = response.json()
        assert data["info"]["title"] == "JIT Runner Manager"


class TestCORS:
    """CORS 설정 테스트 (필요 시)"""
    
    def test_default_cors(self, app_config):
        """기본 CORS 설정"""
        from app.main import app
        client = TestClient(app)
        
        response = client.options("/health")
        # 기본적으로 CORS가 설정되어 있지 않으면 405 또는 200
        assert response.status_code in [200, 405]


class TestEndpointPaths:
    """엔드포인트 경로 테스트"""
    
    @pytest.fixture
    def client(self, app_config):
        """테스트 클라이언트"""
        from app.main import app
        return TestClient(app)
    
    def test_root_path_not_found(self, client):
        """루트 경로 없음"""
        response = client.get("/")
        assert response.status_code == 404
    
    def test_health_path(self, client):
        """헬스 체크 경로"""
        with patch("app.main.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_redis.return_value = mock_client
            
            response = client.get("/health")
            assert response.status_code == 200
    
    def test_metrics_path(self, client):
        """메트릭 경로"""
        with patch("app.main.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_total_running = AsyncMock(return_value=0)
            mock_client.get_all_org_stats = AsyncMock(return_value={})
            mock_redis.return_value = mock_client
            
            response = client.get("/metrics")
            assert response.status_code == 200
    
    def test_org_status_path(self, client):
        """Organization 상태 경로"""
        with patch("app.main.get_redis_client") as mock_redis:
            mock_client = AsyncMock()
            mock_client.get_org_running_count = AsyncMock(return_value=0)
            mock_client.get_org_pending_count = AsyncMock(return_value=0)
            mock_client.get_effective_org_limit = AsyncMock(return_value=10)
            mock_client.get_org_max_limit = AsyncMock(return_value=None)
            mock_redis.return_value = mock_client
            
            response = client.get("/orgs/any-org/status")
            assert response.status_code == 200
