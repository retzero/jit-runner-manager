"""
GitHub Webhook 핸들러

Enterprise Webhook을 수신하고 처리합니다.
"""

import hashlib
import hmac
import json
import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Header
from pydantic import BaseModel

from app.config import get_config
from app.redis_client import get_redis_client

logger = logging.getLogger(__name__)
router = APIRouter()


class WorkflowJobPayload(BaseModel):
    """Workflow Job Webhook Payload"""
    action: str
    workflow_job: dict
    repository: dict
    organization: Optional[dict] = None
    sender: dict


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    GitHub Webhook 서명을 검증합니다.
    
    Args:
        payload: Request body (bytes)
        signature: X-Hub-Signature-256 헤더 값
        secret: Webhook secret
    
    Returns:
        서명이 유효하면 True
    """
    if not signature or not signature.startswith("sha256="):
        return False
    
    expected_signature = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected_signature)


@router.post("")
async def handle_webhook(
    request: Request,
    x_github_event: str = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
    x_github_delivery: str = Header(None, alias="X-GitHub-Delivery")
):
    """
    GitHub Webhook을 수신하고 처리합니다.
    
    지원 이벤트:
    - workflow_job: Workflow job 상태 변경
    """
    config = get_config()
    
    # Request body 읽기
    body = await request.body()
    
    # 서명 검증 (Webhook secret이 설정된 경우)
    if config.github.webhook_secret:
        if not verify_webhook_signature(body, x_hub_signature_256, config.github.webhook_secret):
            logger.warning(f"Invalid webhook signature. Delivery: {x_github_delivery}")
            raise HTTPException(status_code=401, detail="Invalid signature")
    
    # 이벤트 타입 확인
    if x_github_event != "workflow_job":
        logger.debug(f"Ignoring event: {x_github_event}")
        return {"status": "ignored", "event": x_github_event}
    
    # Payload 파싱
    try:
        payload_dict = json.loads(body)
        payload = WorkflowJobPayload(**payload_dict)
    except Exception as e:
        logger.error(f"Payload 파싱 실패: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")
    
    # Organization 정보 추출
    org_name = None
    if payload.organization:
        org_name = payload.organization.get("login")
    elif payload.repository:
        # Repository owner가 Organization인 경우
        owner = payload.repository.get("owner", {})
        if owner.get("type") == "Organization":
            org_name = owner.get("login")
    
    if not org_name:
        logger.warning(f"Organization을 확인할 수 없습니다. Delivery: {x_github_delivery}")
        return {"status": "ignored", "reason": "no_organization"}
    
    # Workflow Job 정보 추출
    workflow_job = payload.workflow_job
    job_id = workflow_job.get("id")
    job_name = workflow_job.get("name")
    run_id = workflow_job.get("run_id")
    labels = workflow_job.get("labels", [])
    
    logger.info(
        f"Webhook 수신: event={x_github_event}, action={payload.action}, "
        f"org={org_name}, job_id={job_id}, job_name={job_name}, labels={labels}"
    )
    
    # Runner 라벨 확인 (code-linux 라벨이 있는 경우만 처리)
    runner_labels = config.runner.labels
    if not any(label in labels for label in runner_labels):
        logger.debug(f"Runner 라벨 불일치. 요청 라벨: {labels}, 지원 라벨: {runner_labels}")
        return {"status": "ignored", "reason": "label_mismatch"}
    
    # Action에 따라 처리
    if payload.action == "queued":
        # Redis 대기열에 Job 저장 (모든 요청은 일단 대기열로)
        logger.info(f"Job 대기열 추가: org={org_name}, job_id={job_id}")
        
        redis_client = get_redis_client()
        await redis_client.add_pending_job(
            org_name=org_name,
            job_id=job_id,
            run_id=run_id,
            job_name=job_name,
            repo_full_name=payload.repository.get("full_name"),
            labels=labels
        )
        
        logger.info(f"Job 대기열 저장 완료: org={org_name}, job_id={job_id}")
        
        return {
            "status": "queued",
            "action": "queued",
            "org": org_name,
            "job_id": job_id,
            "message": "Job added to pending queue"
        }
    
    elif payload.action == "in_progress":
        # 상태 업데이트 (로깅만)
        runner_name = workflow_job.get("runner_name")
        logger.info(
            f"Job 실행 중: org={org_name}, job_id={job_id}, runner={runner_name}"
        )
        
        return {
            "status": "acknowledged",
            "action": "in_progress",
            "org": org_name,
            "job_id": job_id
        }
    
    elif payload.action == "completed":
        # Runner 정리는 Pod 종료 시 자동 처리 (ephemeral runner)
        # 여기서는 로깅만 수행
        conclusion = workflow_job.get("conclusion")
        runner_name = workflow_job.get("runner_name")
        
        logger.info(
            f"Job 완료 (로깅만): org={org_name}, job_id={job_id}, "
            f"conclusion={conclusion}, runner={runner_name}"
        )
        
        # Ephemeral runner는 자동 종료되므로 별도 처리 불필요
        # Pod 종료 시 sync_redis_state 태스크에서 카운터 갱신
        
        return {
            "status": "acknowledged",
            "action": "completed",
            "org": org_name,
            "job_id": job_id,
            "conclusion": conclusion,
            "message": "Logged only, pod cleanup handled by K8s"
        }
    
    else:
        logger.debug(f"처리하지 않는 action: {payload.action}")
        return {"status": "ignored", "action": payload.action}


@router.get("/test")
async def test_webhook():
    """Webhook 엔드포인트 테스트"""
    return {"status": "ok", "message": "Webhook endpoint is working"}

