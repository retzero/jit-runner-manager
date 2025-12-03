"""
Celery 태스크 테스트

app/tasks.py의 Celery 태스크 테스트
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock


class TestCreateRunnerForJob:
    """create_runner_for_job 태스크 테스트"""
    
    @pytest.fixture
    def mock_dependencies(self, app_config):
        """태스크 의존성 Mock"""
        with patch("app.tasks.get_config") as mock_config, \
             patch("app.tasks.get_redis_client_sync") as mock_redis, \
             patch("app.tasks.GitHubClient") as mock_github_cls, \
             patch("app.tasks.KubernetesClient") as mock_k8s_cls:
            
            # Config mock
            mock_config.return_value = app_config
            
            # Redis mock
            redis_client = MagicMock()
            mock_redis.return_value = redis_client
            
            # GitHub mock
            github_client = MagicMock()
            mock_github_cls.return_value = github_client
            
            # K8s mock
            k8s_client = MagicMock()
            mock_k8s_cls.return_value = k8s_client
            
            yield {
                "config": app_config,
                "redis": redis_client,
                "github": github_client,
                "k8s": k8s_client
            }
    
    def test_create_runner_success(self, mock_dependencies, sample_jit_config):
        """Runner 생성 성공"""
        from app.tasks import create_runner_for_job
        
        mock_dependencies["github"].create_jit_runner_config.return_value = sample_jit_config
        mock_dependencies["k8s"].create_runner_pod.return_value = MagicMock()
        
        # Task 직접 호출 (Celery worker 없이)
        result = create_runner_for_job(
            org_name="test-org",
            job_id=12345,
            run_id=67890,
            job_name="build",
            repo_full_name="test-org/test-repo",
            labels=["code-linux"]
        )
        
        assert result["status"] == "created"
        assert result["runner_name"] == "jit-runner-12345"
        assert result["org"] == "test-org"
        
        # Redis 업데이트 확인
        mock_dependencies["redis"].increment_org_running_sync.assert_called_with("test-org")
        mock_dependencies["redis"].increment_total_running_sync.assert_called_once()
        mock_dependencies["redis"].save_runner_info_sync.assert_called_once()
    
    def test_create_runner_github_error_retries(self, mock_dependencies):
        """GitHub API 에러 시 재시도"""
        from app.tasks import create_runner_for_job
        
        mock_dependencies["github"].create_jit_runner_config.side_effect = Exception("API Error")
        
        # bind=True task는 self.retry를 호출함
        with patch.object(create_runner_for_job, "retry") as mock_retry:
            mock_retry.side_effect = Exception("Retry")
            
            with pytest.raises(Exception, match="Retry"):
                create_runner_for_job(
                    org_name="test-org",
                    job_id=12345,
                    run_id=67890,
                    job_name="build",
                    repo_full_name="test-org/test-repo",
                    labels=["code-linux"]
                )
    
    def test_create_runner_k8s_error_retries(self, mock_dependencies, sample_jit_config):
        """K8s 에러 시 재시도"""
        from app.tasks import create_runner_for_job
        
        mock_dependencies["github"].create_jit_runner_config.return_value = sample_jit_config
        mock_dependencies["k8s"].create_runner_pod.side_effect = Exception("K8s Error")
        
        with patch.object(create_runner_for_job, "retry") as mock_retry:
            mock_retry.side_effect = Exception("Retry")
            
            with pytest.raises(Exception, match="Retry"):
                create_runner_for_job(
                    org_name="test-org",
                    job_id=12345,
                    run_id=67890,
                    job_name="build",
                    repo_full_name="test-org/test-repo",
                    labels=["code-linux"]
                )


class TestProcessPendingQueues:
    """process_pending_queues 태스크 테스트"""
    
    @pytest.fixture
    def mock_dependencies(self, app_config):
        """태스크 의존성 Mock"""
        with patch("app.tasks.get_config") as mock_config, \
             patch("app.tasks.get_redis_client_sync") as mock_redis, \
             patch("app.tasks.KubernetesClient") as mock_k8s_cls, \
             patch("app.tasks._sync_running_state") as mock_sync:
            
            mock_config.return_value = app_config
            
            redis_client = MagicMock()
            mock_redis.return_value = redis_client
            
            k8s_client = MagicMock()
            mock_k8s_cls.return_value = k8s_client
            
            yield {
                "config": app_config,
                "redis": redis_client,
                "k8s": k8s_client,
                "sync": mock_sync
            }
    
    def test_process_skipped_when_total_limit_reached(self, mock_dependencies):
        """전체 제한 도달 시 건너뜀"""
        from app.tasks import process_pending_queues
        
        mock_dependencies["redis"].get_total_running_sync.return_value = 200  # max_total
        
        result = process_pending_queues()
        
        assert result["status"] == "skipped"
        assert result["reason"] == "total_limit_reached"
    
    def test_process_no_pending_jobs(self, mock_dependencies):
        """대기 중인 Job 없음"""
        from app.tasks import process_pending_queues
        
        mock_dependencies["redis"].get_total_running_sync.return_value = 10
        mock_dependencies["redis"].peek_all_pending_jobs_sync.return_value = []
        
        result = process_pending_queues()
        
        assert result["status"] == "no_pending_jobs"
    
    def test_process_jobs_respects_org_limit(self, mock_dependencies):
        """Org 제한 존중"""
        from app.tasks import process_pending_queues
        
        mock_dependencies["redis"].get_total_running_sync.return_value = 10
        
        # 대기 중인 Job
        pending_jobs = [
            ("test-org", 0, {"job_id": 12345, "org_name": "test-org", "run_id": 1, "job_name": "build", "repo_full_name": "test-org/repo", "labels": [], "timestamp": 1}),
            ("test-org", 1, {"job_id": 12346, "org_name": "test-org", "run_id": 2, "job_name": "build", "repo_full_name": "test-org/repo", "labels": [], "timestamp": 2}),
        ]
        mock_dependencies["redis"].peek_all_pending_jobs_sync.return_value = pending_jobs
        
        # Org 제한 도달
        mock_dependencies["redis"].get_org_running_count_sync.return_value = 10  # max_per_org
        mock_dependencies["redis"].get_effective_org_limit_sync.return_value = 10
        
        result = process_pending_queues()
        
        assert result["status"] == "no_available_slots"
    
    def test_process_jobs_creates_runners(self, mock_dependencies):
        """Job 처리 및 Runner 생성"""
        from app.tasks import process_pending_queues
        
        mock_dependencies["redis"].get_total_running_sync.return_value = 5
        
        # 대기 중인 Job
        pending_jobs = [
            ("test-org", 0, {"job_id": 12345, "org_name": "test-org", "run_id": 1, "job_name": "build", "repo_full_name": "test-org/repo", "labels": ["code-linux"], "timestamp": 1}),
        ]
        mock_dependencies["redis"].peek_all_pending_jobs_sync.return_value = pending_jobs
        
        # 여유 슬롯 있음
        mock_dependencies["redis"].get_org_running_count_sync.return_value = 3
        mock_dependencies["redis"].get_effective_org_limit_sync.return_value = 10
        mock_dependencies["redis"].remove_pending_jobs_by_job_ids_sync.return_value = 1
        
        with patch("app.tasks.create_runner_for_job") as mock_create:
            result = process_pending_queues()
            
            assert result["status"] == "processed"
            assert result["created"] == 1
            mock_create.delay.assert_called_once()
    
    def test_process_error_handling(self, mock_dependencies):
        """에러 처리"""
        from app.tasks import process_pending_queues
        
        mock_dependencies["redis"].get_total_running_sync.side_effect = Exception("Redis Error")
        
        result = process_pending_queues()
        
        assert result["status"] == "error"
        assert "error" in result


class TestCleanupStaleRunners:
    """cleanup_stale_runners 태스크 테스트"""
    
    @pytest.fixture
    def mock_dependencies(self, app_config):
        """태스크 의존성 Mock"""
        with patch("app.tasks.get_config") as mock_config, \
             patch("app.tasks.get_redis_client_sync") as mock_redis, \
             patch("app.tasks.KubernetesClient") as mock_k8s_cls:
            
            mock_config.return_value = app_config
            
            redis_client = MagicMock()
            mock_redis.return_value = redis_client
            
            k8s_client = MagicMock()
            mock_k8s_cls.return_value = k8s_client
            
            yield {
                "config": app_config,
                "redis": redis_client,
                "k8s": k8s_client
            }
    
    def test_cleanup_deletes_completed_pods(self, mock_dependencies):
        """완료된 Pod 삭제"""
        from app.tasks import cleanup_stale_runners
        
        # Succeeded Pod
        mock_pod = MagicMock()
        mock_pod.metadata.name = "jit-runner-12345"
        mock_pod.status.phase = "Succeeded"
        
        mock_dependencies["k8s"].list_runner_pods.return_value = [mock_pod]
        
        result = cleanup_stale_runners()
        
        assert result["status"] == "completed"
        assert result["deleted"] == 1
        mock_dependencies["k8s"].delete_runner_pod.assert_called_with("jit-runner-12345")
    
    def test_cleanup_deletes_failed_pods(self, mock_dependencies):
        """실패한 Pod 삭제"""
        from app.tasks import cleanup_stale_runners
        
        mock_pod = MagicMock()
        mock_pod.metadata.name = "jit-runner-12345"
        mock_pod.status.phase = "Failed"
        
        mock_dependencies["k8s"].list_runner_pods.return_value = [mock_pod]
        
        result = cleanup_stale_runners()
        
        assert result["deleted"] == 1
    
    def test_cleanup_keeps_running_pods(self, mock_dependencies):
        """실행 중인 Pod 유지"""
        from app.tasks import cleanup_stale_runners
        
        mock_pod = MagicMock()
        mock_pod.metadata.name = "jit-runner-12345"
        mock_pod.status.phase = "Running"
        
        mock_dependencies["k8s"].list_runner_pods.return_value = [mock_pod]
        
        result = cleanup_stale_runners()
        
        assert result["deleted"] == 0
        mock_dependencies["k8s"].delete_runner_pod.assert_not_called()
    
    def test_cleanup_error_handling(self, mock_dependencies):
        """에러 처리"""
        from app.tasks import cleanup_stale_runners
        
        mock_dependencies["k8s"].list_runner_pods.side_effect = Exception("K8s Error")
        
        result = cleanup_stale_runners()
        
        assert result["status"] == "error"


class TestSyncRedisState:
    """sync_redis_state 태스크 테스트"""
    
    @pytest.fixture
    def mock_dependencies(self, app_config):
        """태스크 의존성 Mock"""
        with patch("app.tasks.get_config") as mock_config, \
             patch("app.tasks.get_redis_client_sync") as mock_redis, \
             patch("app.tasks.KubernetesClient") as mock_k8s_cls, \
             patch("app.tasks._sync_running_state") as mock_sync:
            
            mock_config.return_value = app_config
            
            redis_client = MagicMock()
            mock_redis.return_value = redis_client
            
            k8s_client = MagicMock()
            mock_k8s_cls.return_value = k8s_client
            
            yield {
                "config": app_config,
                "redis": redis_client,
                "k8s": k8s_client,
                "sync": mock_sync
            }
    
    def test_sync_redis_state_success(self, mock_dependencies):
        """Redis 상태 동기화 성공"""
        from app.tasks import sync_redis_state
        
        result = sync_redis_state()
        
        assert result["status"] == "completed"
        mock_dependencies["sync"].assert_called_once()
    
    def test_sync_redis_state_error(self, mock_dependencies):
        """Redis 상태 동기화 에러"""
        from app.tasks import sync_redis_state
        
        mock_dependencies["sync"].side_effect = Exception("Sync Error")
        
        result = sync_redis_state()
        
        assert result["status"] == "error"


class TestSyncRunningState:
    """_sync_running_state 함수 테스트"""
    
    def test_sync_updates_total_count(self, app_config):
        """전체 카운트 업데이트"""
        with patch("app.tasks.get_config") as mock_config:
            mock_config.return_value = app_config
            
            from app.tasks import _sync_running_state
            
            mock_redis = MagicMock()
            mock_k8s = MagicMock()
            
            # Running Pod 2개
            mock_pod1 = MagicMock()
            mock_pod1.metadata.name = "jit-runner-1"
            mock_pod1.metadata.labels = {"org": "test-org"}
            mock_pod1.status.phase = "Running"
            
            mock_pod2 = MagicMock()
            mock_pod2.metadata.name = "jit-runner-2"
            mock_pod2.metadata.labels = {"org": "test-org"}
            mock_pod2.status.phase = "Running"
            
            mock_k8s.list_runner_pods.return_value = [mock_pod1, mock_pod2]
            
            # Redis에는 3으로 기록됨
            mock_redis.get_total_running_sync.return_value = 3
            mock_redis.get_all_runners_sync.return_value = {}
            
            _sync_running_state(mock_redis, mock_k8s)
            
            # 2로 업데이트
            mock_redis.set_total_running_sync.assert_called_with(2)
    
    def test_sync_removes_terminated_runner_info(self, app_config):
        """종료된 Runner 정보 삭제"""
        with patch("app.tasks.get_config") as mock_config:
            mock_config.return_value = app_config
            
            from app.tasks import _sync_running_state
            
            mock_redis = MagicMock()
            mock_k8s = MagicMock()
            
            # K8s에 실행 중인 Pod 없음
            mock_k8s.list_runner_pods.return_value = []
            
            mock_redis.get_total_running_sync.return_value = 0
            
            # Redis에 Runner 정보 있음
            mock_redis.get_all_runners_sync.return_value = {
                "jit-runner-12345": {"runner_name": "jit-runner-12345", "org_name": "test-org"}
            }
            
            _sync_running_state(mock_redis, mock_k8s)
            
            # Runner 정보 삭제
            mock_redis.delete_runner_info_sync.assert_called_with("jit-runner-12345")


class TestGetOrgsWithPendingJobs:
    """_get_orgs_with_pending_jobs 함수 테스트"""
    
    def test_returns_orgs_with_pending_jobs(self, app_config):
        """대기 중인 Job이 있는 Org 목록 반환"""
        from app.tasks import _get_orgs_with_pending_jobs
        
        mock_redis = MagicMock()
        mock_redis.client.scan_iter.return_value = iter([
            b"org:test-org-1:pending",
            b"org:test-org-2:pending"
        ])
        mock_redis.get_pending_job_count_sync.side_effect = [5, 0]  # org-1에만 Job 있음
        
        result = _get_orgs_with_pending_jobs(mock_redis)
        
        assert result == ["test-org-1"]
    
    def test_returns_empty_when_no_pending_jobs(self, app_config):
        """대기 중인 Job 없을 때 빈 목록"""
        from app.tasks import _get_orgs_with_pending_jobs
        
        mock_redis = MagicMock()
        mock_redis.client.scan_iter.return_value = iter([])
        
        result = _get_orgs_with_pending_jobs(mock_redis)
        
        assert result == []
