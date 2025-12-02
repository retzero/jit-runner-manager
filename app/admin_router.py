"""
Admin API 라우터

Organization 제한 관리 및 시스템 관리 API를 제공합니다.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import get_config
from app.redis_client import get_redis_client

logger = logging.getLogger(__name__)
router = APIRouter()


# ==================== 인증 ====================

async def verify_admin_key(x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    """
    Admin API Key 검증
    
    환경변수 ADMIN_API_KEY가 설정된 경우에만 인증을 요구합니다.
    """
    config = get_config()
    
    # API Key가 설정되지 않은 경우 인증 생략 (개발 환경용)
    if not config.admin.api_key:
        logger.warning("ADMIN_API_KEY가 설정되지 않았습니다. 인증이 비활성화됩니다.")
        return True
    
    if not x_admin_key:
        raise HTTPException(
            status_code=401,
            detail="X-Admin-Key 헤더가 필요합니다."
        )
    
    if x_admin_key != config.admin.api_key:
        raise HTTPException(
            status_code=403,
            detail="유효하지 않은 Admin API Key입니다."
        )
    
    return True


# ==================== 요청/응답 모델 ====================

class OrgLimitRequest(BaseModel):
    """Organization 제한 설정 요청"""
    limit: int = Field(..., gt=0, le=1000, description="최대 동시 Runner 수 (1-1000)")


class OrgLimitResponse(BaseModel):
    """Organization 제한 응답"""
    organization: str
    limit: int
    is_custom: bool
    current_running: int
    available: int


class AllOrgLimitsResponse(BaseModel):
    """모든 Organization 제한 응답"""
    default_limit: int
    custom_limits: dict
    total_custom_orgs: int


class OrgLimitUpdateResponse(BaseModel):
    """Organization 제한 업데이트 응답"""
    organization: str
    limit: int
    previous_limit: int
    is_custom: bool
    message: str


# ==================== API 엔드포인트 ====================

@router.get("/org-limits", response_model=AllOrgLimitsResponse)
async def get_all_org_limits(_: bool = Depends(verify_admin_key)):
    """
    모든 Organization의 커스텀 제한 조회
    
    기본 제한값과 커스텀 설정된 Organization 목록을 반환합니다.
    """
    config = get_config()
    redis_client = get_redis_client()
    
    try:
        custom_limits = await redis_client.get_all_org_limits()
        
        return AllOrgLimitsResponse(
            default_limit=config.runner.max_per_org,
            custom_limits=custom_limits,
            total_custom_orgs=len(custom_limits)
        )
    except Exception as e:
        logger.error(f"Organization 제한 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/org-limits/{org_name}", response_model=OrgLimitResponse)
async def get_org_limit(org_name: str, _: bool = Depends(verify_admin_key)):
    """
    특정 Organization의 제한 조회
    
    커스텀 제한이 설정되어 있으면 해당 값을, 없으면 기본값을 반환합니다.
    """
    config = get_config()
    redis_client = get_redis_client()
    
    try:
        custom_limit = await redis_client.get_org_max_limit(org_name)
        effective_limit = custom_limit if custom_limit is not None else config.runner.max_per_org
        is_custom = custom_limit is not None
        
        current_running = await redis_client.get_org_running_count(org_name)
        available = max(0, effective_limit - current_running)
        
        return OrgLimitResponse(
            organization=org_name,
            limit=effective_limit,
            is_custom=is_custom,
            current_running=current_running,
            available=available
        )
    except Exception as e:
        logger.error(f"Organization 제한 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/org-limits/{org_name}", response_model=OrgLimitUpdateResponse)
async def set_org_limit(
    org_name: str,
    request: OrgLimitRequest,
    _: bool = Depends(verify_admin_key)
):
    """
    Organization의 커스텀 제한 설정
    
    기본값과 다른 제한을 설정합니다.
    """
    config = get_config()
    redis_client = get_redis_client()
    
    try:
        # 이전 값 조회
        previous_custom = await redis_client.get_org_max_limit(org_name)
        previous_limit = previous_custom if previous_custom is not None else config.runner.max_per_org
        
        # 새 값 설정
        await redis_client.set_org_max_limit(org_name, request.limit)
        
        logger.info(f"Organization 제한 설정: {org_name} = {request.limit} (이전: {previous_limit})")
        
        return OrgLimitUpdateResponse(
            organization=org_name,
            limit=request.limit,
            previous_limit=previous_limit,
            is_custom=True,
            message=f"커스텀 제한이 설정되었습니다: {request.limit}"
        )
    except Exception as e:
        logger.error(f"Organization 제한 설정 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/org-limits/{org_name}", response_model=OrgLimitUpdateResponse)
async def delete_org_limit(org_name: str, _: bool = Depends(verify_admin_key)):
    """
    Organization의 커스텀 제한 삭제
    
    커스텀 제한을 삭제하고 기본값을 사용하도록 합니다.
    """
    config = get_config()
    redis_client = get_redis_client()
    
    try:
        # 이전 값 조회
        previous_custom = await redis_client.get_org_max_limit(org_name)
        
        if previous_custom is None:
            return OrgLimitUpdateResponse(
                organization=org_name,
                limit=config.runner.max_per_org,
                previous_limit=config.runner.max_per_org,
                is_custom=False,
                message="이미 기본값을 사용 중입니다."
            )
        
        # 커스텀 제한 삭제
        await redis_client.delete_org_max_limit(org_name)
        
        logger.info(f"Organization 커스텀 제한 삭제: {org_name} (이전: {previous_custom})")
        
        return OrgLimitUpdateResponse(
            organization=org_name,
            limit=config.runner.max_per_org,
            previous_limit=previous_custom,
            is_custom=False,
            message=f"커스텀 제한이 삭제되었습니다. 기본값({config.runner.max_per_org}) 사용"
        )
    except Exception as e:
        logger.error(f"Organization 제한 삭제 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 벌크 작업 ====================

class BulkOrgLimitsRequest(BaseModel):
    """벌크 Organization 제한 설정 요청"""
    limits: dict = Field(..., description="Organization별 제한 딕셔너리 (예: {'org-a': 25, 'org-b': 5})")


class BulkOrgLimitsResponse(BaseModel):
    """벌크 Organization 제한 설정 응답"""
    updated: int
    limits: dict
    message: str


@router.put("/org-limits", response_model=BulkOrgLimitsResponse)
async def set_org_limits_bulk(
    request: BulkOrgLimitsRequest,
    _: bool = Depends(verify_admin_key)
):
    """
    여러 Organization의 커스텀 제한 일괄 설정
    
    기존 설정은 유지되며, 요청에 포함된 Organization만 업데이트됩니다.
    """
    redis_client = get_redis_client()
    
    try:
        # 값 검증
        validated_limits = {}
        for org, limit in request.limits.items():
            if isinstance(limit, int) and 0 < limit <= 1000:
                validated_limits[org] = limit
            else:
                logger.warning(f"유효하지 않은 제한 값 무시: {org}={limit}")
        
        if not validated_limits:
            raise HTTPException(
                status_code=400,
                detail="유효한 제한 값이 없습니다."
            )
        
        # 벌크 설정
        await redis_client.set_org_limits_bulk(validated_limits)
        
        logger.info(f"Organization 제한 벌크 설정: {len(validated_limits)}개")
        
        return BulkOrgLimitsResponse(
            updated=len(validated_limits),
            limits=validated_limits,
            message=f"{len(validated_limits)}개 Organization의 제한이 설정되었습니다."
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Organization 제한 벌크 설정 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 설정 파일 리로드 ====================

class ReloadConfigResponse(BaseModel):
    """설정 파일 리로드 응답"""
    loaded: int
    message: str


@router.post("/org-limits/reload", response_model=ReloadConfigResponse)
async def reload_org_limits_from_file(
    force: bool = False,
    _: bool = Depends(verify_admin_key)
):
    """
    설정 파일에서 Organization 제한 다시 로드
    
    Args:
        force: True인 경우 기존 설정을 덮어씁니다.
    """
    from app.org_limits import get_org_limits_manager
    
    redis_client = get_redis_client()
    manager = get_org_limits_manager()
    
    try:
        if force:
            # 강제 리로드: 파일에서 로드하여 덮어쓰기
            limits = manager.load_from_file()
            if limits:
                await redis_client.set_org_limits_bulk(limits)
                logger.info(f"Organization 제한 강제 리로드: {len(limits)}개")
                return ReloadConfigResponse(
                    loaded=len(limits),
                    message=f"{len(limits)}개 Organization 제한이 파일에서 리로드되었습니다."
                )
            else:
                return ReloadConfigResponse(
                    loaded=0,
                    message="설정 파일이 비어있거나 유효한 설정이 없습니다."
                )
        else:
            # 일반 초기화: Redis가 비어있는 경우에만 로드
            loaded = await manager.initialize_from_file()
            if loaded > 0:
                return ReloadConfigResponse(
                    loaded=loaded,
                    message=f"{loaded}개 Organization 제한이 파일에서 로드되었습니다."
                )
            else:
                return ReloadConfigResponse(
                    loaded=0,
                    message="Redis에 기존 설정이 있어 로드를 건너뛰었습니다. force=true로 강제 리로드 가능합니다."
                )
    except Exception as e:
        logger.error(f"설정 파일 리로드 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))

