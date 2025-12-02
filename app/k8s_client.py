"""
Kubernetes 클라이언트

Runner Pod 생성 및 관리
"""

import logging
import os
from typing import Dict, List, Optional

from kubernetes import client, config as k8s_config
from kubernetes.client.rest import ApiException

from app.config import get_config

logger = logging.getLogger(__name__)


class KubernetesClient:
    """Kubernetes API 클라이언트"""
    
    def __init__(self):
        self.app_config = get_config()
        
        # Kubernetes 설정 로드
        if self.app_config.kubernetes.in_cluster:
            k8s_config.load_incluster_config()
        else:
            k8s_config.load_kube_config()
        
        self.core_v1 = client.CoreV1Api()
        self.namespace = self.app_config.kubernetes.runner_namespace
    
    def create_runner_pod(
        self,
        runner_name: str,
        org_name: str,
        job_id: int,
        jit_config: Dict,
        labels: List[str]
    ) -> client.V1Pod:
        """
        Runner Pod 생성
        
        Args:
            runner_name: Runner 이름 (Pod 이름으로 사용)
            org_name: Organization 이름
            job_id: Workflow Job ID
            jit_config: JIT Runner 설정 (encoded_jit_config 포함)
            labels: Runner 라벨
        
        Returns:
            생성된 Pod 객체
        """
        config = self.app_config.kubernetes
        encoded_jit_config = jit_config.get("encoded_jit_config", "")
        
        # Pod 메타데이터
        metadata = client.V1ObjectMeta(
            name=runner_name,
            namespace=self.namespace,
            labels={
                "app": "jit-runner",
                "org": org_name,
                "job-id": str(job_id),
                "runner-name": runner_name
            },
            annotations={
                "jit-runner-manager/created-by": "jit-runner-manager",
                "jit-runner-manager/org": org_name,
                "jit-runner-manager/job-id": str(job_id)
            }
        )
        
        # Runner 컨테이너
        runner_container = client.V1Container(
            name="runner",
            image=config.runner_image,
            image_pull_policy="IfNotPresent",
            command=["/bin/sh", "-c"],
            args=[
                # JIT config를 사용하여 Runner 실행
                f'echo "{encoded_jit_config}" | base64 -d > /home/runner/.runner && '
                '/home/runner/run.sh --jitconfig /home/runner/.runner'
            ],
            env=[
                client.V1EnvVar(name="DOCKER_HOST", value="unix:///var/run/docker.sock"),
                client.V1EnvVar(name="RUNNER_ALLOW_RUNASROOT", value="1"),
            ],
            resources=client.V1ResourceRequirements(
                requests={
                    "cpu": config.runner_cpu_request,
                    "memory": config.runner_memory_request
                },
                limits={
                    "cpu": config.runner_cpu_limit,
                    "memory": config.runner_memory_limit
                }
            ),
            volume_mounts=[
                client.V1VolumeMount(name="work", mount_path="/home/runner/_work"),
                client.V1VolumeMount(name="dind-sock", mount_path="/var/run"),
            ]
        )
        
        # DinD 사이드카 컨테이너
        dind_container = client.V1Container(
            name="dind",
            image=config.dind_image,
            image_pull_policy="IfNotPresent",
            args=[
                "dockerd",
                "--host=unix:///var/run/docker.sock",
                "--host=tcp://0.0.0.0:2376"
            ],
            security_context=client.V1SecurityContext(
                privileged=True
            ),
            resources=client.V1ResourceRequirements(
                requests={
                    "cpu": config.dind_cpu_request,
                    "memory": config.dind_memory_request
                },
                limits={
                    "cpu": config.dind_cpu_limit,
                    "memory": config.dind_memory_limit
                }
            ),
            volume_mounts=[
                client.V1VolumeMount(name="work", mount_path="/home/runner/_work"),
                client.V1VolumeMount(name="dind-sock", mount_path="/var/run"),
                client.V1VolumeMount(name="dind-storage", mount_path="/var/lib/docker"),
            ]
        )
        
        # 볼륨 정의
        volumes = [
            client.V1Volume(name="work", empty_dir=client.V1EmptyDirVolumeSource()),
            client.V1Volume(name="dind-sock", empty_dir=client.V1EmptyDirVolumeSource()),
            client.V1Volume(name="dind-storage", empty_dir=client.V1EmptyDirVolumeSource()),
        ]
        
        # Pod 스펙
        spec = client.V1PodSpec(
            restart_policy="Never",
            containers=[runner_container, dind_container],
            volumes=volumes,
            # 완료 후 자동 삭제를 위한 TTL (Kubernetes 1.23+)
            # active_deadline_seconds=3600,  # 1시간 후 강제 종료
        )
        
        # Pod 생성
        pod = client.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=metadata,
            spec=spec
        )
        
        try:
            created_pod = self.core_v1.create_namespaced_pod(
                namespace=self.namespace,
                body=pod
            )
            logger.info(f"Runner Pod 생성됨: {runner_name}")
            return created_pod
            
        except ApiException as e:
            logger.error(f"Runner Pod 생성 실패: {e}")
            raise
    
    def delete_runner_pod(self, runner_name: str, force: bool = False) -> None:
        """
        Runner Pod 삭제
        
        Args:
            runner_name: 삭제할 Pod 이름
            force: 강제 삭제 여부
        """
        try:
            # 삭제 옵션
            delete_options = client.V1DeleteOptions(
                grace_period_seconds=0 if force else self.app_config.kubernetes.pod_cleanup_grace_period
            )
            
            self.core_v1.delete_namespaced_pod(
                name=runner_name,
                namespace=self.namespace,
                body=delete_options
            )
            logger.info(f"Runner Pod 삭제 요청됨: {runner_name}")
            
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"Runner Pod가 존재하지 않음: {runner_name}")
            else:
                logger.error(f"Runner Pod 삭제 실패: {e}")
                raise
    
    def get_runner_pod(self, runner_name: str) -> Optional[client.V1Pod]:
        """Runner Pod 조회"""
        try:
            return self.core_v1.read_namespaced_pod(
                name=runner_name,
                namespace=self.namespace
            )
        except ApiException as e:
            if e.status == 404:
                return None
            raise
    
    def list_runner_pods(
        self,
        org_name: Optional[str] = None,
        label_selector: Optional[str] = None
    ) -> List[client.V1Pod]:
        """
        Runner Pod 목록 조회
        
        Args:
            org_name: 특정 Organization의 Pod만 조회
            label_selector: 커스텀 라벨 셀렉터
        
        Returns:
            Pod 목록
        """
        if label_selector is None:
            label_selector = "app=jit-runner"
            if org_name:
                label_selector += f",org={org_name}"
        
        try:
            result = self.core_v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=label_selector
            )
            return result.items
            
        except ApiException as e:
            logger.error(f"Runner Pod 목록 조회 실패: {e}")
            raise
    
    def get_pod_status(self, runner_name: str) -> Optional[str]:
        """Pod 상태 조회"""
        pod = self.get_runner_pod(runner_name)
        if pod:
            return pod.status.phase
        return None
    
    def get_pod_logs(
        self,
        runner_name: str,
        container: str = "runner",
        tail_lines: int = 100
    ) -> str:
        """Pod 로그 조회"""
        try:
            return self.core_v1.read_namespaced_pod_log(
                name=runner_name,
                namespace=self.namespace,
                container=container,
                tail_lines=tail_lines
            )
        except ApiException as e:
            logger.error(f"Pod 로그 조회 실패: {e}")
            return ""
    
    def cleanup_completed_pods(self, max_age_minutes: int = 60) -> int:
        """
        완료된 Pod 정리
        
        Args:
            max_age_minutes: 이 시간(분)보다 오래된 완료 Pod 삭제
        
        Returns:
            삭제된 Pod 수
        """
        from datetime import datetime, timedelta, timezone
        
        deleted_count = 0
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        
        pods = self.list_runner_pods()
        for pod in pods:
            # Succeeded 또는 Failed 상태인 Pod
            if pod.status.phase in ["Succeeded", "Failed"]:
                # 생성 시간 확인
                if pod.metadata.creation_timestamp < cutoff_time:
                    try:
                        self.delete_runner_pod(pod.metadata.name)
                        deleted_count += 1
                    except Exception as e:
                        logger.warning(f"Pod 삭제 실패: {pod.metadata.name}, {e}")
        
        return deleted_count
    
    def ensure_namespace_exists(self) -> None:
        """네임스페이스가 존재하는지 확인하고 없으면 생성"""
        try:
            self.core_v1.read_namespace(name=self.namespace)
            logger.info(f"네임스페이스 존재: {self.namespace}")
        except ApiException as e:
            if e.status == 404:
                # 네임스페이스 생성
                namespace = client.V1Namespace(
                    metadata=client.V1ObjectMeta(
                        name=self.namespace,
                        labels={
                            "app": "jit-runner",
                            "managed-by": "jit-runner-manager"
                        }
                    )
                )
                self.core_v1.create_namespace(body=namespace)
                logger.info(f"네임스페이스 생성됨: {self.namespace}")
            else:
                raise

