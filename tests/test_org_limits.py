"""
Organization 제한 관리 모듈 테스트

app/org_limits.py의 OrgLimitsManager 테스트
"""

import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
import tempfile
import yaml


class TestOrgLimitsManager:
    """OrgLimitsManager 테스트"""
    
    @pytest.fixture
    def org_limits_manager(self, app_config):
        """테스트용 OrgLimitsManager 인스턴스"""
        from app.org_limits import OrgLimitsManager
        return OrgLimitsManager()
    
    # ==================== load_from_file 테스트 ====================
    
    def test_load_from_file_success(self, org_limits_manager):
        """YAML 파일에서 로드 성공"""
        yaml_content = """
org_limits:
  test-org-1: 25
  test-org-2: 50
  test-org-3: 100
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(yaml_content)
            temp_path = f.name
        
        try:
            result = org_limits_manager.load_from_file(temp_path)
            
            assert result == {"test-org-1": 25, "test-org-2": 50, "test-org-3": 100}
        finally:
            os.unlink(temp_path)
    
    def test_load_from_file_not_found(self, org_limits_manager):
        """파일이 없을 때 빈 딕셔너리 반환"""
        result = org_limits_manager.load_from_file("/nonexistent/path.yaml")
        
        assert result == {}
    
    def test_load_from_file_empty(self, org_limits_manager):
        """빈 파일"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write("")
            temp_path = f.name
        
        try:
            result = org_limits_manager.load_from_file(temp_path)
            
            assert result == {}
        finally:
            os.unlink(temp_path)
    
    def test_load_from_file_invalid_yaml(self, org_limits_manager):
        """유효하지 않은 YAML"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write("invalid: yaml: content: [")
            temp_path = f.name
        
        try:
            result = org_limits_manager.load_from_file(temp_path)
            
            assert result == {}
        finally:
            os.unlink(temp_path)
    
    def test_load_from_file_validates_values(self, org_limits_manager):
        """유효하지 않은 값 무시"""
        yaml_content = """
org_limits:
  valid-org: 25
  invalid-org-1: -5
  invalid-org-2: "not a number"
  invalid-org-3: 0
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(yaml_content)
            temp_path = f.name
        
        try:
            result = org_limits_manager.load_from_file(temp_path)
            
            # 유효한 값만 포함
            assert "valid-org" in result
            assert "invalid-org-1" not in result
            assert "invalid-org-2" not in result
            assert "invalid-org-3" not in result
        finally:
            os.unlink(temp_path)
    
    def test_load_from_file_uses_default_path(self, org_limits_manager, monkeypatch):
        """기본 경로 사용"""
        yaml_content = """
org_limits:
  test-org: 25
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "config"
            config_dir.mkdir()
            config_file = config_dir / "org-limits.yaml"
            
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(yaml_content)
            
            # PROJECT_ROOT 환경변수 설정
            monkeypatch.setenv("PROJECT_ROOT", temp_dir)
            
            # 기본 경로 사용
            org_limits_manager.config.admin.org_limits_file = "config/org-limits.yaml"
            
            result = org_limits_manager.load_from_file()
            
            assert result == {"test-org": 25}
    
    # ==================== initialize_from_file 테스트 ====================
    
    @pytest.mark.asyncio
    async def test_initialize_from_file_skips_when_redis_has_data(self, org_limits_manager):
        """Redis에 기존 데이터가 있으면 건너뜀"""
        with patch("app.org_limits.get_redis_client") as mock_get_redis:
            mock_redis = MagicMock()
            mock_redis.get_all_org_limits = AsyncMock(return_value={"existing-org": 10})
            mock_get_redis.return_value = mock_redis
            
            result = await org_limits_manager.initialize_from_file()
            
            assert result == 0
            mock_redis.set_org_limits_bulk.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_initialize_from_file_loads_when_redis_empty(self, org_limits_manager):
        """Redis가 비어있으면 파일에서 로드"""
        yaml_content = """
