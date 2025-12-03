"""
Config 모듈 테스트

app/config.py의 설정 클래스 및 헬퍼 함수 테스트
"""

import os
import pytest
from unittest.mock import patch


class TestGitHubConfig:
    """GitHubConfig 테스트"""
    
    def test_github_config_with_valid_env(self, mock_env_vars):
        """유효한 환경 변수로 GitHubConfig 생성"""
        from app.config import GitHubConfig
        
        config = GitHubConfig()
        
        assert config.url == "https://github.example.com"
        assert config.pat == "test-pat-token"
        assert config.webhook_secret == "test-webhook-secret"
        assert config.api_version == "2022-11-28"
    
    def test_github_config_url_trailing_slash_removed(self, monkeypatch):
        """URL 끝 슬래시 제거 확인"""
        monkeypatch.setenv("GHES_URL", "https://github.example.com/")
        monkeypatch.setenv("GITHUB_PAT", "test-token")
        
        from app.config import GitHubConfig
        
        config = GitHubConfig()
        assert config.url == "https://github.example.com"
    
    def test_github_config_missing_url_raises_error(self, monkeypatch):
        """GHES_URL 누락 시 ValueError 발생"""
        monkeypatch.delenv("GHES_URL", raising=False)
        monkeypatch.setenv("GITHUB_PAT", "test-token")
        
        from app.config import GitHubConfig
        
        with pytest.raises(ValueError, match="GHES_URL"):
            GitHubConfig()
    
    def test_github_config_missing_pat_raises_error(self, monkeypatch):
        """GITHUB_PAT 누락 시 ValueError 발생"""
        monkeypatch.setenv("GHES_URL", "https://github.example.com")
        monkeypatch.delenv("GITHUB_PAT", raising=False)
        
        from app.config import GitHubConfig
        
        with pytest.raises(ValueError, match="GITHUB_PAT"):
            GitHubConfig()


class TestRedisConfig:
    """RedisConfig 테스트"""
    
    def test_redis_config_defaults(self, mock_env_vars):
        """RedisConfig 기본값 확인"""
        from app.config import RedisConfig
        
        config = RedisConfig()
        
        assert config.url == "redis://localhost:6379/0"
        assert config.prefix == "jit-runner"
        assert config.ttl == 86400
    
    def test_redis_config_custom_url(self, monkeypatch):
        """커스텀 Redis URL 설정"""
        monkeypatch.setenv("REDIS_URL", "redis://redis.example.com:6380/5")
        
        from app.config import RedisConfig
        
        config = RedisConfig()
        assert config.url == "redis://redis.example.com:6380/5"


class TestRunnerConfig:
    """RunnerConfig 테스트"""
    
    def test_runner_config_defaults(self, mock_env_vars):
        """RunnerConfig 기본값 확인"""
        from app.config import RunnerConfig
        
        config = RunnerConfig()
        
        assert config.max_per_org == 10
        assert config.max_total == 200
        assert config.max_batch_size == 10
        assert config.labels == ["code-linux"]
        assert config.group == "default"
        assert config.name_prefix == "jit-runner"
    
    def test_runner_config_custom_values(self, monkeypatch):
        """RunnerConfig 커스텀 값 설정"""
        monkeypatch.setenv("MAX_RUNNERS_PER_ORG", "50")
        monkeypatch.setenv("MAX_TOTAL_RUNNERS", "500")
        monkeypatch.setenv("MAX_BATCH_SIZE", "20")
        monkeypatch.setenv("RUNNER_LABELS", "label1,label2,label3")
        
        from app.config import RunnerConfig
        
        config = RunnerConfig()
        
        assert config.max_per_org == 50
        assert config.max_total == 500
        assert config.max_batch_size == 20
        assert config.labels == ["label1", "label2", "label3"]


