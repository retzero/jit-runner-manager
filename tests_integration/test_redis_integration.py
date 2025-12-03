"""
Redis Integration Tests

실제 Redis 서버와의 통합 테스트
"""

import json
import pytest


@pytest.mark.integration
@pytest.mark.redis
class TestRedisIntegration:
    """Redis 통합 테스트"""
    
    def test_redis_connection(self, redis_client):
        """Redis 연결 테스트"""
        assert redis_client.ping() is True
    
    def test_redis_set_get(self, clean_redis):
        """기본 SET/GET 동작 테스트"""
        clean_redis.set("test:key", "test-value")
        value = clean_redis.get("test:key")
        assert value == "test-value"
    
    def test_redis_hash_operations(self, clean_redis):
        """Hash 연산 테스트"""
        clean_redis.hset("test:hash", "field1", "value1")
        clean_redis.hset("test:hash", "field2", "value2")
        
        assert clean_redis.hget("test:hash", "field1") == "value1"
        assert clean_redis.hgetall("test:hash") == {
            "field1": "value1",
            "field2": "value2"
        }
    
    def test_redis_list_operations(self, clean_redis):
        """List 연산 테스트"""
        clean_redis.rpush("test:list", "item1", "item2", "item3")
        
        assert clean_redis.llen("test:list") == 3
        assert clean_redis.lrange("test:list", 0, -1) == ["item1", "item2", "item3"]
        assert clean_redis.lpop("test:list") == "item1"
    
    def test_redis_counter_operations(self, clean_redis):
        """카운터 연산 테스트"""
        clean_redis.set("test:counter", "0")
        
        clean_redis.incr("test:counter")
        clean_redis.incr("test:counter")
        assert clean_redis.get("test:counter") == "2"
        
        clean_redis.decr("test:counter")
        assert clean_redis.get("test:counter") == "1"
    
    def test_redis_expiration(self, clean_redis):
        """Key 만료 테스트"""
        clean_redis.set("test:expire", "value", ex=1)
        assert clean_redis.get("test:expire") == "value"
        
        import time
        time.sleep(2)
        assert clean_redis.get("test:expire") is None


@pytest.mark.integration
@pytest.mark.redis
class TestRunnerStateManagement:
    """Runner 상태 관리 통합 테스트"""
    
    def test_org_running_counter(self, clean_redis):
        """Organization별 실행 중 Runner 카운터 테스트"""
        org_name = "test-org"
        key = f"org:{org_name}:running"
        
        # 초기값 설정
        clean_redis.set(key, "0")
        
        # Runner 생성 시 증가
        clean_redis.incr(key)
        assert clean_redis.get(key) == "1"
        
        # 추가 Runner
        clean_redis.incr(key)
        clean_redis.incr(key)
        assert clean_redis.get(key) == "3"
        
        # Runner 완료 시 감소
        clean_redis.decr(key)
        assert clean_redis.get(key) == "2"
    
    def test_pending_jobs_queue(self, clean_redis):
        """대기 중인 Job 큐 테스트"""
        org_name = "test-org"
        key = f"org:{org_name}:pending"
        
        # Job 추가
        jobs = [
            {"job_id": 1, "labels": ["code-linux"]},
            {"job_id": 2, "labels": ["code-linux"]},
            {"job_id": 3, "labels": ["code-linux"]}
        ]
        
        for job in jobs:
            clean_redis.rpush(key, json.dumps(job))
        
        assert clean_redis.llen(key) == 3
        
        # FIFO로 처리
        first_job = json.loads(clean_redis.lpop(key))
        assert first_job["job_id"] == 1
        assert clean_redis.llen(key) == 2
    
    def test_runner_info_storage(self, clean_redis):
        """Runner 정보 저장 테스트"""
        runner_name = "jit-runner-12345"
        key = f"runner:{runner_name}:info"
        
        runner_info = {
            "runner_id": "100",
            "org_name": "test-org",
            "job_id": "12345",
            "status": "running",
            "created_at": "2024-01-01T00:00:00Z"
        }
        
        # 정보 저장
        for field, value in runner_info.items():
            clean_redis.hset(key, field, value)
        
        # 정보 조회
        stored_info = clean_redis.hgetall(key)
        assert stored_info == runner_info
        
        # 상태 업데이트
        clean_redis.hset(key, "status", "completed")
        assert clean_redis.hget(key, "status") == "completed"
    
    def test_global_total_runners(self, clean_redis):
        """전역 Runner 수 관리 테스트"""
        key = "global:total_running"
        
        clean_redis.set(key, "0")
        
        # 여러 org에서 Runner 생성
        clean_redis.incr(key)  # org1
        clean_redis.incr(key)  # org1
        clean_redis.incr(key)  # org2
        
        assert clean_redis.get(key) == "3"
        
        # 최대 제한 체크 시뮬레이션
        current = int(clean_redis.get(key))
        max_total = 50
        assert current < max_total
