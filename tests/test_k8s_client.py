"""
Kubernetes 클라이언트 테스트

app/k8s_client.py의 KubernetesClient 테스트
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timedelta, timezone


class TestKubernetesClient:
    """KubernetesClient 테스트"""
    
    @pytest.fixture
    def k8s_client(self, app_config):
        """테스트용 KubernetesClient 인스턴스 (비활성화 상태)"""
        with patch("app.k8s_client.k8s_config") as mock_config:
            # Kubernetes 설정 로드 실패 시뮬레이션
            mock_config.load_incluster_config.side_effect = Exception("No incluster config")
            mock_config.load_kube_config.side_effect = Exception("No kubeconfig")
            
            from app.k8s_client import KubernetesClient
            client = KubernetesClient()
            
            assert client.enabled is False
            return client
    
    @pytest.fixture
    def k8s_client_enabled(self, app_config):
        """테스트용 KubernetesClient 인스턴스 (활성화 상태)"""
        with patch("app.k8s_client.k8s_config") as mock_config, \
             patch("app.k8s_client.client") as mock_client:
            
            mock_core_v1 = MagicMock()
            mock_client.CoreV1Api.return_value = mock_core_v1
            
            from app.k8s_client import KubernetesClient
            client = KubernetesClient()
            
            assert client.enabled is True
            client.core_v1 = mock_core_v1
            return client
    
    # ==================== 초기화 테스트 ====================
    
    def test_init_disabled_when_no_k8s_config(self, k8s_client):
        """Kubernetes 설정 없을 때 비활성화"""
        assert k8s_client.enabled is False
        assert k8s_client.core_v1 is None
    
    def test_init_enabled_when_k8s_available(self, k8s_client_enabled):
        """Kubernetes 사용 가능할 때 활성화"""
        assert k8s_client_enabled.enabled is True
        assert k8s_client_enabled.core_v1 is not None
    
    # ==================== Pod 생성 테스트 ====================
    
    def test_create_runner_pod_when_disabled(self, k8s_client, sample_jit_config):
        """비활성화 상태에서 Pod 생성 건너뜀"""
        result = k8s_client.create_runner_pod(
            runner_name="jit-runner-12345",
            org_name="test-org",
            job_id=12345,
            jit_config=sample_jit_config,
            labels=["code-linux"]
        )
        
        assert result is None
    
    def test_create_runner_pod_success(self, k8s_client_enabled, sample_jit_config):
        """Pod 생성 성공"""
        mock_pod = MagicMock()
        k8s_client_enabled.core_v1.create_namespaced_pod.return_value = mock_pod
        
        result = k8s_client_enabled.create_runner_pod(
            runner_name="jit-runner-12345",
            org_name="test-org",
            job_id=12345,
            jit_config=sample_jit_config,
            labels=["code-linux"]
        )
        
        assert result is mock_pod
        k8s_client_enabled.core_v1.create_namespaced_pod.assert_called_once()
        
        # 호출 인자 확인
        call_args = k8s_client_enabled.core_v1.create_namespaced_pod.call_args
        assert call_args.kwargs["namespace"] == "jit-runners"
    
    def test_create_runner_pod_with_correct_labels(self, k8s_client_enabled, sample_jit_config):
        """Pod 생성 시 올바른 레이블 설정"""
        with patch("app.k8s_client.client") as mock_client:
            # Mock V1Pod 구조
            mock_pod_class = MagicMock()
            mock_client.V1Pod = mock_pod_class
            mock_client.V1ObjectMeta = MagicMock()
            mock_client.V1PodSpec = MagicMock()
            mock_client.V1Container = MagicMock()
            mock_client.V1ResourceRequirements = MagicMock()
            mock_client.V1Volume = MagicMock()
            mock_client.V1VolumeMount = MagicMock()
            mock_client.V1EmptyDirVolumeSource = MagicMock()
            mock_client.V1EnvVar = MagicMock()
            mock_client.V1SecurityContext = MagicMock()
            
            k8s_client_enabled.core_v1.create_namespaced_pod.return_value = MagicMock()
            
            k8s_client_enabled.create_runner_pod(
                runner_name="jit-runner-12345",
                org_name="test-org",
                job_id=12345,
                jit_config=sample_jit_config,
                labels=["code-linux"]
            )
            
            # 메타데이터 호출 확인
            mock_client.V1ObjectMeta.assert_called_once()
            meta_call = mock_client.V1ObjectMeta.call_args
            labels = meta_call.kwargs.get("labels", {})
            assert labels["app"] == "jit-runner"
            assert labels["org"] == "test-org"
    
    def test_create_runner_pod_api_exception(self, k8s_client_enabled, sample_jit_config):
        """Pod 생성 시 API 예외 발생"""
        from kubernetes.client.rest import ApiException
        
        k8s_client_enabled.core_v1.create_namespaced_pod.side_effect = ApiException(
            status=500, reason="Internal Server Error"
        )
        
        with pytest.raises(ApiException):
            k8s_client_enabled.create_runner_pod(
                runner_name="jit-runner-12345",
                org_name="test-org",
                job_id=12345,
                jit_config=sample_jit_config,
                labels=["code-linux"]
            )
    
    # ==================== Pod 삭제 테스트 ====================
    
    def test_delete_runner_pod_when_disabled(self, k8s_client):
        """비활성화 상태에서 Pod 삭제 건너뜀"""
        # 예외 없이 반환
        k8s_client.delete_runner_pod("jit-runner-12345")
    
    def test_delete_runner_pod_success(self, k8s_client_enabled):
        """Pod 삭제 성공"""
        k8s_client_enabled.delete_runner_pod("jit-runner-12345")
        
        k8s_client_enabled.core_v1.delete_namespaced_pod.assert_called_once()
    
    def test_delete_runner_pod_force(self, k8s_client_enabled):
        """Pod 강제 삭제"""
        with patch("app.k8s_client.client") as mock_client:
            mock_client.V1DeleteOptions = MagicMock()
            
            k8s_client_enabled.delete_runner_pod("jit-runner-12345", force=True)
            
            # grace_period_seconds=0으로 호출되었는지 확인
            delete_options_call = mock_client.V1DeleteOptions.call_args
            assert delete_options_call.kwargs["grace_period_seconds"] == 0
    
    def test_delete_runner_pod_not_found(self, k8s_client_enabled):
        """Pod 삭제 시 404 처리"""
        from kubernetes.client.rest import ApiException
        
        k8s_client_enabled.core_v1.delete_namespaced_pod.side_effect = ApiException(
            status=404, reason="Not Found"
        )
        
        # 404는 예외 없이 처리
        k8s_client_enabled.delete_runner_pod("jit-runner-12345")
    
    # ==================== Pod 조회 테스트 ====================
    
    def test_get_runner_pod_when_disabled(self, k8s_client):
        """비활성화 상태에서 Pod 조회"""
        result = k8s_client.get_runner_pod("jit-runner-12345")
        
        assert result is None
    
    def test_get_runner_pod_success(self, k8s_client_enabled, mock_pod):
        """Pod 조회 성공"""
        k8s_client_enabled.core_v1.read_namespaced_pod.return_value = mock_pod
        
        result = k8s_client_enabled.get_runner_pod("jit-runner-12345")
        
        assert result is mock_pod
    
    def test_get_runner_pod_not_found(self, k8s_client_enabled):
        """Pod 조회 시 404"""
        from kubernetes.client.rest import ApiException
        
        k8s_client_enabled.core_v1.read_namespaced_pod.side_effect = ApiException(
            status=404, reason="Not Found"
        )
        
        result = k8s_client_enabled.get_runner_pod("jit-runner-12345")
        
        assert result is None
    
    # ==================== Pod 목록 조회 테스트 ====================
    
    def test_list_runner_pods_when_disabled(self, k8s_client):
        """비활성화 상태에서 Pod 목록 조회"""
        result = k8s_client.list_runner_pods()
        
        assert result == []
    
    def test_list_runner_pods_success(self, k8s_client_enabled, mock_pod):
        """Pod 목록 조회 성공"""
        mock_result = MagicMock()
        mock_result.items = [mock_pod]
        k8s_client_enabled.core_v1.list_namespaced_pod.return_value = mock_result
        
        result = k8s_client_enabled.list_runner_pods()
        
        assert len(result) == 1
        k8s_client_enabled.core_v1.list_namespaced_pod.assert_called_once()
    
    def test_list_runner_pods_with_org_filter(self, k8s_client_enabled, mock_pod):
        """특정 Org의 Pod 목록 조회"""
        mock_result = MagicMock()
        mock_result.items = [mock_pod]
        k8s_client_enabled.core_v1.list_namespaced_pod.return_value = mock_result
        
        k8s_client_enabled.list_runner_pods(org_name="test-org")
        
        call_args = k8s_client_enabled.core_v1.list_namespaced_pod.call_args
        assert "org=test-org" in call_args.kwargs["label_selector"]
    
    # ==================== Pod 상태 조회 테스트 ====================
    
    def test_get_pod_status_running(self, k8s_client_enabled, mock_pod):
        """Pod 상태 조회 - Running"""
        mock_pod.status.phase = "Running"
        k8s_client_enabled.core_v1.read_namespaced_pod.return_value = mock_pod
        
        status = k8s_client_enabled.get_pod_status("jit-runner-12345")
        
        assert status == "Running"
    
    def test_get_pod_status_not_found(self, k8s_client_enabled):
        """Pod 상태 조회 - 없는 경우"""
        from kubernetes.client.rest import ApiException
        
        k8s_client_enabled.core_v1.read_namespaced_pod.side_effect = ApiException(
            status=404, reason="Not Found"
        )
        
        status = k8s_client_enabled.get_pod_status("jit-runner-12345")
        
        assert status is None
    
    # ==================== Pod 로그 조회 테스트 ====================
    
    def test_get_pod_logs_when_disabled(self, k8s_client):
        """비활성화 상태에서 로그 조회"""
        result = k8s_client.get_pod_logs("jit-runner-12345")
        
        assert result == ""
    
    def test_get_pod_logs_success(self, k8s_client_enabled):
        """로그 조회 성공"""
        k8s_client_enabled.core_v1.read_namespaced_pod_log.return_value = "Log content"
        
        result = k8s_client_enabled.get_pod_logs("jit-runner-12345")
        
        assert result == "Log content"
    
    # ==================== 완료된 Pod 정리 테스트 ====================
    
    def test_cleanup_completed_pods_when_disabled(self, k8s_client):
        """비활성화 상태에서 정리"""
        result = k8s_client.cleanup_completed_pods()
        
        assert result == 0
    
    def test_cleanup_completed_pods_deletes_old_succeeded(self, k8s_client_enabled):
        """오래된 Succeeded Pod 삭제"""
        mock_pod = MagicMock()
        mock_pod.metadata.name = "jit-runner-12345"
        mock_pod.status.phase = "Succeeded"
        mock_pod.metadata.creation_timestamp = datetime.now(timezone.utc) - timedelta(hours=2)
        
        mock_result = MagicMock()
        mock_result.items = [mock_pod]
        k8s_client_enabled.core_v1.list_namespaced_pod.return_value = mock_result
        
        result = k8s_client_enabled.cleanup_completed_pods(max_age_minutes=60)
        
        assert result == 1
        k8s_client_enabled.core_v1.delete_namespaced_pod.assert_called_once()
    
    def test_cleanup_completed_pods_keeps_recent(self, k8s_client_enabled):
        """최근 완료된 Pod 유지"""
        mock_pod = MagicMock()
        mock_pod.metadata.name = "jit-runner-12345"
        mock_pod.status.phase = "Succeeded"
        mock_pod.metadata.creation_timestamp = datetime.now(timezone.utc) - timedelta(minutes=30)
        
        mock_result = MagicMock()
        mock_result.items = [mock_pod]
        k8s_client_enabled.core_v1.list_namespaced_pod.return_value = mock_result
        
        result = k8s_client_enabled.cleanup_completed_pods(max_age_minutes=60)
        
        assert result == 0
        k8s_client_enabled.core_v1.delete_namespaced_pod.assert_not_called()
    
    # ==================== 네임스페이스 확인 테스트 ====================
    
    def test_ensure_namespace_exists_when_disabled(self, k8s_client):
        """비활성화 상태에서 네임스페이스 확인"""
        # 예외 없이 반환
        k8s_client.ensure_namespace_exists()
    
    def test_ensure_namespace_exists_already_exists(self, k8s_client_enabled):
        """네임스페이스가 이미 존재할 때"""
        k8s_client_enabled.core_v1.read_namespace.return_value = MagicMock()
        
        k8s_client_enabled.ensure_namespace_exists()
        
        k8s_client_enabled.core_v1.create_namespace.assert_not_called()
    
    def test_ensure_namespace_exists_creates_new(self, k8s_client_enabled):
        """네임스페이스가 없을 때 생성"""
        from kubernetes.client.rest import ApiException
        
        k8s_client_enabled.core_v1.read_namespace.side_effect = ApiException(
            status=404, reason="Not Found"
        )
        
        with patch("app.k8s_client.client") as mock_client:
            mock_client.V1Namespace = MagicMock()
            mock_client.V1ObjectMeta = MagicMock()
            
            k8s_client_enabled.ensure_namespace_exists()
            
            k8s_client_enabled.core_v1.create_namespace.assert_called_once()
