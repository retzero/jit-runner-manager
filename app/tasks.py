"""
Celery 태스크 정의

Runner 생성, 정리, 유지보수 태스크
"""

import logging
from typing import List, Optional

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError

from app.celery_app import celery_app
from app.config import get_config, RedisKeys
from app.redis_client import get_redis_client_sync
from app.github_client import GitHubClient
from app.k8s_client import KubernetesClient

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def process_workflow_job_queued(
    self,
    org_name: str,
    job_id: int,
    run_id: int,
    job_name: str,
    repo_full_name: str,
    labels: List[str]
):
    """
    workflow_job.queued 이벤트 처리
    
    1. Organization 제한 확인
    2. 전체 제한 확인
    3. JIT Runner 토큰 발급
    4. Kubernetes Pod 생성
    5. Redis 상태 업데이트
    """
    config = get_config()
    redis_client = get_redis_client_sync()
    github_client = GitHubClient()
    k8s_client = KubernetesClient()
    
    logger.info(f"Runner 생성 시작: org={org_name}, job_id={job_id}")
    
    try:
        # 1. Organization 제한 확인 (커스텀 또는 기본값)
        org_running = redis_client.get_org_running_count_sync(org_name)
        org_limit = redis_client.get_effective_org_limit_sync(org_name)
        
        if org_running >= org_limit:
            logger.info(
                f"Organization 제한 도달: org={org_name}, "
                f"running={org_running}, max={org_limit}"
            )
            # 대기열에 추가 (전체 Job 정보 포함)
            redis_client.add_pending_job_sync(
                org_name=org_name,
                job_id=job_id,
                run_id=run_id,
                job_name=job_name,
                repo_full_name=repo_full_name,
                labels=labels
            )
            return {
                "status": "pending",
                "reason": "org_limit_reached",
                "org": org_name,
                "job_id": job_id,
                "current": org_running,
                "limit": org_limit
            }
        
        # 2. 전체 제한 확인
        total_running = redis_client.get_total_running_sync()
        if total_running >= config.runner.max_total:
            logger.info(
                f"전체 제한 도달: total={total_running}, max={config.runner.max_total}"
            )
            # 대기열에 추가 (전체 Job 정보 포함)
            redis_client.add_pending_job_sync(
                org_name=org_name,
                job_id=job_id,
                run_id=run_id,
                job_name=job_name,
                repo_full_name=repo_full_name,
                labels=labels
            )
            return {
                "status": "pending",
                "reason": "total_limit_reached",
                "total": total_running,
                "job_id": job_id
            }
        
        # 3. JIT Runner 토큰 발급
        logger.info(f"JIT Runner 토큰 발급 중: org={org_name}")
        runner_name = f"{config.runner.name_prefix}-{job_id}"
        
        try:
            jit_config = github_client.create_jit_runner_config(
                org_name=org_name,
                runner_name=runner_name,
                labels=config.runner.labels,
                runner_group=config.runner.group
            )
        except Exception as e:
            logger.error(f"JIT Runner 토큰 발급 실패: {e}")
            raise self.retry(exc=e)
        
        # 4. Kubernetes Pod 생성
        logger.info(f"Runner Pod 생성 중: name={runner_name}")
        
        try:
            pod = k8s_client.create_runner_pod(
                runner_name=runner_name,
                org_name=org_name,
                job_id=job_id,
                jit_config=jit_config,
                labels=config.runner.labels
            )
        except Exception as e:
            logger.error(f"Runner Pod 생성 실패: {e}")
            raise self.retry(exc=e)
        
        # 5. Redis 상태 업데이트
        redis_client.increment_org_running_sync(org_name)
        redis_client.increment_total_running_sync()
        
        # Runner 정보 저장
        redis_client.save_runner_info_sync(
            runner_name=runner_name,
            org_name=org_name,
            job_id=job_id,
            run_id=run_id,
            repo_full_name=repo_full_name
        )
        
        logger.info(f"Runner 생성 완료: name={runner_name}, org={org_name}, job_id={job_id}")
        
        return {
            "status": "created",
            "runner_name": runner_name,
            "org": org_name,
            "job_id": job_id
        }
        
    except MaxRetriesExceededError:
        logger.error(f"최대 재시도 횟수 초과: org={org_name}, job_id={job_id}")
        return {
            "status": "failed",
            "reason": "max_retries_exceeded",
            "org": org_name,
            "job_id": job_id
        }
    except Exception as e:
        logger.error(f"Runner 생성 실패: {e}", exc_info=True)
        raise


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def process_workflow_job_completed(
    self,
    org_name: str,
    job_id: int,
    runner_name: str,
    conclusion: str
):
    """
    workflow_job.completed 이벤트 처리
    
    1. Redis 카운터 감소
    2. Runner Pod 삭제
    3. 대기 중인 Job 처리
    """
    config = get_config()
    redis_client = get_redis_client_sync()
    k8s_client = KubernetesClient()
    
    logger.info(
        f"Runner 정리 시작: name={runner_name}, org={org_name}, "
        f"job_id={job_id}, conclusion={conclusion}"
    )
    
    try:
        # 1. Redis 카운터 감소
        redis_client.decrement_org_running_sync(org_name)
        redis_client.decrement_total_running_sync()
        
        # Runner 정보 삭제
        redis_client.delete_runner_info_sync(runner_name)
        
        # 2. Runner Pod 삭제
        try:
            k8s_client.delete_runner_pod(runner_name)
            logger.info(f"Runner Pod 삭제 완료: {runner_name}")
        except Exception as e:
            logger.warning(f"Runner Pod 삭제 실패 (이미 삭제됨?): {e}")
        
        # 3. 대기 중인 Job 처리
        # 같은 Org의 대기열에서 먼저 확인
        pending_job = redis_client.pop_pending_job_sync(org_name)
        if pending_job:
            logger.info(
                f"대기 중인 Job 발견: org={org_name}, "
                f"pending_job_id={pending_job.get('job_id')}"
            )
            # 대기 중인 Job에 대해 Runner 생성 태스크 호출
            process_workflow_job_queued.delay(
                org_name=pending_job.get("org_name"),
                job_id=pending_job.get("job_id"),
                run_id=pending_job.get("run_id"),
                job_name=pending_job.get("job_name"),
                repo_full_name=pending_job.get("repo_full_name"),
                labels=pending_job.get("labels", [])
            )
            logger.info(
                f"대기 중인 Job Runner 생성 요청: "
                f"org={pending_job.get('org_name')}, job_id={pending_job.get('job_id')}"
            )
        
        logger.info(f"Runner 정리 완료: {runner_name}")
        
        return {
            "status": "cleaned",
            "runner_name": runner_name,
            "org": org_name,
            "job_id": job_id
        }
        
    except Exception as e:
        logger.error(f"Runner 정리 실패: {e}", exc_info=True)
        raise self.retry(exc=e)


