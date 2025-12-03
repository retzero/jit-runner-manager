"""
GitHub API Mock Server

Integration 테스트를 위한 GitHub Enterprise Server API Mock 서버
GitHub API의 주요 엔드포인트를 시뮬레이션합니다.
"""

import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="GitHub API Mock Server",
    description="Integration 테스트용 GitHub API Mock",
    version="1.0.0"
)


# =============================================================================
# In-Memory Storage (테스트용 상태 저장)
# =============================================================================

class MockStorage:
    """테스트용 인메모리 저장소"""
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        """상태 초기화"""
        self.organizations: Dict[str, Dict] = {
            "test-org": {
                "id": 1,
                "login": "test-org",
                "name": "Test Organization",
                "type": "Organization"
            },
            "another-org": {
                "id": 2,
                "login": "another-org",
                "name": "Another Organization",
                "type": "Organization"
            }
        }
        
        self.runner_groups: Dict[str, List[Dict]] = {
            "test-org": [
                {"id": 1, "name": "default", "default": True, "visibility": "all"},
                {"id": 2, "name": "custom-group", "default": False, "visibility": "selected"}
            ],
            "another-org": [
                {"id": 3, "name": "default", "default": True, "visibility": "all"}
            ]
        }
        
        self.runners: Dict[str, List[Dict]] = {
            "test-org": [],
            "another-org": []
        }
        
        self.workflow_jobs: Dict[str, Dict] = {}
        
        # Runner ID counter
        self.next_runner_id = 100
        
        # API call tracking (테스트 검증용)
        self.api_calls: List[Dict] = []


storage = MockStorage()


# =============================================================================
# Request/Response Models
# =============================================================================

class JitConfigRequest(BaseModel):
    name: str
    runner_group_id: int
    labels: List[str]
    work_folder: str = "_work"


class RunnerResponse(BaseModel):
    id: int
    name: str
    os: str = "linux"
    status: str = "online"
    busy: bool = False
    labels: List[Dict[str, str]]


# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/")
async def root():
    """Health check"""
    return {"status": "ok", "service": "github-mock"}


@app.get("/api/v3")
async def api_root():
    """GitHub API root"""
    return {
        "current_user_url": "{origin}/api/v3/user",
        "organization_url": "{origin}/api/v3/orgs/{org}",
        "repository_url": "{origin}/api/v3/repos/{owner}/{repo}"
    }


# -----------------------------------------------------------------------------
# Organization Endpoints
# -----------------------------------------------------------------------------

@app.get("/api/v3/orgs/{org_name}")
async def get_organization(org_name: str, request: Request):
    """Organization 정보 조회"""
    _track_api_call("GET", f"/orgs/{org_name}", request)
    
    if org_name not in storage.organizations:
        raise HTTPException(status_code=404, detail=f"Organization not found: {org_name}")
    
    return storage.organizations[org_name]


# -----------------------------------------------------------------------------
# Runner Group Endpoints
# -----------------------------------------------------------------------------

@app.get("/api/v3/orgs/{org_name}/actions/runner-groups")
async def list_runner_groups(org_name: str, request: Request):
    """Runner 그룹 목록 조회"""
    _track_api_call("GET", f"/orgs/{org_name}/actions/runner-groups", request)
    
    if org_name not in storage.runner_groups:
        raise HTTPException(status_code=404, detail=f"Organization not found: {org_name}")
    
    return {
        "total_count": len(storage.runner_groups[org_name]),
        "runner_groups": storage.runner_groups[org_name]
    }


# -----------------------------------------------------------------------------
# Runner Endpoints
# -----------------------------------------------------------------------------

@app.get("/api/v3/orgs/{org_name}/actions/runners")
async def list_runners(org_name: str, request: Request):
    """Organization의 Runner 목록 조회"""
    _track_api_call("GET", f"/orgs/{org_name}/actions/runners", request)
    
    if org_name not in storage.runners:
        storage.runners[org_name] = []
    
    return {
        "total_count": len(storage.runners[org_name]),
        "runners": storage.runners[org_name]
    }


