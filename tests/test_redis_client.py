"""
Redis 클라이언트 테스트

app/redis_client.py의 RedisClient 및 RedisClientSync 테스트
"""

import json
import time
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


def run_async(coro):
    """비동기 함수를 동기적으로 실행하는 헬퍼"""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestRedisClient:
    """비동기 RedisClient 테스트"""
    
    @pytest.fixture
    def redis_client(self, mock_redis_client, app_config):
        """테스트용 RedisClient 인스턴스"""
        from app.redis_client import RedisClient
        return RedisClient(mock_redis_client)
    
    def test_ping(self, redis_client, mock_redis_client):
        """ping 테스트"""
        mock_redis_client.ping = AsyncMock(return_value=True)
        
        result = run_async(redis_client.ping())
        
        assert result is True
        mock_redis_client.ping.assert_called_once()
    
    # ==================== Organization 관련 테스트 ====================
    
    def test_get_org_running_count_returns_zero_when_empty(self, redis_client, mock_redis_client):
        """Organization running count - 값 없을 때 0 반환"""
        mock_redis_client.get = AsyncMock(return_value=None)
        
        count = run_async(redis_client.get_org_running_count("test-org"))
        
        assert count == 0
    
    def test_get_org_running_count_returns_value(self, redis_client, mock_redis_client):
        """Organization running count - 값 반환"""
        mock_redis_client.get = AsyncMock(return_value=b"5")
        
        count = run_async(redis_client.get_org_running_count("test-org"))
        
        assert count == 5
    
    def test_increment_org_running(self, redis_client, mock_redis_client):
        """Organization running count 증가"""
        mock_redis_client.incr = AsyncMock(return_value=6)
        
        result = run_async(redis_client.increment_org_running("test-org"))
        
        assert result == 6
        mock_redis_client.incr.assert_called_once()
    
    def test_decrement_org_running_prevents_negative(self, redis_client, mock_redis_client):
        """Organization running count 감소 - 음수 방지"""
        mock_redis_client.decr = AsyncMock(return_value=-1)
        mock_redis_client.set = AsyncMock()
        
        result = run_async(redis_client.decrement_org_running("test-org"))
        
        assert result == 0
        mock_redis_client.set.assert_called_once()
    
    def test_set_org_running(self, redis_client, mock_redis_client):
        """Organization running count 설정"""
        mock_redis_client.set = AsyncMock()
        
        run_async(redis_client.set_org_running("test-org", 10))
        
        mock_redis_client.set.assert_called_once()
    
    # ==================== Organization 제한 관련 테스트 ====================
    
    def test_get_org_max_limit_returns_none_when_empty(self, redis_client, mock_redis_client):
        """커스텀 제한 없을 때 None 반환"""
        mock_redis_client.hget = AsyncMock(return_value=None)
        
        limit = run_async(redis_client.get_org_max_limit("test-org"))
        
        assert limit is None
    
    def test_get_org_max_limit_returns_value(self, redis_client, mock_redis_client):
        """커스텀 제한 값 반환"""
        mock_redis_client.hget = AsyncMock(return_value=b"25")
        
        limit = run_async(redis_client.get_org_max_limit("test-org"))
        
        assert limit == 25
    
    def test_set_org_max_limit(self, redis_client, mock_redis_client):
        """커스텀 제한 설정"""
        mock_redis_client.hset = AsyncMock()
        
        run_async(redis_client.set_org_max_limit("test-org", 50))
        
        mock_redis_client.hset.assert_called_once()
    
    def test_delete_org_max_limit(self, redis_client, mock_redis_client):
        """커스텀 제한 삭제"""
        mock_redis_client.hdel = AsyncMock(return_value=1)
        
        result = run_async(redis_client.delete_org_max_limit("test-org"))
        
        assert result is True
    
    def test_get_effective_org_limit_with_custom(self, redis_client, mock_redis_client):
        """유효 제한 - 커스텀 제한 있을 때"""
        mock_redis_client.hget = AsyncMock(return_value=b"25")
        
        limit = run_async(redis_client.get_effective_org_limit("test-org"))
        
        assert limit == 25
    
    def test_get_effective_org_limit_default(self, redis_client, mock_redis_client):
        """유효 제한 - 기본값 사용"""
        mock_redis_client.hget = AsyncMock(return_value=None)
        
        limit = run_async(redis_client.get_effective_org_limit("test-org"))
        
        # 기본값 (config에서 설정됨)
        assert limit == 10
    
    # ==================== 전체 카운트 관련 테스트 ====================
    
    def test_get_total_running_returns_zero_when_empty(self, redis_client, mock_redis_client):
        """전체 running count - 값 없을 때 0 반환"""
        mock_redis_client.get = AsyncMock(return_value=None)
        
        count = run_async(redis_client.get_total_running())
        
        assert count == 0
    
    def test_increment_total_running(self, redis_client, mock_redis_client):
        """전체 running count 증가"""
        mock_redis_client.incr = AsyncMock(return_value=50)
        
        result = run_async(redis_client.increment_total_running())
        
        assert result == 50
    
    def test_decrement_total_running_prevents_negative(self, redis_client, mock_redis_client):
        """전체 running count 감소 - 음수 방지"""
        mock_redis_client.decr = AsyncMock(return_value=-1)
        mock_redis_client.set = AsyncMock()
        
        result = run_async(redis_client.decrement_total_running())
        
        assert result == 0
    
    # ==================== 대기열 관련 테스트 ====================
    
    def test_add_pending_job(self, redis_client, mock_redis_client):
        """대기열에 Job 추가"""
        mock_redis_client.rpush = AsyncMock()
        
        run_async(redis_client.add_pending_job(
            org_name="test-org",
            job_id=12345,
            run_id=67890,
            job_name="build",
            repo_full_name="test-org/test-repo",
            labels=["code-linux"]
        ))
        
        mock_redis_client.rpush.assert_called_once()
        # 저장된 데이터 확인
        call_args = mock_redis_client.rpush.call_args
        job_data = json.loads(call_args[0][1])
        assert job_data["job_id"] == 12345
        assert job_data["org_name"] == "test-org"
        assert "timestamp" in job_data
    
    def test_pop_pending_job_returns_none_when_empty(self, redis_client, mock_redis_client):
        """대기열에서 Job 가져오기 - 빈 경우"""
        mock_redis_client.lpop = AsyncMock(return_value=None)
        
        job = run_async(redis_client.pop_pending_job("test-org"))
        
        assert job is None
    
    def test_pop_pending_job_returns_job(self, redis_client, mock_redis_client):
        """대기열에서 Job 가져오기"""
        job_data = {"job_id": 12345, "org_name": "test-org"}
        mock_redis_client.lpop = AsyncMock(return_value=json.dumps(job_data).encode())
        
        job = run_async(redis_client.pop_pending_job("test-org"))
        
        assert job["job_id"] == 12345
    
    def test_get_pending_job_count(self, redis_client, mock_redis_client):
        """대기열 Job 수 조회"""
        mock_redis_client.llen = AsyncMock(return_value=5)
        
        count = run_async(redis_client.get_pending_job_count("test-org"))
        
        assert count == 5
    
    # ==================== Runner 정보 관련 테스트 ====================
    
    def test_save_runner_info(self, redis_client, mock_redis_client):
        """Runner 정보 저장"""
        mock_redis_client.hset = AsyncMock()
        mock_redis_client.expire = AsyncMock()
        
        run_async(redis_client.save_runner_info(
            runner_name="jit-runner-12345",
            org_name="test-org",
            job_id=12345,
            run_id=67890,
            repo_full_name="test-org/test-repo"
        ))
        
        mock_redis_client.hset.assert_called_once()
        mock_redis_client.expire.assert_called_once()
    
    def test_get_runner_info_returns_none_when_empty(self, redis_client, mock_redis_client):
        """Runner 정보 조회 - 없을 때"""
        mock_redis_client.hgetall = AsyncMock(return_value={})
        
        info = run_async(redis_client.get_runner_info("jit-runner-12345"))
        
        assert info is None
    
    def test_get_runner_info_returns_data(self, redis_client, mock_redis_client):
        """Runner 정보 조회"""
        mock_redis_client.hgetall = AsyncMock(return_value={
            b"runner_name": b"jit-runner-12345",
            b"org_name": b"test-org"
        })
        
        info = run_async(redis_client.get_runner_info("jit-runner-12345"))
        
        assert info["runner_name"] == "jit-runner-12345"
        assert info["org_name"] == "test-org"
    
    def test_delete_runner_info(self, redis_client, mock_redis_client):
        """Runner 정보 삭제"""
        mock_redis_client.delete = AsyncMock()
        
        run_async(redis_client.delete_runner_info("jit-runner-12345"))
        
        mock_redis_client.delete.assert_called_once()


