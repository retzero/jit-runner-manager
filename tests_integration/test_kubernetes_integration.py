"""
Kubernetes Integration Tests

실제 Kubernetes 클러스터(Kind)와의 통합 테스트
"""

import time
import pytest


@pytest.mark.integration
@pytest.mark.kubernetes
class TestKubernetesConnection:
    """Kubernetes 연결 테스트"""
    
    def test_cluster_connection(self, k8s_client):
        """클러스터 연결 확인"""
        # 노드 목록 조회로 연결 확인
        nodes = k8s_client.list_node()
        assert len(nodes.items) >= 1
    
    def test_namespace_exists(self, k8s_client, integration_env):
        """jit-runners 네임스페이스 존재 확인"""
        namespace = integration_env["RUNNER_NAMESPACE"]
        
        try:
            ns = k8s_client.read_namespace(name=namespace)
            assert ns.metadata.name == namespace
        except Exception:
            # 네임스페이스 생성
            from kubernetes import client
            
            ns_body = client.V1Namespace(
                metadata=client.V1ObjectMeta(name=namespace)
            )
            k8s_client.create_namespace(body=ns_body)
            
            ns = k8s_client.read_namespace(name=namespace)
            assert ns.metadata.name == namespace


@pytest.mark.integration
@pytest.mark.kubernetes
class TestPodOperations:
    """Pod 작업 테스트"""
    
    def test_create_simple_pod(self, k8s_client, clean_k8s_namespace, integration_env):
        """간단한 Pod 생성 테스트"""
        from kubernetes import client
        
        namespace = integration_env["RUNNER_NAMESPACE"]
        pod_name = "integration-test-pod"
        
        # Pod 정의
        pod = client.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=client.V1ObjectMeta(
                name=pod_name,
                labels={
                    "app": "integration-test",
                    "test": "true"
                }
            ),
            spec=client.V1PodSpec(
                restart_policy="Never",
                containers=[
                    client.V1Container(
                        name="test-container",
                        image="busybox:latest",
                        command=["sh", "-c", "echo 'test' && sleep 30"],
                        resources=client.V1ResourceRequirements(
                            requests={"cpu": "50m", "memory": "64Mi"},
                            limits={"cpu": "100m", "memory": "128Mi"}
                        )
                    )
                ]
            )
        )
        
        try:
            # Pod 생성
            created_pod = k8s_client.create_namespaced_pod(
                namespace=namespace,
                body=pod
            )
            assert created_pod.metadata.name == pod_name
            
            # Pod 상태 확인 (Pending 또는 Running)
            time.sleep(2)
            pod_status = k8s_client.read_namespaced_pod_status(
                name=pod_name,
                namespace=namespace
            )
            assert pod_status.status.phase in ["Pending", "Running", "Succeeded"]
            
        finally:
            # 정리
            try:
                k8s_client.delete_namespaced_pod(
                    name=pod_name,
                    namespace=namespace
                )
            except Exception:
                pass
    
    def test_list_pods_with_label_selector(self, k8s_client, clean_k8s_namespace, integration_env):
        """Label selector로 Pod 목록 조회"""
        from kubernetes import client
        
        namespace = integration_env["RUNNER_NAMESPACE"]
        
        # 테스트 Pod 생성
        pod_names = ["test-pod-1", "test-pod-2"]
        for pod_name in pod_names:
            pod = client.V1Pod(
                api_version="v1",
                kind="Pod",
                metadata=client.V1ObjectMeta(
                    name=pod_name,
                    labels={
                        "app": "jit-runner",
                        "org": "test-org",
                        "test": "list-test"
                    }
                ),
                spec=client.V1PodSpec(
                    restart_policy="Never",
                    containers=[
                        client.V1Container(
                            name="test-container",
                            image="busybox:latest",
                            command=["sleep", "60"]
                        )
                    ]
                )
            )
            k8s_client.create_namespaced_pod(namespace=namespace, body=pod)
        
        try:
            # Label selector로 조회
            pods = k8s_client.list_namespaced_pod(
                namespace=namespace,
                label_selector="app=jit-runner,org=test-org"
            )
            
            found_names = [p.metadata.name for p in pods.items]
            for pod_name in pod_names:
                assert pod_name in found_names
            
        finally:
            # 정리
            for pod_name in pod_names:
                try:
                    k8s_client.delete_namespaced_pod(
                        name=pod_name,
                        namespace=namespace
                    )
                except Exception:
                    pass
    
    def test_delete_pod(self, k8s_client, clean_k8s_namespace, integration_env):
        """Pod 삭제 테스트"""
        from kubernetes import client
        from kubernetes.client.rest import ApiException
        
        namespace = integration_env["RUNNER_NAMESPACE"]
        pod_name = "test-delete-pod"
        
        # Pod 생성
        pod = client.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=client.V1ObjectMeta(
                name=pod_name,
                labels={"app": "jit-runner"}
            ),
            spec=client.V1PodSpec(
                restart_policy="Never",
                containers=[
                    client.V1Container(
                        name="test-container",
                        image="busybox:latest",
                        command=["sleep", "60"]
                    )
                ]
            )
        )
        k8s_client.create_namespaced_pod(namespace=namespace, body=pod)
        
        # Pod 존재 확인
        pod_exists = k8s_client.read_namespaced_pod(
            name=pod_name,
            namespace=namespace
        )
        assert pod_exists is not None
        
        # Pod 삭제
        k8s_client.delete_namespaced_pod(
            name=pod_name,
            namespace=namespace,
            body=client.V1DeleteOptions(grace_period_seconds=0)
        )
        
        # 삭제 확인 (약간의 대기 후)
        time.sleep(2)
        try:
            k8s_client.read_namespaced_pod(
                name=pod_name,
                namespace=namespace
            )
            # Pod가 아직 Terminating 상태일 수 있음
        except ApiException as e:
            # 404면 정상적으로 삭제됨
            assert e.status == 404