@app.get("/api/v3/orgs/{org_name}/actions/runners/{runner_id}")
async def get_runner(org_name: str, runner_id: int, request: Request):
    """특정 Runner 정보 조회"""
    _track_api_call("GET", f"/orgs/{org_name}/actions/runners/{runner_id}", request)
    
    if org_name not in storage.runners:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    for runner in storage.runners[org_name]:
        if runner["id"] == runner_id:
            return runner
    
    raise HTTPException(status_code=404, detail=f"Runner not found: {runner_id}")


@app.delete("/api/v3/orgs/{org_name}/actions/runners/{runner_id}")
async def delete_runner(org_name: str, runner_id: int, request: Request):
    """Runner 삭제"""
    _track_api_call("DELETE", f"/orgs/{org_name}/actions/runners/{runner_id}", request)
    
    if org_name not in storage.runners:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    for i, runner in enumerate(storage.runners[org_name]):
        if runner["id"] == runner_id:
            del storage.runners[org_name][i]
            return Response(status_code=204)
    
    raise HTTPException(status_code=404, detail=f"Runner not found: {runner_id}")


@app.post("/api/v3/orgs/{org_name}/actions/runners/registration-token")
async def create_registration_token(org_name: str, request: Request):
    """Runner 등록 토큰 생성"""
    _track_api_call("POST", f"/orgs/{org_name}/actions/runners/registration-token", request)
    
    if org_name not in storage.organizations:
        raise HTTPException(status_code=404, detail=f"Organization not found: {org_name}")
    
    return {
        "token": f"AAAAAA{uuid.uuid4().hex[:20].upper()}",
        "expires_at": "2099-12-31T23:59:59Z"
    }


@app.post("/api/v3/orgs/{org_name}/actions/runners/generate-jitconfig")
async def generate_jit_config(org_name: str, config: JitConfigRequest, request: Request):
    """JIT Runner 설정 생성"""
    _track_api_call("POST", f"/orgs/{org_name}/actions/runners/generate-jitconfig", request)
    
    if org_name not in storage.organizations:
        raise HTTPException(status_code=404, detail=f"Organization not found: {org_name}")
    
    # Runner 그룹 확인
    runner_groups = storage.runner_groups.get(org_name, [])
    group_valid = any(g["id"] == config.runner_group_id for g in runner_groups)
    if not group_valid:
        raise HTTPException(status_code=404, detail=f"Runner group not found: {config.runner_group_id}")
    
    # Runner 생성
    runner_id = storage.next_runner_id
    storage.next_runner_id += 1
    
    runner = {
        "id": runner_id,
        "name": config.name,
        "os": "linux",
        "status": "offline",  # JIT runner는 처음에 offline
        "busy": False,
        "labels": [{"id": i, "name": label, "type": "custom"} for i, label in enumerate(config.labels)]
    }
    
    if org_name not in storage.runners:
        storage.runners[org_name] = []
    storage.runners[org_name].append(runner)
    
    # JIT config 생성 (실제 GitHub에서는 암호화된 설정이 반환됨)
    jit_config_data = {
        "runner_name": config.name,
        "runner_id": runner_id,
        "org_name": org_name,
        "labels": config.labels,
        "work_folder": config.work_folder,
        "server_url": os.getenv("MOCK_GITHUB_URL", "http://localhost:8080"),
        "token": f"mock-jit-token-{runner_id}"
    }
    
    encoded_jit_config = base64.b64encode(
        json.dumps(jit_config_data).encode()
    ).decode()
    
    return {
        "runner": runner,
        "encoded_jit_config": encoded_jit_config
    }


# -----------------------------------------------------------------------------
# Workflow Job Endpoints
# -----------------------------------------------------------------------------

@app.get("/api/v3/repos/{owner}/{repo}/actions/jobs/{job_id}")
async def get_workflow_job(owner: str, repo: str, job_id: int, request: Request):
    """Workflow Job 정보 조회"""
    _track_api_call("GET", f"/repos/{owner}/{repo}/actions/jobs/{job_id}", request)
    
    job_key = f"{owner}/{repo}/{job_id}"
    
    if job_key in storage.workflow_jobs:
        return storage.workflow_jobs[job_key]
    
    # 기본 Mock Job 반환
    return {
        "id": job_id,
        "run_id": job_id * 10,
        "name": "build",
        "status": "queued",
        "conclusion": None,
        "started_at": None,
        "completed_at": None,
        "labels": ["code-linux"],
        "runner_id": None,
        "runner_name": None
    }


