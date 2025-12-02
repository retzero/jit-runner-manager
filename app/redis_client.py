"""
Redis 클라이언트

Runner 상태 관리 및 메시지 큐 연동
"""

import json
import logging
from typing import Dict, List, Optional, Any

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
    
    async def add_pending_job(self, org_name: str, job_id: int) -> None:
        """대기열에 Job 추가"""
        key = RedisKeys.org_pending(org_name)
        await self.client.rpush(key, job_id)
    
    async def pop_pending_job(self, org_name: str) -> Optional[int]:
        """대기열에서 Job 가져오기 (FIFO)"""
        key = RedisKeys.org_pending(org_name)
        value = await self.client.lpop(key)
        return int(value) if value else None
    
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
    
    def add_pending_job_sync(self, org_name: str, job_id: int) -> None:
        key = RedisKeys.org_pending(org_name)
        self.client.rpush(key, job_id)
    
    def pop_pending_job_sync(self, org_name: str) -> Optional[int]:
        key = RedisKeys.org_pending(org_name)
        value = self.client.lpop(key)
        return int(value) if value else None
    
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


def get_redis_client() -> RedisClient:
    """비동기 Redis 클라이언트 인스턴스 반환"""
    global _async_client
    if _async_client is None:
        config = get_config()
        _async_client = aioredis.from_url(
            config.redis.url,
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
            encoding="utf-8",
            decode_responses=False
        )
    return RedisClientSync(_sync_client)

