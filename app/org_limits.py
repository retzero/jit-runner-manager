"""
Organization 제한 관리 모듈

Organization별 커스텀 Runner 제한 설정을 관리합니다.
"""

import logging
import os
from pathlib import Path
from typing import Dict, Optional

import yaml

from app.config import get_config
from app.redis_client import get_redis_client, get_redis_client_sync

logger = logging.getLogger(__name__)


class OrgLimitsManager:
    """Organization 제한 관리자"""
    
    def __init__(self):
        self.config = get_config()
    
    def load_from_file(self, file_path: Optional[str] = None) -> Dict[str, int]:
        """
        YAML 파일에서 Organization 제한 설정을 로드합니다.
        
        Args:
            file_path: 설정 파일 경로 (없으면 기본 경로 사용)
        
        Returns:
            Organization별 제한 딕셔너리
        """
        if file_path is None:
            file_path = self.config.admin.org_limits_file
        
        # 상대 경로인 경우 프로젝트 루트 기준으로 변환
        path = Path(file_path)
        if not path.is_absolute():
            # 환경변수로 프로젝트 루트 지정 가능
            project_root = os.getenv("PROJECT_ROOT", "")
            if project_root:
                path = Path(project_root) / path
        
        if not path.exists():
            logger.warning(f"Organization 제한 설정 파일이 없습니다: {path}")
            return {}
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            
            if data is None:
                logger.warning(f"Organization 제한 설정 파일이 비어있습니다: {path}")
                return {}
            
            org_limits = data.get("org_limits", {})
            
            # 값 검증
            validated_limits = {}
            for org, limit in org_limits.items():
                if isinstance(limit, int) and limit > 0:
                    validated_limits[org] = limit
                else:
                    logger.warning(f"유효하지 않은 제한 값 무시: {org}={limit}")
            
            logger.info(f"Organization 제한 설정 로드 완료: {len(validated_limits)}개 Organization")
            return validated_limits
            
        except yaml.YAMLError as e:
            logger.error(f"YAML 파싱 오류: {e}")
            return {}
        except Exception as e:
            logger.error(f"설정 파일 로드 오류: {e}")
            return {}
    
    async def initialize_from_file(self, file_path: Optional[str] = None) -> int:
        """
        파일에서 설정을 로드하여 Redis에 저장합니다.
        Redis에 기존 설정이 없는 경우에만 적용됩니다.
        
        Args:
            file_path: 설정 파일 경로
        
        Returns:
            로드된 설정 수
        """
        redis_client = get_redis_client()
        
        # 기존 설정 확인
        existing_limits = await redis_client.get_all_org_limits()
        if existing_limits:
            logger.info(f"Redis에 기존 설정이 있습니다 ({len(existing_limits)}개). 파일 로드를 건너뜁니다.")
            return 0
        
        # 파일에서 로드
        limits = self.load_from_file(file_path)
        if not limits:
            return 0
        
        # Redis에 저장
        await redis_client.set_org_limits_bulk(limits)
        logger.info(f"Redis에 Organization 제한 설정 저장 완료: {len(limits)}개")
        
        return len(limits)
    
    def initialize_from_file_sync(self, file_path: Optional[str] = None) -> int:
        """
        파일에서 설정을 로드하여 Redis에 저장합니다 (동기 버전).
        Redis에 기존 설정이 없는 경우에만 적용됩니다.
        
        Args:
            file_path: 설정 파일 경로
        
        Returns:
            로드된 설정 수
        """
        redis_client = get_redis_client_sync()
        
        # 기존 설정 확인
        existing_limits = redis_client.get_all_org_limits_sync()
        if existing_limits:
            logger.info(f"Redis에 기존 설정이 있습니다 ({len(existing_limits)}개). 파일 로드를 건너뜁니다.")
            return 0
        
        # 파일에서 로드
        limits = self.load_from_file(file_path)
        if not limits:
            return 0
        
        # Redis에 저장
        redis_client.set_org_limits_bulk_sync(limits)
        logger.info(f"Redis에 Organization 제한 설정 저장 완료: {len(limits)}개")
        
        return len(limits)


# 싱글톤 인스턴스
_manager: Optional[OrgLimitsManager] = None


def get_org_limits_manager() -> OrgLimitsManager:
    """OrgLimitsManager 인스턴스 반환"""
    global _manager
    if _manager is None:
        _manager = OrgLimitsManager()
    return _manager

