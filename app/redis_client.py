"""
Redis 클라이언트

Runner 상태 관리 및 메시지 큐 연동
"""

import json
import logging
import time
from typing import Dict, List, Optional, Any, Tuple

import redis
from redis import asyncio as aioredis

from app.config import get_config, RedisKeys

logger = logging.getLogger(__name__)

# 글로벌 클라이언트 인스턴스
_async_client: Optional[aioredis.Redis] = None
_sync_client: Optional[redis.Redis] = None


class RedisClient:
    """비동기 Redis 클라이언트"""
    
    def __init__(self, client: aioredis.Redis):
        self.client = client
        self.config = get_config()
    
    async def ping(self) -> bool:
        """Redis 연결 확인"""
        return await self.client.ping()
    
    # ==================== Organization 관련 ====================
    
    async def get_org_running_count(self, org_name: str) -> int:
        """Organization의 현재 실행 중인 Runner 수 조회"""
        key = RedisKeys.org_running(org_name)
        value = await self.client.get(key)
        return int(value) if value else 0
    
    async def get_org_pending_count(self, org_name: str) -> int:
        """Organization의 대기 중인 Job 수 조회"""
        key = RedisKeys.org_pending(org_name)
        return await self.client.llen(key)
    
    async def increment_org_running(self, org_name: str) -> int:
        """Organization의 실행 중인 Runner 수 증가"""
        key = RedisKeys.org_running(org_name)
        return await self.client.incr(key)
    
    async def decrement_org_running(self, org_name: str) -> int:
        """Organization의 실행 중인 Runner 수 감소"""
        key = RedisKeys.org_running(org_name)
        value = await self.client.decr(key)
        # 음수 방지
        if value < 0:
            await self.client.set(key, 0)
            return 0
        return value
    
    async def set_org_running(self, org_name: str, count: int) -> None:
        """Organization의 실행 중인 Runner 수 설정"""
        key = RedisKeys.org_running(org_name)
        await self.client.set(key, count)
    
    # ==================== Organization 제한 관련 ====================
    
    async def get_org_max_limit(self, org_name: str) -> Optional[int]:
        """Organization의 커스텀 최대 Runner 수 조회 (없으면 None)"""
        key = RedisKeys.org_limits_hash()
        value = await self.client.hget(key, org_name)
        if value:
            return int(value.decode() if isinstance(value, bytes) else value)
        return None
    
    async def set_org_max_limit(self, org_name: str, limit: int) -> None:
        """Organization의 커스텀 최대 Runner 수 설정"""
        key = RedisKeys.org_limits_hash()
        await self.client.hset(key, org_name, str(limit))
    
    async def delete_org_max_limit(self, org_name: str) -> bool:
        """Organization의 커스텀 최대 Runner 수 삭제 (기본값 사용)"""
        key = RedisKeys.org_limits_hash()
        result = await self.client.hdel(key, org_name)
        return result > 0
    
    async def get_all_org_limits(self) -> Dict[str, int]:
        """모든 Organization의 커스텀 제한 조회"""
        key = RedisKeys.org_limits_hash()
        data = await self.client.hgetall(key)
        if data:
            return {
                (k.decode() if isinstance(k, bytes) else k): 
                int(v.decode() if isinstance(v, bytes) else v)
                for k, v in data.items()
            }
        return {}
    
    async def set_org_limits_bulk(self, limits: Dict[str, int]) -> None:
        """여러 Organization의 커스텀 제한 일괄 설정"""
        if not limits:
            return
        key = RedisKeys.org_limits_hash()
        mapping = {org: str(limit) for org, limit in limits.items()}
        await self.client.hset(key, mapping=mapping)
    
    async def get_effective_org_limit(self, org_name: str) -> int:
        """Organization의 유효 제한 조회 (커스텀 또는 기본값)"""
        custom_limit = await self.get_org_max_limit(org_name)
        if custom_limit is not None:
            return custom_limit
        return self.config.runner.max_per_org
    
    # ==================== 전체 카운트 관련 ====================
    
    async def get_total_running(self) -> int:
        """전체 실행 중인 Runner 수 조회"""
        key = RedisKeys.global_total()
        value = await self.client.get(key)
        return int(value) if value else 0
    
    async def increment_total_running(self) -> int:
        """전체 실행 중인 Runner 수 증가"""
        key = RedisKeys.global_total()
        return await self.client.incr(key)
    
    async def decrement_total_running(self) -> int:
        """전체 실행 중인 Runner 수 감소"""
        key = RedisKeys.global_total()
        value = await self.client.decr(key)
        if value < 0:
            await self.client.set(key, 0)
            return 0
        return value
    
    async def set_total_running(self, count: int) -> None:
        """전체 실행 중인 Runner 수 설정"""
        key = RedisKeys.global_total()
        await self.client.set(key, count)
    
    # ==================== 대기열 관련 ====================
    
    async def add_pending_job(
        self,
        org_name: str,
        job_id: int,
        run_id: int,
        job_name: str,
        repo_full_name: str,
        labels: List[str]
    ) -> None:
        """대기열에 Job 추가 (전체 정보 포함, timestamp 포함)"""
        key = RedisKeys.org_pending(org_name)
        job_data = json.dumps({
            "job_id": job_id,
            "run_id": run_id,
            "job_name": job_name,
            "repo_full_name": repo_full_name,
            "labels": labels,
            "org_name": org_name,
            "timestamp": time.time()
        })
        await self.client.rpush(key, job_data)
    
    async def pop_pending_job(self, org_name: str) -> Optional[Dict]:
        """대기열에서 Job 가져오기 (FIFO)"""
        key = RedisKeys.org_pending(org_name)
        value = await self.client.lpop(key)
        if value:
            data = value.decode() if isinstance(value, bytes) else value
            return json.loads(data)
        return None
    
    async def get_pending_job_count(self, org_name: str) -> int:
        """대기열의 Job 수 조회"""
        key = RedisKeys.org_pending(org_name)
        return await self.client.llen(key)
    
    # ==================== Runner 정보 관련 ====================
    
    async def save_runner_info(
        self,
        runner_name: str,
        org_name: str,
        job_id: int,
        run_id: int,
        repo_full_name: str
    ) -> None:
        """Runner 정보 저장"""
        key = RedisKeys.runner_info(runner_name)
        data = {
            "runner_name": runner_name,
            "org_name": org_name,
            "job_id": job_id,
            "run_id": run_id,
            "repo_full_name": repo_full_name
        }
        await self.client.hset(key, mapping=data)
        await self.client.expire(key, self.config.redis.ttl)
    
    async def get_runner_info(self, runner_name: str) -> Optional[Dict]:
        """Runner 정보 조회"""
        key = RedisKeys.runner_info(runner_name)
        data = await self.client.hgetall(key)
        if data:
            return {k.decode() if isinstance(k, bytes) else k: 
                    v.decode() if isinstance(v, bytes) else v 
                    for k, v in data.items()}
        return None
    
    async def delete_runner_info(self, runner_name: str) -> None:
        """Runner 정보 삭제"""
        key = RedisKeys.runner_info(runner_name)
        await self.client.delete(key)
    
    async def get_all_runners(self) -> Dict[str, Dict]:
        """모든 Runner 정보 조회"""
        pattern = "runner:*:info"
        runners = {}
        async for key in self.client.scan_iter(match=pattern):
            key_str = key.decode() if isinstance(key, bytes) else key
            runner_name = key_str.split(":")[1]
            info = await self.get_runner_info(runner_name)
            if info:
                runners[runner_name] = info
        return runners
    
    # ==================== 통계 관련 ====================
    
    async def get_all_org_stats(self) -> Dict[str, Dict]:
        """모든 Organization 통계 조회"""
        pattern = "org:*:running"
        stats = {}
        async for key in self.client.scan_iter(match=pattern):
            key_str = key.decode() if isinstance(key, bytes) else key
            org_name = key_str.split(":")[1]
            running = await self.get_org_running_count(org_name)
            pending = await self.get_org_pending_count(org_name)
            if running > 0 or pending > 0:
                stats[org_name] = {"running": running, "pending": pending}
        return stats


