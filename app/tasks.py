"""
Celery 태스크 정의

Runner 생성, 대기열 처리, 유지보수 태스크
"""

import logging
from typing import List, Optional, Dict

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError

from app.celery_app import celery_app
from app.config import get_config, RedisKeys
from app.redis_client import get_redis_client_sync
from app.github_client import GitHubClient
from app.k8s_client import KubernetesClient

logger = logging.getLogger(__name__)


# =============================================================================
# Runner 생성 태스크
# =============================================================================

@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def create_runner_for_job(
    self,
    org_name: str,
    job_id: int,
    run_id: int,
    job_name: str,
    repo_full_name: str,
    labels: List[str]
):
    """
    Job에 대한 Runner Pod 생성
    
    대기열에서 추출된 Job에 대해 Runner를 생성합니다.
    (제한 확인은 process_pending_queues에서 이미 수행됨)
    
    1. JIT Runner 토큰 발급
    2. Kubernetes Pod 생성
    3. Redis 상태 업데이트
    """
    config = get_config()
    redis_client = get_redis_client_sync()
    github_client = GitHubClient()
    k8s_client = KubernetesClient()
    
    runner_name = f"{config.runner.name_prefix}-{job_id}"
    
    logger.info(f"Runner 생성 시작: org={org_name}, job_id={job_id}, runner={runner_name}")
    
    try:
        # 1. JIT Runner 토큰 발급
        logger.info(f"JIT Runner 토큰 발급 중: org={org_name}")
        
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
        
        # 2. Kubernetes Pod 생성
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
        
        # 3. Redis 상태 업데이트
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


# =============================================================================
# 대기열 처리 태스크 (주기적 실행)
# =============================================================================