@pytest.mark.integration
@pytest.mark.kubernetes
class TestRunnerPodTemplate:
    """Runner Pod 템플릿 테스트"""
    
    def test_runner_pod_structure(self, k8s_client, clean_k8s_namespace, integration_env):
        """Runner Pod 구조 테스트 (DinD 없는 단순 버전)"""
        from kubernetes import client
        
        namespace = integration_env["RUNNER_NAMESPACE"]
        runner_name = "test-runner-structure"
        
        # 실제 Runner Pod 구조와 유사한 Pod 생성
        pod = client.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=client.V1ObjectMeta(
                name=runner_name,
                labels={
                    "app": "jit-runner",
                    "org": "test-org",
                    "job-id": "12345",
                    "runner-name": runner_name
                },
                annotations={
                    "jit-runner-manager/created-by": "jit-runner-manager",
                    "jit-runner-manager/org": "test-org",
                    "jit-runner-manager/job-id": "12345"
                }
            ),
            spec=client.V1PodSpec(
                restart_policy="Never",
                containers=[
                    client.V1Container(
                        name="runner",
                        image="busybox:latest",
                        command=["sh", "-c", "echo 'Mock runner' && sleep 30"],
                        resources=client.V1ResourceRequirements(
                            requests={"cpu": "100m", "memory": "128Mi"},
                            limits={"cpu": "500m", "memory": "512Mi"}
                        ),
                        volume_mounts=[
                            client.V1VolumeMount(
                                name="work",
                                mount_path="/home/runner/_work"
                            )
                        ]
                    )
                ],
                volumes=[
                    client.V1Volume(
                        name="work",
                        empty_dir=client.V1EmptyDirVolumeSource()
                    )
                ]
            )
        )
        
        try:
            created_pod = k8s_client.create_namespaced_pod(
                namespace=namespace,
                body=pod
            )
            
            # 구조 검증
            assert created_pod.metadata.labels["app"] == "jit-runner"
            assert created_pod.metadata.labels["org"] == "test-org"
            assert created_pod.metadata.annotations["jit-runner-manager/created-by"] == "jit-runner-manager"
            
            # 컨테이너 검증
            assert len(created_pod.spec.containers) == 1
            assert created_pod.spec.containers[0].name == "runner"
            
            # 볼륨 검증
            volume_names = [v.name for v in created_pod.spec.volumes]
            assert "work" in volume_names
            
        finally:
            try:
                k8s_client.delete_namespaced_pod(
                    name=runner_name,
                    namespace=namespace
                )
            except Exception:
                pass