class RedisClientSync:
    """동기 Redis 클라이언트 (Celery task용)"""
    
    def __init__(self, client: redis.Redis):
        self.client = client
        self.config = get_config()
    
    def ping(self) -> bool:
        return self.client.ping()
    
    # ==================== Organization 관련 ====================
    
    def get_org_running_count_sync(self, org_name: str) -> int:
        key = RedisKeys.org_running(org_name)
        value = self.client.get(key)
        return int(value) if value else 0
    
    def increment_org_running_sync(self, org_name: str) -> int:
        key = RedisKeys.org_running(org_name)
        return self.client.incr(key)
    
    def decrement_org_running_sync(self, org_name: str) -> int:
        key = RedisKeys.org_running(org_name)
        value = self.client.decr(key)
        if value < 0:
            self.client.set(key, 0)
            return 0
        return value
    
    def set_org_running_sync(self, org_name: str, count: int) -> None:
        key = RedisKeys.org_running(org_name)
        self.client.set(key, count)
    
    # ==================== Organization 제한 관련 ====================
    
    def get_org_max_limit_sync(self, org_name: str) -> Optional[int]:
        """Organization의 커스텀 최대 Runner 수 조회 (없으면 None)"""
        key = RedisKeys.org_limits_hash()
        value = self.client.hget(key, org_name)
        if value:
            return int(value.decode() if isinstance(value, bytes) else value)
        return None
    
    def set_org_max_limit_sync(self, org_name: str, limit: int) -> None:
        """Organization의 커스텀 최대 Runner 수 설정"""
        key = RedisKeys.org_limits_hash()
        self.client.hset(key, org_name, str(limit))
    
    def delete_org_max_limit_sync(self, org_name: str) -> bool:
        """Organization의 커스텀 최대 Runner 수 삭제 (기본값 사용)"""
        key = RedisKeys.org_limits_hash()
        result = self.client.hdel(key, org_name)
        return result > 0
    
    def get_all_org_limits_sync(self) -> Dict[str, int]:
        """모든 Organization의 커스텀 제한 조회"""
        key = RedisKeys.org_limits_hash()
        data = self.client.hgetall(key)
        if data:
            return {
                (k.decode() if isinstance(k, bytes) else k): 
                int(v.decode() if isinstance(v, bytes) else v)
                for k, v in data.items()
            }
        return {}
    
    def set_org_limits_bulk_sync(self, limits: Dict[str, int]) -> None:
        """여러 Organization의 커스텀 제한 일괄 설정"""
        if not limits:
            return
        key = RedisKeys.org_limits_hash()
        mapping = {org: str(limit) for org, limit in limits.items()}
        self.client.hset(key, mapping=mapping)
    
    def get_effective_org_limit_sync(self, org_name: str) -> int:
        """Organization의 유효 제한 조회 (커스텀 또는 기본값)"""
        custom_limit = self.get_org_max_limit_sync(org_name)
        if custom_limit is not None:
            return custom_limit
        return self.config.runner.max_per_org
    
    # ==================== 전체 카운트 관련 ====================
    
    def get_total_running_sync(self) -> int:
        key = RedisKeys.global_total()
        value = self.client.get(key)
        return int(value) if value else 0
    
    def increment_total_running_sync(self) -> int:
        key = RedisKeys.global_total()
        return self.client.incr(key)
    
    def decrement_total_running_sync(self) -> int:
        key = RedisKeys.global_total()
        value = self.client.decr(key)
        if value < 0:
            self.client.set(key, 0)
            return 0
        return value
    
    def set_total_running_sync(self, count: int) -> None:
        key = RedisKeys.global_total()
        self.client.set(key, count)
    
    # ==================== 대기열 관련 ====================
    
    def add_pending_job_sync(
        self,
        org_name: str,
        job_id: int,
        run_id: int,
        job_name: str,
        repo_full_name: str,
        labels: List[str]
    ) -> None:
        """대기열에 Job 추가 (전체 정보 포함, timestamp 포함)"""
        key = RedisKeys.org_pending(org_name)
        job_data = json.dumps({
            "job_id": job_id,
            "run_id": run_id,
            "job_name": job_name,
            "repo_full_name": repo_full_name,
            "labels": labels,
            "org_name": org_name,
            "timestamp": time.time()
        })
        self.client.rpush(key, job_data)
    
    def pop_pending_job_sync(self, org_name: str) -> Optional[Dict]:
        """대기열에서 Job 가져오기 (FIFO)"""
        key = RedisKeys.org_pending(org_name)
        value = self.client.lpop(key)
        if value:
            data = value.decode() if isinstance(value, bytes) else value
            return json.loads(data)
        return None
    
    def get_pending_job_count_sync(self, org_name: str) -> int:
        """대기열의 Job 수 조회"""
        key = RedisKeys.org_pending(org_name)
        return self.client.llen(key)
    
    # ==================== Runner 정보 관련 ====================
    
    def save_runner_info_sync(
        self,
        runner_name: str,
        org_name: str,
        job_id: int,
        run_id: int,
        repo_full_name: str
    ) -> None:
        key = RedisKeys.runner_info(runner_name)
        data = {
            "runner_name": runner_name,
            "org_name": org_name,
            "job_id": str(job_id),
            "run_id": str(run_id),
            "repo_full_name": repo_full_name
        }
        self.client.hset(key, mapping=data)
        self.client.expire(key, self.config.redis.ttl)
    
    def get_runner_info_sync(self, runner_name: str) -> Optional[Dict]:
        key = RedisKeys.runner_info(runner_name)
        data = self.client.hgetall(key)
        if data:
            return {k.decode() if isinstance(k, bytes) else k:
                    v.decode() if isinstance(v, bytes) else v
                    for k, v in data.items()}
        return None
    
    def delete_runner_info_sync(self, runner_name: str) -> None:
        key = RedisKeys.runner_info(runner_name)
        self.client.delete(key)
    
    def get_all_runners_sync(self) -> Dict[str, Dict]:
        pattern = "runner:*:info"
        runners = {}
        for key in self.client.scan_iter(match=pattern):
            key_str = key.decode() if isinstance(key, bytes) else key
            runner_name = key_str.split(":")[1]
            info = self.get_runner_info_sync(runner_name)
            if info:
                runners[runner_name] = info
        return runners
    
    # ==================== 배치 대기열 처리 관련 ====================
    
    def peek_all_pending_jobs_sync(self) -> List[Tuple[str, int, Dict]]:
        """
        모든 Org의 pending job을 조회 (제거하지 않고)
        
        Returns:
            List of (org_name, index, job_data) sorted by timestamp (FIFO)
        """
        all_jobs = []
        pattern = "org:*:pending"
        
        for key in self.client.scan_iter(match=pattern):
            key_str = key.decode() if isinstance(key, bytes) else key
            parts = key_str.split(":")
            if len(parts) >= 2:
                org_name = parts[1]
                # LRANGE로 전체 목록 조회 (제거하지 않음)
                items = self.client.lrange(key_str, 0, -1)
                for idx, item in enumerate(items):
                    data = item.decode() if isinstance(item, bytes) else item
                    job_data = json.loads(data)
                    # timestamp가 없는 기존 데이터 호환성
                    if "timestamp" not in job_data:
                        job_data["timestamp"] = 0
                    all_jobs.append((org_name, idx, job_data))
        
        # timestamp 순으로 정렬 (FIFO - 오래된 것부터)
        all_jobs.sort(key=lambda x: x[2].get("timestamp", 0))
        return all_jobs
    
    def remove_pending_jobs_by_job_ids_sync(self, jobs_to_remove: List[Dict]) -> int:
        """
        특정 job들을 pending queue에서 제거
        
        Args:
            jobs_to_remove: List of job_data dicts containing org_name and job_id
            
        Returns:
            Number of jobs removed
        """
        removed_count = 0
        
        # Org별로 그룹화
        org_jobs = {}
        for job in jobs_to_remove:
            org_name = job.get("org_name")
            if org_name not in org_jobs:
                org_jobs[org_name] = []
            org_jobs[org_name].append(job.get("job_id"))
        
        for org_name, job_ids in org_jobs.items():
            key = RedisKeys.org_pending(org_name)
            # 현재 queue 내용 조회
            items = self.client.lrange(key, 0, -1)
            
            # 제거할 job_id set
            job_ids_set = set(job_ids)
            
            # 유지할 항목들
            items_to_keep = []
            for item in items:
                data = item.decode() if isinstance(item, bytes) else item
                job_data = json.loads(data)
                if job_data.get("job_id") not in job_ids_set:
                    items_to_keep.append(item)
                else:
                    removed_count += 1
            
            # Queue 재구성 (atomic operation을 위해 pipeline 사용)
            pipe = self.client.pipeline()
            pipe.delete(key)
            if items_to_keep:
                pipe.rpush(key, *items_to_keep)
            pipe.execute()
        
        return removed_count


def get_redis_client() -> RedisClient:
    """비동기 Redis 클라이언트 인스턴스 반환"""
    global _async_client
    if _async_client is None:
        config = get_config()
        _async_client = aioredis.from_url(
            config.redis.url,
            password=config.redis.password if config.redis.password else None,
            encoding="utf-8",
            decode_responses=False
        )
    return RedisClient(_async_client)


def get_redis_client_sync() -> RedisClientSync:
    """동기 Redis 클라이언트 인스턴스 반환"""
    global _sync_client
    if _sync_client is None:
        config = get_config()
        _sync_client = redis.from_url(
            config.redis.url,
            password=config.redis.password if config.redis.password else None,
            encoding="utf-8",
            decode_responses=False
        )
    return RedisClientSync(_sync_client)