class TestKubernetesConfig:
    """KubernetesConfig 테스트"""
    
    def test_kubernetes_config_defaults(self, mock_env_vars):
        """KubernetesConfig 기본값 확인"""
        from app.config import KubernetesConfig
        
        config = KubernetesConfig()
        
        assert config.runner_namespace == "jit-runners"
        assert config.runner_cpu_request == "500m"
        assert config.runner_memory_request == "1Gi"
        assert config.pod_cleanup_grace_period == 30
    
    def test_kubernetes_config_custom_namespace(self, monkeypatch):
        """커스텀 네임스페이스 설정"""
        monkeypatch.setenv("RUNNER_NAMESPACE", "custom-runners")
        
        from app.config import KubernetesConfig
        
        config = KubernetesConfig()
        assert config.runner_namespace == "custom-runners"


class TestAdminConfig:
    """AdminConfig 테스트"""
    
    def test_admin_config_defaults(self, mock_env_vars):
        """AdminConfig 기본값 확인"""
        from app.config import AdminConfig
        
        config = AdminConfig()
        
        assert config.api_key == "test-admin-key"
        assert config.org_limits_file == "config/org-limits.yaml"
    
    def test_admin_config_empty_api_key(self, monkeypatch):
        """API Key 미설정 시 빈 문자열"""
        monkeypatch.delenv("ADMIN_API_KEY", raising=False)
        
        from app.config import AdminConfig
        
        config = AdminConfig()
        assert config.api_key == ""


class TestAppConfig:
    """AppConfig 테스트"""
    
    def test_app_config_integrates_all_configs(self, app_config):
        """AppConfig가 모든 하위 설정 포함"""
        assert hasattr(app_config, "github")
        assert hasattr(app_config, "redis")
        assert hasattr(app_config, "kubernetes")
        assert hasattr(app_config, "runner")
        assert hasattr(app_config, "celery")
        assert hasattr(app_config, "admin")
    
    def test_app_config_debug_mode(self, monkeypatch, mock_env_vars):
        """DEBUG 모드 설정"""
        monkeypatch.setenv("DEBUG", "true")
        
        import app.config as config_module
        config_module._config = None
        
        from app.config import get_config
        config = get_config()
        
        assert config.debug is True


class TestGetConfig:
    """get_config 함수 테스트"""
    
    def test_get_config_returns_singleton(self, app_config):
        """get_config가 싱글톤 인스턴스 반환"""
        from app.config import get_config
        
        config1 = get_config()
        config2 = get_config()
        
        assert config1 is config2
    
    def test_reload_config_creates_new_instance(self, app_config):
        """reload_config가 새 인스턴스 생성"""
        from app.config import get_config, reload_config
        
        config1 = get_config()
        config2 = reload_config()
        
        assert config1 is not config2


class TestRedisKeys:
    """RedisKeys 헬퍼 클래스 테스트"""
    
    def test_org_running_key(self):
        """Organization running 키 생성"""
        from app.config import RedisKeys
        
        key = RedisKeys.org_running("test-org")
        assert key == "org:test-org:running"
    
    def test_org_pending_key(self):
        """Organization pending 키 생성"""
        from app.config import RedisKeys
        
        key = RedisKeys.org_pending("test-org")
        assert key == "org:test-org:pending"
    
    def test_org_limits_hash_key(self):
        """Organization limits hash 키 생성"""
        from app.config import RedisKeys
        
        key = RedisKeys.org_limits_hash()
        assert key == "org_limits"
    
    def test_global_total_key(self):
        """Global total 키 생성"""
        from app.config import RedisKeys
        
        key = RedisKeys.global_total()
        assert key == "global:total_running"
    
    def test_job_info_key(self):
        """Job info 키 생성"""
        from app.config import RedisKeys
        
        key = RedisKeys.job_info(12345)
        assert key == "job:12345:info"
    
    def test_runner_info_key(self):
        """Runner info 키 생성"""
        from app.config import RedisKeys
        
        key = RedisKeys.runner_info("jit-runner-12345")
        assert key == "runner:jit-runner-12345:info"
