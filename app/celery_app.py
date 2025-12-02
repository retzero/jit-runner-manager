"""
Celery 애플리케이션 설정

비동기 태스크 처리를 위한 Celery 설정
"""

import os
from celery import Celery

# Celery 브로커 및 백엔드 URL
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

# Celery 앱 생성
celery_app = Celery(
    "jit_runner_manager",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=["app.tasks"]
)

# Celery 설정
celery_app.conf.update(
    # Task 설정
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    # Task 실행 설정
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=600,  # 10분
    task_soft_time_limit=540,  # 9분
    
    # Worker 설정
    worker_prefetch_multiplier=1,
    worker_concurrency=int(os.getenv("CELERY_WORKER_CONCURRENCY", "10")),
    
    # Retry 설정
    task_default_retry_delay=30,
    task_max_retries=3,
    
    # Result 설정
    result_expires=3600,  # 1시간
    
    # Beat 설정 (주기적 태스크용)
    beat_schedule={
        "cleanup-stale-runners": {
            "task": "app.tasks.cleanup_stale_runners",
            "schedule": 300.0,  # 5분마다
        },
        "sync-redis-state": {
            "task": "app.tasks.sync_redis_state",
            "schedule": 600.0,  # 10분마다
        },
    },
)


# Task 라우팅 (선택사항)
celery_app.conf.task_routes = {
    "app.tasks.process_workflow_job_queued": {"queue": "runner_create"},
    "app.tasks.process_workflow_job_completed": {"queue": "runner_cleanup"},
    "app.tasks.cleanup_stale_runners": {"queue": "maintenance"},
    "app.tasks.sync_redis_state": {"queue": "maintenance"},
}


if __name__ == "__main__":
    celery_app.start()