class TestRedisClientSync:
    """동기 RedisClientSync 테스트"""
    
    @pytest.fixture
    def redis_client_sync(self, mock_redis_client_sync, app_config):
        """테스트용 RedisClientSync 인스턴스"""
        from app.redis_client import RedisClientSync
        return RedisClientSync(mock_redis_client_sync)
    
    def test_ping(self, redis_client_sync, mock_redis_client_sync):
        """ping 테스트"""
        mock_redis_client_sync.ping.return_value = True
        
        result = redis_client_sync.ping()
        
        assert result is True
    
    def test_get_org_running_count_sync(self, redis_client_sync, mock_redis_client_sync):
        """Organization running count 동기 조회"""
        mock_redis_client_sync.get.return_value = b"5"
        
        count = redis_client_sync.get_org_running_count_sync("test-org")
        
        assert count == 5
    
    def test_increment_org_running_sync(self, redis_client_sync, mock_redis_client_sync):
        """Organization running count 동기 증가"""
        mock_redis_client_sync.incr.return_value = 6
        
        result = redis_client_sync.increment_org_running_sync("test-org")
        
        assert result == 6
    
    def test_get_effective_org_limit_sync_with_custom(self, redis_client_sync, mock_redis_client_sync):
        """유효 제한 동기 조회 - 커스텀 제한"""
        mock_redis_client_sync.hget.return_value = b"25"
        
        limit = redis_client_sync.get_effective_org_limit_sync("test-org")
        
        assert limit == 25
    
    def test_get_total_running_sync(self, redis_client_sync, mock_redis_client_sync):
        """전체 running count 동기 조회"""
        mock_redis_client_sync.get.return_value = b"100"
        
        count = redis_client_sync.get_total_running_sync()
        
        assert count == 100
    
    def test_add_pending_job_sync(self, redis_client_sync, mock_redis_client_sync):
        """대기열에 Job 동기 추가"""
        redis_client_sync.add_pending_job_sync(
            org_name="test-org",
            job_id=12345,
            run_id=67890,
            job_name="build",
            repo_full_name="test-org/test-repo",
            labels=["code-linux"]
        )
        
        mock_redis_client_sync.rpush.assert_called_once()
    
    def test_pop_pending_job_sync(self, redis_client_sync, mock_redis_client_sync):
        """대기열에서 Job 동기 가져오기"""
        job_data = {"job_id": 12345, "org_name": "test-org"}
        mock_redis_client_sync.lpop.return_value = json.dumps(job_data).encode()
        
        job = redis_client_sync.pop_pending_job_sync("test-org")
        
        assert job["job_id"] == 12345
    
    def test_save_runner_info_sync(self, redis_client_sync, mock_redis_client_sync):
        """Runner 정보 동기 저장"""
        redis_client_sync.save_runner_info_sync(
            runner_name="jit-runner-12345",
            org_name="test-org",
            job_id=12345,
            run_id=67890,
            repo_full_name="test-org/test-repo"
        )
        
        mock_redis_client_sync.hset.assert_called_once()
        mock_redis_client_sync.expire.assert_called_once()
    
    def test_peek_all_pending_jobs_sync(self, redis_client_sync, mock_redis_client_sync):
        """모든 pending job 조회 (제거 없이)"""
        # scan_iter가 키 목록 반환
        mock_redis_client_sync.scan_iter.return_value = iter([b"org:test-org:pending"])
        
        # lrange가 해당 키의 모든 항목 반환
        job_data = json.dumps({
            "job_id": 12345,
            "org_name": "test-org",
            "timestamp": time.time()
        })
        mock_redis_client_sync.lrange.return_value = [job_data.encode()]
        
        jobs = redis_client_sync.peek_all_pending_jobs_sync()
        
        assert len(jobs) == 1
        assert jobs[0][0] == "test-org"
        assert jobs[0][2]["job_id"] == 12345
    
    def test_remove_pending_jobs_by_job_ids_sync(self, redis_client_sync, mock_redis_client_sync):
        """특정 job_id의 pending job 제거"""
        # lrange 반환값 설정
        jobs_in_queue = [
            json.dumps({"job_id": 12345, "org_name": "test-org"}).encode(),
            json.dumps({"job_id": 12346, "org_name": "test-org"}).encode(),
        ]
        mock_redis_client_sync.lrange.return_value = jobs_in_queue
        
        # pipeline mock 설정
        mock_pipe = MagicMock()
        mock_redis_client_sync.pipeline.return_value = mock_pipe
        
        jobs_to_remove = [{"job_id": 12345, "org_name": "test-org"}]
        removed = redis_client_sync.remove_pending_jobs_by_job_ids_sync(jobs_to_remove)
        
        assert removed == 1
        mock_pipe.delete.assert_called_once()
        mock_pipe.rpush.assert_called_once()


class TestRedisClientFactory:
    """Redis 클라이언트 팩토리 함수 테스트"""
    
    def test_get_redis_client_creates_client(self, app_config):
        """get_redis_client가 클라이언트 생성"""
        with patch("app.redis_client.aioredis") as mock_aioredis:
            mock_client = AsyncMock()
            mock_aioredis.from_url.return_value = mock_client
            
            # 싱글톤 리셋
            import app.redis_client as redis_module
            redis_module._async_client = None
            
            from app.redis_client import get_redis_client
            
            client = get_redis_client()
            
            assert client is not None
            mock_aioredis.from_url.assert_called_once()
    
    def test_get_redis_client_sync_creates_client(self, app_config):
        """get_redis_client_sync가 클라이언트 생성"""
        with patch("app.redis_client.redis") as mock_redis:
            mock_client = MagicMock()
            mock_redis.from_url.return_value = mock_client
            
            # 싱글톤 리셋
            import app.redis_client as redis_module
            redis_module._sync_client = None
            
            from app.redis_client import get_redis_client_sync
            
            client = get_redis_client_sync()
            
            assert client is not None
            mock_redis.from_url.assert_called_once()