org_limits:
  test-org: 25
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(yaml_content)
            temp_path = f.name
        
        try:
            with patch("app.org_limits.get_redis_client") as mock_get_redis:
                mock_redis = MagicMock()
                mock_redis.get_all_org_limits = AsyncMock(return_value={})
                mock_redis.set_org_limits_bulk = AsyncMock()
                mock_get_redis.return_value = mock_redis
                
                result = await org_limits_manager.initialize_from_file(temp_path)
                
                assert result == 1
                mock_redis.set_org_limits_bulk.assert_called_once_with({"test-org": 25})
        finally:
            os.unlink(temp_path)
    
    @pytest.mark.asyncio
    async def test_initialize_from_file_returns_zero_when_file_empty(self, org_limits_manager):
        """파일이 비어있으면 0 반환"""
        with patch("app.org_limits.get_redis_client") as mock_get_redis, \
             patch.object(org_limits_manager, "load_from_file", return_value={}):
            
            mock_redis = MagicMock()
            mock_redis.get_all_org_limits = AsyncMock(return_value={})
            mock_get_redis.return_value = mock_redis
            
            result = await org_limits_manager.initialize_from_file()
            
            assert result == 0
    
    # ==================== initialize_from_file_sync 테스트 ====================
    
    def test_initialize_from_file_sync_skips_when_redis_has_data(self, org_limits_manager):
        """동기 버전: Redis에 기존 데이터가 있으면 건너뜀"""
        with patch("app.org_limits.get_redis_client_sync") as mock_get_redis:
            mock_redis = MagicMock()
            mock_redis.get_all_org_limits_sync.return_value = {"existing-org": 10}
            mock_get_redis.return_value = mock_redis
            
            result = org_limits_manager.initialize_from_file_sync()
            
            assert result == 0
    
    def test_initialize_from_file_sync_loads_when_redis_empty(self, org_limits_manager):
        """동기 버전: Redis가 비어있으면 파일에서 로드"""
        yaml_content = """
org_limits:
  test-org-1: 25
  test-org-2: 50
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(yaml_content)
            temp_path = f.name
        
        try:
            with patch("app.org_limits.get_redis_client_sync") as mock_get_redis:
                mock_redis = MagicMock()
                mock_redis.get_all_org_limits_sync.return_value = {}
                mock_get_redis.return_value = mock_redis
                
                result = org_limits_manager.initialize_from_file_sync(temp_path)
                
                assert result == 2
                mock_redis.set_org_limits_bulk_sync.assert_called_once()
        finally:
            os.unlink(temp_path)


class TestGetOrgLimitsManager:
    """get_org_limits_manager 함수 테스트"""
    
    def test_returns_singleton(self, app_config):
        """싱글톤 인스턴스 반환"""
        from app.org_limits import get_org_limits_manager
        
        # 싱글톤 리셋
        import app.org_limits as org_limits_module
        org_limits_module._manager = None
        
        manager1 = get_org_limits_manager()
        manager2 = get_org_limits_manager()
        
        assert manager1 is manager2


class TestOrgLimitsConfigFile:
    """설정 파일 구조 테스트"""
    
    def test_valid_config_structure(self, app_config):
        """유효한 설정 파일 구조"""
        from app.org_limits import OrgLimitsManager
        
        yaml_content = """
# Organization별 커스텀 Runner 제한 설정
# 형식: organization_name: max_runners
# 여기에 지정되지 않은 Organization은 기본값(MAX_RUNNERS_PER_ORG) 사용

org_limits:
  large-team: 50
  medium-team: 25
  small-team: 5
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(yaml_content)
            temp_path = f.name
        
        try:
            manager = OrgLimitsManager()
            result = manager.load_from_file(temp_path)
            
            assert result == {
                "large-team": 50,
                "medium-team": 25,
                "small-team": 5
            }
        finally:
            os.unlink(temp_path)
    
    def test_config_with_no_org_limits_key(self, app_config):
        """org_limits 키가 없는 설정"""
        from app.org_limits import OrgLimitsManager
        
        yaml_content = """
some_other_key:
  test: value
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(yaml_content)
            temp_path = f.name
        
        try:
            manager = OrgLimitsManager()
            result = manager.load_from_file(temp_path)
            
            # org_limits 키가 없으면 빈 딕셔너리 반환
            assert result == {}
        finally:
            os.unlink(temp_path)


class TestOrgLimitsEdgeCases:
    """엣지 케이스 테스트"""
    
    def test_large_org_limit_value(self, app_config):
        """큰 제한 값"""
        from app.org_limits import OrgLimitsManager
        
        yaml_content = """
org_limits:
  large-org: 1000
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(yaml_content)
            temp_path = f.name
        
        try:
            manager = OrgLimitsManager()
            result = manager.load_from_file(temp_path)
            
            assert result["large-org"] == 1000
        finally:
            os.unlink(temp_path)
    
    def test_org_name_with_special_characters(self, app_config):
        """특수 문자가 포함된 Organization 이름"""
        from app.org_limits import OrgLimitsManager
        
        yaml_content = """
org_limits:
  org-with-dash: 25
  org_with_underscore: 30
  org123: 35
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(yaml_content)
            temp_path = f.name
        
        try:
            manager = OrgLimitsManager()
            result = manager.load_from_file(temp_path)
            
            assert "org-with-dash" in result
            assert "org_with_underscore" in result
            assert "org123" in result
        finally:
            os.unlink(temp_path)
    
    def test_unicode_org_names(self, app_config):
        """유니코드 Organization 이름 (비권장이지만 처리 가능)"""
        from app.org_limits import OrgLimitsManager
        
        yaml_content = """
org_limits:
  테스트조직: 25
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(yaml_content)
            temp_path = f.name
        
        try:
            manager = OrgLimitsManager()
            result = manager.load_from_file(temp_path)
            
            assert "테스트조직" in result
            assert result["테스트조직"] == 25
        finally:
            os.unlink(temp_path)
