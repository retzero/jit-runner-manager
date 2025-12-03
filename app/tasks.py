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
    대기열에서 Job을 꺼내 Runner 생성 (배치 처리)
    
    주기적으로 실행되어:
    1. K8s 상태와 Redis 동기화 (Pod 종료 감지)
    2. 모든 Org의 pending job을 timestamp 순으로 조회 (FIFO)
    3. Org별 제한과 전체 제한을 고려하여 최대 batch_size개까지 선택
    4. 선택된 Job들에 대해 Runner 생성 태스크 실행
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
        max_batch_size = config.runner.max_batch_size
        
        if total_running >= max_total:
            logger.info(f"전체 제한 도달: {total_running}/{max_total}, 대기열 처리 건너뜀")
            return {"status": "skipped", "reason": "total_limit_reached"}
        
        # 3. 모든 pending job을 timestamp 순으로 조회 (FIFO)
        all_pending_jobs = redis_client.peek_all_pending_jobs_sync()
        
        if not all_pending_jobs:
            logger.debug("대기 중인 Job 없음")
            return {"status": "no_pending_jobs"}
        
        logger.info(f"대기 중인 총 Job 수: {len(all_pending_jobs)}개")
        
        # 4. Org별 현재 running 수와 제한 정보 캐싱
        org_running_counts = {}  # org_name -> current running count
        org_limits = {}  # org_name -> max limit
        org_selected_counts = {}  # org_name -> 이번 배치에서 선택된 수
        
        # 5. 선택할 Job 목록 결정 (FIFO 순서로, Org 제한 및 전체 제한 고려)
        jobs_to_process = []
        available_slots = min(max_total - total_running, max_batch_size)
        
        for org_name, idx, job_data in all_pending_jobs:
            # 이미 batch_size 또는 전체 제한에 도달했으면 중단
            if len(jobs_to_process) >= available_slots:
                break
            
            # Org의 현재 running 수 조회 (캐싱)
            if org_name not in org_running_counts:
                org_running_counts[org_name] = redis_client.get_org_running_count_sync(org_name)
                org_limits[org_name] = redis_client.get_effective_org_limit_sync(org_name)
                org_selected_counts[org_name] = 0
            
            # Org의 현재 상태: running + 이번 배치에서 선택된 수
            current_org_total = org_running_counts[org_name] + org_selected_counts[org_name]
            org_limit = org_limits[org_name]
            
            # Org 제한 확인
            if current_org_total >= org_limit:
                logger.debug(
                    f"Org 제한 도달, 건너뜀: {org_name} "
                    f"(running={org_running_counts[org_name]}, "
                    f"selected={org_selected_counts[org_name]}, limit={org_limit})"
                )
                continue
            
            # 이 Job을 처리 대상으로 선택
            jobs_to_process.append(job_data)
            org_selected_counts[org_name] += 1
            
            logger.debug(
                f"Job 선택: org={org_name}, job_id={job_data.get('job_id')}, "
                f"org_total={current_org_total + 1}/{org_limit}"
            )
        
        if not jobs_to_process:
            logger.info("처리할 수 있는 Job 없음 (모든 Org 제한 도달)")
            return {"status": "no_available_slots"}
        
        # 6. 선택된 Job들을 queue에서 제거
        removed_count = redis_client.remove_pending_jobs_by_job_ids_sync(jobs_to_process)
        logger.info(f"대기열에서 {removed_count}개 Job 제거")
        
        # 7. 선택된 Job들에 대해 Runner 생성 태스크 실행
        created_count = 0
        for job_data in jobs_to_process:
            org_name = job_data.get("org_name")
            job_id = job_data.get("job_id")
            
            logger.info(f"Runner 생성 요청: org={org_name}, job_id={job_id}")
            
            create_runner_for_job.delay(
                org_name=org_name,
                job_id=job_id,
                run_id=job_data.get("run_id"),
                job_name=job_data.get("job_name"),
                repo_full_name=job_data.get("repo_full_name"),
                labels=job_data.get("labels", [])
            )
            created_count += 1
        
        logger.info(
            f"대기열 처리 완료: {created_count}개 Runner 생성 요청 "
            f"(남은 대기: {len(all_pending_jobs) - created_count}개)"
        )
        
        return {
            "status": "processed",
            "created": created_count,
            "remaining": len(all_pending_jobs) - created_count
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