@celery_app.task
def process_pending_queues():
    """
    대기열에서 Job을 꺼내 Runner 생성
    
    주기적으로 실행되어:
    1. K8s 상태와 Redis 동기화 (Pod 종료 감지)
    2. 각 Org의 대기열 확인
    3. 여유가 있는 Org의 Job에 대해 Runner 생성
    """
    config = get_config()
    redis_client = get_redis_client_sync()
    k8s_client = KubernetesClient()
    
    logger.info("대기열 처리 시작")
    
    try:
        # 1. K8s 상태와 Redis 동기화 (Pod 종료 감지)
        _sync_running_state(redis_client, k8s_client)
        
        # 2. 현재 전체 실행 중인 수 확인
        total_running = redis_client.get_total_running_sync()
        max_total = config.runner.max_total
        
        if total_running >= max_total:
            logger.info(f"전체 제한 도달: {total_running}/{max_total}, 대기열 처리 건너뜀")
            return {"status": "skipped", "reason": "total_limit_reached"}
        
        # 3. 대기열이 있는 모든 Org 확인
        pending_orgs = _get_orgs_with_pending_jobs(redis_client)
        
        if not pending_orgs:
            logger.debug("대기 중인 Job 없음")
            return {"status": "no_pending_jobs"}
        
        logger.info(f"대기열 있는 Org: {len(pending_orgs)}개")
        
        # 4. 각 Org별로 처리
        created_count = 0
        for org_name in pending_orgs:
            # 전체 제한 재확인
            total_running = redis_client.get_total_running_sync()
            if total_running >= max_total:
                logger.info(f"전체 제한 도달, 처리 중단: {total_running}/{max_total}")
                break
            
            # Org 제한 확인
            org_running = redis_client.get_org_running_count_sync(org_name)
            org_limit = redis_client.get_effective_org_limit_sync(org_name)
            
            if org_running >= org_limit:
                logger.debug(f"Org 제한 도달: {org_name} ({org_running}/{org_limit})")
                continue
            
            # 여유가 있으면 대기열에서 Job 꺼내기
            pending_job = redis_client.pop_pending_job_sync(org_name)
            if pending_job:
                logger.info(
                    f"대기열에서 Job 추출: org={org_name}, job_id={pending_job.get('job_id')}"
                )
                
                # Runner 생성 태스크 호출
                create_runner_for_job.delay(
                    org_name=pending_job.get("org_name"),
                    job_id=pending_job.get("job_id"),
                    run_id=pending_job.get("run_id"),
                    job_name=pending_job.get("job_name"),
                    repo_full_name=pending_job.get("repo_full_name"),
                    labels=pending_job.get("labels", [])
                )
                created_count += 1
        
        logger.info(f"대기열 처리 완료: {created_count}개 Runner 생성 요청")
        
        return {
            "status": "processed",
            "created": created_count
        }
        
    except Exception as e:
        logger.error(f"대기열 처리 실패: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


def _sync_running_state(redis_client, k8s_client):
    """
    K8s 상태와 Redis 상태 동기화
    
    Pod가 종료되면 Redis 카운터를 갱신합니다.
    """
    try:
        # Kubernetes에서 실행 중인 Runner Pod 조회
        running_pods = k8s_client.list_runner_pods()
        
        # Running/Pending 상태인 Pod만 카운트
        org_counts = {}
        total_count = 0
        active_pod_names = set()
        
        for pod in running_pods:
            if pod.status.phase in ["Running", "Pending"]:
                active_pod_names.add(pod.metadata.name)
                org_name = pod.metadata.labels.get("org")
                if org_name:
                    org_counts[org_name] = org_counts.get(org_name, 0) + 1
                    total_count += 1
        
        # 전체 카운트 동기화
        current_total = redis_client.get_total_running_sync()
        if current_total != total_count:
            logger.info(f"전체 카운트 동기화: {current_total} → {total_count}")
            redis_client.set_total_running_sync(total_count)
        
        # Org별 카운트 동기화
        # 먼저 Redis에 기록된 모든 runner 정보 조회
        redis_runners = redis_client.get_all_runners_sync()
        all_orgs = set(org_counts.keys())
        
        for runner_name, runner_info in redis_runners.items():
            org = runner_info.get("org_name")
            if org:
                all_orgs.add(org)
        
        for org_name in all_orgs:
            k8s_count = org_counts.get(org_name, 0)
            redis_count = redis_client.get_org_running_count_sync(org_name)
            if redis_count != k8s_count:
                logger.info(f"Org 카운트 동기화: {org_name} {redis_count} → {k8s_count}")
                redis_client.set_org_running_sync(org_name, k8s_count)
        
        # Redis에는 있지만 K8s에는 없는 Runner 정보 정리
        for runner_name, runner_info in redis_runners.items():
            if runner_name not in active_pod_names:
                logger.info(f"종료된 Runner 정보 삭제: {runner_name}")
                redis_client.delete_runner_info_sync(runner_name)
        
    except Exception as e:
        logger.error(f"상태 동기화 실패: {e}", exc_info=True)


def _get_orgs_with_pending_jobs(redis_client) -> List[str]:
    """
    대기 중인 Job이 있는 Organization 목록 조회
    """
    orgs = []
    try:
        # org:*:pending 패턴으로 대기열 키 검색
        pattern = "org:*:pending"
        for key in redis_client.client.scan_iter(match=pattern):
            key_str = key.decode() if isinstance(key, bytes) else key
            # org:{name}:pending 에서 name 추출
            parts = key_str.split(":")
            if len(parts) >= 2:
                org_name = parts[1]
                # 대기열에 실제 항목이 있는지 확인
                queue_len = redis_client.get_pending_job_count_sync(org_name)
                if queue_len > 0:
                    orgs.append(org_name)
    except Exception as e:
        logger.error(f"대기열 Org 목록 조회 실패: {e}")
    
    return orgs


# =============================================================================
# 유지보수 태스크 (주기적 실행)
# =============================================================================

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
        # 1. Kubernetes에서 Runner Pod 목록 조회
        all_pods = k8s_client.list_runner_pods()
        
        # 2. Completed/Failed 상태인 Pod 삭제
        deleted_count = 0
        for pod in all_pods:
            if pod.status.phase in ["Succeeded", "Failed"]:
                logger.info(f"완료된 Runner Pod 삭제: {pod.metadata.name}")
                try:
                    k8s_client.delete_runner_pod(pod.metadata.name)
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Pod 삭제 실패: {e}")
        
        logger.info(f"오래된 Runner 정리 완료: {deleted_count}개 삭제")
        
        return {"status": "completed", "deleted": deleted_count}
        
    except Exception as e:
        logger.error(f"오래된 Runner 정리 실패: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


@celery_app.task
def sync_redis_state():
    """
    Redis 상태 전체 동기화
    
    Kubernetes의 실제 상태와 Redis 상태를 동기화합니다.
    process_pending_queues보다 더 철저한 정리를 수행합니다.
    """
    config = get_config()
    redis_client = get_redis_client_sync()
    k8s_client = KubernetesClient()
    
    logger.info("Redis 상태 전체 동기화 시작")
    
    try:
        # 상태 동기화 수행
        _sync_running_state(redis_client, k8s_client)
        
        # 추가: 오래된 대기열 항목 정리 (선택적)
        # TODO: 필요시 오래된 pending job 정리 로직 추가
        
        logger.info("Redis 상태 전체 동기화 완료")
        
        return {"status": "completed"}
        
    except Exception as e:
        logger.error(f"Redis 상태 동기화 실패: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