@celery_app.task
def cleanup_stale_runners():
    """
    오래된/좀비 Runner 정리
    
    주기적으로 실행되어 비정상 종료된 Runner를 정리합니다.
    """
    config = get_config()
    redis_client = get_redis_client_sync()
    k8s_client = KubernetesClient()
    
    logger.info("오래된 Runner 정리 시작")
    
    try:
        # 1. Kubernetes에서 실행 중인 Runner Pod 목록 조회
        running_pods = k8s_client.list_runner_pods()
        running_pod_names = {pod.metadata.name for pod in running_pods}
        
        # 2. Redis에 저장된 Runner 목록 조회
        redis_runners = redis_client.get_all_runners_sync()
        
        # 3. Redis에는 있지만 K8s에는 없는 Runner 정리
        for runner_name, runner_info in redis_runners.items():
            if runner_name not in running_pod_names:
                logger.warning(f"좀비 Runner 발견 (Redis에만 존재): {runner_name}")
                org_name = runner_info.get("org_name")
                if org_name:
                    redis_client.decrement_org_running_sync(org_name)
                    redis_client.decrement_total_running_sync()
                redis_client.delete_runner_info_sync(runner_name)
        
        # 4. Completed/Failed 상태인 Pod 삭제
        for pod in running_pods:
            if pod.status.phase in ["Succeeded", "Failed"]:
                logger.info(f"완료된 Runner Pod 삭제: {pod.metadata.name}")
                try:
                    k8s_client.delete_runner_pod(pod.metadata.name)
                except Exception as e:
                    logger.warning(f"Pod 삭제 실패: {e}")
        
        logger.info("오래된 Runner 정리 완료")
        
    except Exception as e:
        logger.error(f"오래된 Runner 정리 실패: {e}", exc_info=True)


@celery_app.task
def sync_redis_state():
    """
    Redis 상태 동기화
    
    Kubernetes의 실제 상태와 Redis 상태를 동기화합니다.
    """
    config = get_config()
    redis_client = get_redis_client_sync()
    k8s_client = KubernetesClient()
    
    logger.info("Redis 상태 동기화 시작")
    
    try:
        # 1. Kubernetes에서 실행 중인 Runner Pod 조회
        running_pods = k8s_client.list_runner_pods()
        
        # 2. Organization별 카운트 계산
        org_counts = {}
        total_count = 0
        
        for pod in running_pods:
            if pod.status.phase == "Running":
                org_name = pod.metadata.labels.get("org")
                if org_name:
                    org_counts[org_name] = org_counts.get(org_name, 0) + 1
                    total_count += 1
        
        # 3. Redis 상태 업데이트
        # 전체 카운트 동기화
        current_total = redis_client.get_total_running_sync()
        if current_total != total_count:
            logger.warning(
                f"전체 카운트 불일치 수정: Redis={current_total}, K8s={total_count}"
            )
            redis_client.set_total_running_sync(total_count)
        
        # Organization별 카운트 동기화
        for org_name, count in org_counts.items():
            current_org = redis_client.get_org_running_count_sync(org_name)
            if current_org != count:
                logger.warning(
                    f"Org 카운트 불일치 수정: org={org_name}, "
                    f"Redis={current_org}, K8s={count}"
                )
                redis_client.set_org_running_sync(org_name, count)
        
        logger.info(
            f"Redis 상태 동기화 완료: total={total_count}, orgs={len(org_counts)}"
        )
        
    except Exception as e:
        logger.error(f"Redis 상태 동기화 실패: {e}", exc_info=True)

