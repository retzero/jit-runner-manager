"""
GitHub API 클라이언트

JIT Runner 토큰 발급 및 Runner 관리
"""

import base64
import logging
from typing import Dict, List, Optional

import requests

from app.config import get_config

logger = logging.getLogger(__name__)


class GitHubClient:
    """GitHub Enterprise Server API 클라이언트"""
    
    def __init__(self):
        self.config = get_config()
        self.base_url = f"{self.config.github.api_url}"
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.config.github.pat}",
            "X-GitHub-Api-Version": self.config.github.api_version
        }
    
    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Dict:
        """API 요청 실행"""
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
                params=params,
                timeout=30
            )
            response.raise_for_status()
            
            if response.content:
                return response.json()
            return {}
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"GitHub API 오류: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"GitHub API 요청 실패: {e}")
            raise
    
    def get_organization(self, org_name: str) -> Dict:
        """Organization 정보 조회"""
        return self._request("GET", f"/orgs/{org_name}")
    
    def list_org_runners(self, org_name: str) -> List[Dict]:
        """Organization의 Runner 목록 조회"""
        result = self._request("GET", f"/orgs/{org_name}/actions/runners")
        return result.get("runners", [])
    
    def get_runner(self, org_name: str, runner_id: int) -> Dict:
        """특정 Runner 정보 조회"""
        return self._request("GET", f"/orgs/{org_name}/actions/runners/{runner_id}")
    
    def delete_runner(self, org_name: str, runner_id: int) -> None:
        """Runner 삭제"""
        self._request("DELETE", f"/orgs/{org_name}/actions/runners/{runner_id}")
    
    def create_registration_token(self, org_name: str) -> str:
        """
        Organization용 Runner 등록 토큰 생성
        
        Returns:
            등록 토큰 문자열
        """
        result = self._request(
            "POST",
            f"/orgs/{org_name}/actions/runners/registration-token"
        )
        return result.get("token")
    
    def create_jit_runner_config(
        self,
        org_name: str,
        runner_name: str,
        labels: List[str],
        runner_group: str = "default",
        work_folder: str = "_work"
    ) -> Dict:
        """
        JIT (Just-In-Time) Runner 설정 생성
        
        GitHub API를 통해 JIT runner를 생성하고 설정 정보를 반환합니다.
        
        Args:
            org_name: Organization 이름
            runner_name: Runner 이름
            labels: Runner 라벨 목록
            runner_group: Runner 그룹 이름
            work_folder: 작업 폴더 경로
        
        Returns:
            JIT runner 설정 정보 (encoded_jit_config 포함)
        """
        # Runner 그룹 ID 조회
        runner_group_id = self._get_runner_group_id(org_name, runner_group)
        
        # JIT Runner 생성 요청
        data = {
            "name": runner_name,
            "runner_group_id": runner_group_id,
            "labels": labels,
            "work_folder": work_folder
        }
        
        result = self._request(
            "POST",
            f"/orgs/{org_name}/actions/runners/generate-jitconfig",
            data=data
        )
        
        return {
            "runner_name": runner_name,
            "runner_id": result.get("runner", {}).get("id"),
            "encoded_jit_config": result.get("encoded_jit_config"),
            "org_name": org_name,
            "labels": labels
        }
    
    def _get_runner_group_id(self, org_name: str, group_name: str) -> int:
        """Runner 그룹 ID 조회"""
        result = self._request(
            "GET",
            f"/orgs/{org_name}/actions/runner-groups"
        )
        
        for group in result.get("runner_groups", []):
            if group.get("name") == group_name:
                return group.get("id")
        
        # 기본 그룹 반환
        for group in result.get("runner_groups", []):
            if group.get("default"):
                return group.get("id")
        
        raise ValueError(f"Runner 그룹을 찾을 수 없습니다: {group_name}")
    
    def remove_runner_by_name(self, org_name: str, runner_name: str) -> bool:
        """
        이름으로 Runner 삭제
        
        Args:
            org_name: Organization 이름
            runner_name: Runner 이름
        
        Returns:
            삭제 성공 여부
        """
        try:
            runners = self.list_org_runners(org_name)
            for runner in runners:
                if runner.get("name") == runner_name:
                    self.delete_runner(org_name, runner.get("id"))
                    logger.info(f"GitHub에서 Runner 삭제됨: {runner_name}")
                    return True
            
            logger.warning(f"GitHub에서 Runner를 찾을 수 없음: {runner_name}")
            return False
            
        except Exception as e:
            logger.error(f"Runner 삭제 실패: {e}")
            return False
    
    def get_workflow_job(self, owner: str, repo: str, job_id: int) -> Dict:
        """Workflow Job 정보 조회"""
        return self._request(
            "GET",
            f"/repos/{owner}/{repo}/actions/jobs/{job_id}"
        )
    
    def list_workflow_runs(
        self,
        owner: str,
        repo: str,
        status: Optional[str] = None,
        per_page: int = 30
    ) -> List[Dict]:
        """Workflow Run 목록 조회"""
        params = {"per_page": per_page}
        if status:
            params["status"] = status
        
        result = self._request(
            "GET",
            f"/repos/{owner}/{repo}/actions/runs",
            params=params
        )
        return result.get("workflow_runs", [])


class GitHubClientAsync:
    """비동기 GitHub API 클라이언트 (향후 확장용)"""
    
    def __init__(self):
        self.config = get_config()
        self.base_url = f"{self.config.github.api_url}"
    
    # 필요시 aiohttp를 사용한 비동기 구현 추가
    pass