@app.get("/api/v3/repos/{owner}/{repo}/actions/runs")
async def list_workflow_runs(
    owner: str, 
    repo: str, 
    request: Request,
    status: Optional[str] = None,
    per_page: int = 30
):
    """Workflow Run 목록 조회"""
    _track_api_call("GET", f"/repos/{owner}/{repo}/actions/runs", request)
    
    return {
        "total_count": 0,
        "workflow_runs": []
    }


# =============================================================================
# Test Helper Endpoints (테스트 제어용)
# =============================================================================

@app.post("/test/reset")
async def reset_storage():
    """테스트용 상태 초기화"""
    storage.reset()
    return {"status": "ok", "message": "Storage reset"}


@app.post("/test/organizations/{org_name}")
async def create_test_organization(org_name: str):
    """테스트용 Organization 생성"""
    org_id = len(storage.organizations) + 1
    storage.organizations[org_name] = {
        "id": org_id,
        "login": org_name,
        "name": f"Test {org_name}",
        "type": "Organization"
    }
    storage.runner_groups[org_name] = [
        {"id": org_id * 10, "name": "default", "default": True, "visibility": "all"}
    ]
    storage.runners[org_name] = []
    return storage.organizations[org_name]


@app.post("/test/runners/{org_name}")
async def add_test_runner(org_name: str, runner: Dict):
    """테스트용 Runner 추가"""
    if org_name not in storage.runners:
        storage.runners[org_name] = []
    
    runner_id = runner.get("id", storage.next_runner_id)
    storage.next_runner_id = max(storage.next_runner_id, runner_id + 1)
    
    runner_data = {
        "id": runner_id,
        "name": runner.get("name", f"test-runner-{runner_id}"),
        "os": runner.get("os", "linux"),
        "status": runner.get("status", "online"),
        "busy": runner.get("busy", False),
        "labels": runner.get("labels", [])
    }
    storage.runners[org_name].append(runner_data)
    return runner_data


@app.put("/test/runners/{org_name}/{runner_id}/status")
async def update_runner_status(org_name: str, runner_id: int, status: Dict):
    """테스트용 Runner 상태 업데이트"""
    if org_name not in storage.runners:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    for runner in storage.runners[org_name]:
        if runner["id"] == runner_id:
            runner.update(status)
            return runner
    
    raise HTTPException(status_code=404, detail="Runner not found")


@app.post("/test/workflow-jobs/{owner}/{repo}/{job_id}")
async def set_workflow_job(owner: str, repo: str, job_id: int, job_data: Dict):
    """테스트용 Workflow Job 설정"""
    job_key = f"{owner}/{repo}/{job_id}"
    storage.workflow_jobs[job_key] = {
        "id": job_id,
        **job_data
    }
    return storage.workflow_jobs[job_key]


@app.get("/test/api-calls")
async def get_api_calls():
    """API 호출 기록 조회"""
    return {
        "total_count": len(storage.api_calls),
        "calls": storage.api_calls
    }


@app.delete("/test/api-calls")
async def clear_api_calls():
    """API 호출 기록 초기화"""
    storage.api_calls = []
    return {"status": "ok"}


@app.get("/test/state")
async def get_test_state():
    """현재 테스트 상태 조회"""
    return {
        "organizations": storage.organizations,
        "runner_groups": storage.runner_groups,
        "runners": storage.runners,
        "workflow_jobs": storage.workflow_jobs
    }


# =============================================================================
# Helper Functions
# =============================================================================

def _track_api_call(method: str, endpoint: str, request: Request):
    """API 호출 추적"""
    storage.api_calls.append({
        "method": method,
        "endpoint": endpoint,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "headers": dict(request.headers)
    })


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
