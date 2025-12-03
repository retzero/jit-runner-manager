"""
설정 모듈

환경 변수 및 애플리케이션 설정을 관리합니다.
"""

import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

# .env 파일에서 환경변수 로드 (있는 경우)
load_dotenv()


@dataclass
class GitHubConfig:
    """GitHub Enterprise Server 설정"""
    # GitHub Enterprise Server URL (예: https://github.example.com)
    url: str = field(default_factory=lambda: os.getenv("GHES_URL", ""))
    # GitHub Enterprise Server API URL (예: https://github.example.com/api/v3)
    api_url: str = field(default_factory=lambda: os.getenv("GHES_API_URL", ""))
    # Personal Access Token (admin:org, repo 권한 필요)
    pat: str = field(default_factory=lambda: os.getenv("GITHUB_PAT", ""))
    # Webhook 검증용 Secret
    webhook_secret: str = field(default_factory=lambda: os.getenv("WEBHOOK_SECRET", ""))
    # API 버전
    api_version: str = "2022-11-28"

    def __post_init__(self):
        if not self.url:
            raise ValueError("GHES_URL 환경 변수가 설정되지 않았습니다.")
        if not self.pat:
            raise ValueError("GITHUB_PAT 환경 변수가 설정되지 않았습니다.")
        # URL 끝의 슬래시 제거
        self.url = self.url.rstrip("/")


@dataclass
class RedisConfig:
    """Redis 설정"""
    url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    # Redis 패스워드 (선택사항)
    password: str = field(default_factory=lambda: os.getenv("REDIS_PASSWORD", ""))
    # Key prefix
    prefix: str = "jit-runner"
    # Key TTL (초) - 기본 24시간
    ttl: int = 86400


@dataclass
class KubernetesConfig:
    """Kubernetes 설정"""
    # Runner Pod가 생성될 네임스페이스
    runner_namespace: str = field(
        default_factory=lambda: os.getenv("RUNNER_NAMESPACE", "jit-runners")
    )
    # Runner 이미지
    runner_image: str = field(
        default_factory=lambda: os.getenv(
            "RUNNER_IMAGE", "ghcr.io/actions/actions-runner:latest"
        )
    )
    # DinD 이미지
    dind_image: str = field(
        default_factory=lambda: os.getenv("DIND_IMAGE", "docker:dind")
    )
    # Runner Pod 리소스 설정
    runner_cpu_request: str = "500m"
    runner_cpu_limit: str = "2"
    runner_memory_request: str = "1Gi"
    runner_memory_limit: str = "4Gi"
    # DinD 리소스 설정
    dind_cpu_request: str = "500m"
    dind_cpu_limit: str = "2"
    dind_memory_request: str = "1Gi"
    dind_memory_limit: str = "4Gi"
    # Pod 삭제 대기 시간 (초)
    pod_cleanup_grace_period: int = 30
    # In-cluster 설정 사용 여부
    in_cluster: bool = field(
        default_factory=lambda: os.getenv("KUBERNETES_SERVICE_HOST") is not None
    )


@dataclass
class RunnerConfig:
    """Runner 설정"""
    # Organization당 최대 동시 Runner 수
    max_per_org: int = field(
        default_factory=lambda: int(os.getenv("MAX_RUNNERS_PER_ORG", "10"))
    )
    # 전체 최대 동시 Runner 수
    max_total: int = field(
        default_factory=lambda: int(os.getenv("MAX_TOTAL_RUNNERS", "200"))
    )
    # Runner 라벨 (쉼표로 구분)
    labels: List[str] = field(
        default_factory=lambda: os.getenv("RUNNER_LABELS", "code-linux").split(",")
    )
    # Runner 그룹 (선택사항)
    group: str = field(default_factory=lambda: os.getenv("RUNNER_GROUP", "default"))
    # Runner 이름 prefix
    name_prefix: str = "jit-runner"


@dataclass
class CeleryConfig:
    """Celery 설정"""
    broker_url: str = field(
        default_factory=lambda: os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
    )
    result_backend: str = field(
        default_factory=lambda: os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
    )
    # Task 타임아웃 (초)
    task_timeout: int = 300
    # Worker concurrency
    worker_concurrency: int = field(
        default_factory=lambda: int(os.getenv("CELERY_WORKER_CONCURRENCY", "10"))
    )


@dataclass
class AdminConfig:
    """Admin API 설정"""
    # Admin API Key (X-Admin-Key 헤더로 전달)
    api_key: str = field(default_factory=lambda: os.getenv("ADMIN_API_KEY", ""))
    # Org 제한 설정 파일 경로
    org_limits_file: str = field(
        default_factory=lambda: os.getenv("ORG_LIMITS_FILE", "config/org-limits.yaml")
    )


@dataclass
class AppConfig:
    """애플리케이션 전체 설정"""
    github: GitHubConfig = field(default_factory=GitHubConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    kubernetes: KubernetesConfig = field(default_factory=KubernetesConfig)
    runner: RunnerConfig = field(default_factory=RunnerConfig)
    celery: CeleryConfig = field(default_factory=CeleryConfig)
    admin: AdminConfig = field(default_factory=AdminConfig)
    
    # 애플리케이션 설정
    debug: bool = field(
        default_factory=lambda: os.getenv("DEBUG", "false").lower() == "true"
    )
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))


# 전역 설정 인스턴스 (lazy initialization)
_config: AppConfig = None


def get_config() -> AppConfig:
    """설정 인스턴스를 반환합니다."""
    global _config
    if _config is None:
        _config = AppConfig()
    return _config


def reload_config() -> AppConfig:
    """설정을 다시 로드합니다."""
    global _config
    _config = AppConfig()
    return _config


# Redis Key 생성 헬퍼 함수
class RedisKeys:
    """Redis Key 생성 헬퍼"""
    
    @staticmethod
    def org_running(org_name: str) -> str:
        """Organization의 현재 실행 중인 Runner 수 키"""
        return f"org:{org_name}:running"
    
    @staticmethod
    def org_pending(org_name: str) -> str:
        """Organization의 대기 중인 Job 목록 키"""
        return f"org:{org_name}:pending"
    
    @staticmethod
    def org_max_limit(org_name: str) -> str:
        """Organization의 커스텀 최대 Runner 수 키"""
        return f"org:{org_name}:max_limit"
    
    @staticmethod
    def org_limits_hash() -> str:
        """모든 Organization 커스텀 제한을 저장하는 Hash 키"""
        return "org_limits"
    
    @staticmethod
    def global_total() -> str:
        """전체 실행 중인 Runner 수 키"""
        return "global:total_running"
    
    @staticmethod
    def job_info(job_id: int) -> str:
        """Job 정보 키"""
        return f"job:{job_id}:info"
    
    @staticmethod
    def runner_info(runner_name: str) -> str:
        """Runner 정보 키"""
        return f"runner:{runner_name}:info"

