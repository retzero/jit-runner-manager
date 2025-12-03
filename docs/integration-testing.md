# Integration Testing Guide

JIT Runner Manager의 통합 테스트 환경 구성 및 실행 가이드입니다.

## 목차

- [개요](#개요)
- [테스트 인프라 구성](#테스트-인프라-구성)
- [로컬 환경에서 테스트 실행](#로컬-환경에서-테스트-실행)
- [GitHub Actions에서 테스트](#github-actions에서-테스트)
- [테스트 구성 요소](#테스트-구성-요소)
- [문제 해결](#문제-해결)

## 개요

통합 테스트는 다음 외부 서비스들과의 실제 통합을 검증합니다:

1. **Redis** - 상태 관리 및 작업 큐
2. **Kubernetes (Kind)** - Runner Pod 생성/관리
3. **GitHub API (Mock)** - GitHub Enterprise Server API 시뮬레이션

통합 테스트는 일반 단위 테스트(`pytest`)와 분리되어 있으며, `--integration` 플래그로 명시적으로 실행해야 합니다.

## 테스트 인프라 구성

### 디렉토리 구조

```
local-infra/
├── docker-compose.yaml      # 전체 인프라 Docker Compose
├── github-mock/             # GitHub API Mock 서버
│   ├── app.py              # FastAPI 기반 Mock 서버
│   ├── Dockerfile
│   └── requirements.txt
├── kind/                    # Kind Kubernetes 클러스터 설정
│   ├── cluster-config.yaml # 클러스터 구성
│   ├── setup-cluster.sh    # 클러스터 생성 스크립트
│   └── teardown-cluster.sh # 클러스터 삭제 스크립트
└── redis/
    └── redis.conf          # Redis 설정 파일
```

### 필수 도구 설치

#### Docker & Docker Compose

```bash
# Docker 설치 (Ubuntu)
sudo apt-get update
sudo apt-get install docker.io docker-compose-plugin

# Docker 서비스 시작
sudo systemctl start docker
sudo systemctl enable docker
```

#### Kind (Kubernetes in Docker)

```bash
# Kind 설치 (Linux/macOS)
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind

# 설치 확인
kind version
```

#### kubectl

```bash
# kubectl 설치
curl -LO "https://dl.k8s.io/release/v1.28.0/bin/linux/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/kubectl

# 설치 확인
kubectl version --client
```

## 로컬 환경에서 테스트 실행

### 방법 1: Docker Compose 사용 (권장)

전체 인프라를 Docker Compose로 실행합니다:

```bash
# 인프라 시작
docker-compose -f local-infra/docker-compose.yaml up -d

# 서비스 상태 확인
docker-compose -f local-infra/docker-compose.yaml ps

# 로그 확인
docker-compose -f local-infra/docker-compose.yaml logs -f

# 인프라 종료
docker-compose -f local-infra/docker-compose.yaml down -v
```

### 방법 2: 개별 서비스 실행

#### 1. Redis 시작

```bash
# Docker로 Redis 실행
docker run -d --name redis-test \
  -p 6379:6379 \
  redis:7-alpine \
  redis-server --requirepass testpassword

# 연결 테스트
redis-cli -h localhost -a testpassword ping
```

#### 2. GitHub Mock 서버 시작

```bash
# 의존성 설치
pip install -r local-infra/github-mock/requirements.txt

# 서버 실행
cd local-infra/github-mock
PORT=8080 python app.py

# 다른 터미널에서 확인
curl http://localhost:8080/
```

#### 3. Kind 클러스터 생성

```bash
# 클러스터 생성
chmod +x local-infra/kind/setup-cluster.sh
./local-infra/kind/setup-cluster.sh

# 클러스터 확인
kubectl get nodes --context kind-jit-runner-test

# 테스트 후 삭제
./local-infra/kind/teardown-cluster.sh
```

### 통합 테스트 실행

```bash
# 환경 변수 설정
export GHES_URL=http://localhost:8080
export GHES_API_URL=http://localhost:8080/api/v3
export GITHUB_PAT=test-integration-token
export WEBHOOK_SECRET=test-webhook-secret
export REDIS_URL=redis://localhost:6379/0
export REDIS_PASSWORD=testpassword
export ADMIN_API_KEY=test-admin-key
export RUNNER_NAMESPACE=jit-runners

# 전체 통합 테스트 실행
pytest tests_integration/ -v --integration

# 특정 테스트만 실행
pytest tests_integration/test_redis_integration.py -v --integration
pytest tests_integration/test_github_mock_integration.py -v --integration
pytest tests_integration/test_kubernetes_integration.py -v --integration
pytest tests_integration/test_end_to_end.py -v --integration

# 특정 마커로 필터링
pytest tests_integration/ -v --integration -m "redis"
pytest tests_integration/ -v --integration -m "kubernetes"
pytest tests_integration/ -v --integration -m "github_mock"
```

## GitHub Actions에서 테스트

### 워크플로우 구성

통합 테스트는 `.github/workflows/integration-test.yml`에 정의되어 있습니다:

- **integration-basic**: Redis와 GitHub Mock 테스트
- **integration-kubernetes**: Kind 클러스터를 사용한 Kubernetes 테스트
- **integration-full**: main 브랜치 푸시 시 전체 통합 테스트

### 수동 실행

GitHub Actions에서 수동으로 워크플로우를 실행할 수 있습니다:

1. Repository → Actions → Integration Tests
2. "Run workflow" 클릭
3. 옵션 선택 (예: Kubernetes 테스트 스킵)
4. "Run workflow" 확인

## 테스트 구성 요소

### GitHub Mock API 서버

`local-infra/github-mock/app.py`는 다음 API 엔드포인트를 제공합니다:

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /api/v3/orgs/{org}` | Organization 정보 조회 |
| `GET /api/v3/orgs/{org}/actions/runner-groups` | Runner 그룹 목록 |
| `GET /api/v3/orgs/{org}/actions/runners` | Runner 목록 |
| `POST /api/v3/orgs/{org}/actions/runners/generate-jitconfig` | JIT Config 생성 |
| `DELETE /api/v3/orgs/{org}/actions/runners/{id}` | Runner 삭제 |
| `GET /api/v3/repos/{owner}/{repo}/actions/jobs/{id}` | Workflow Job 조회 |

#### 테스트 헬퍼 엔드포인트

| 엔드포인트 | 설명 |
|-----------|------|
| `POST /test/reset` | Mock 상태 초기화 |
| `POST /test/organizations/{org}` | 테스트 Organization 생성 |
| `POST /test/runners/{org}` | 테스트 Runner 추가 |
| `GET /test/api-calls` | API 호출 기록 조회 |
| `GET /test/state` | 현재 Mock 상태 조회 |

### Kind 클러스터 설정

`local-infra/kind/cluster-config.yaml`의 주요 설정:

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: jit-runner-test
nodes:
  - role: control-plane
networking:
  podSubnet: "10.244.0.0/16"
  serviceSubnet: "10.96.0.0/12"
```

### 테스트 마커

| 마커 | 설명 |
|-----|------|
| `@pytest.mark.integration` | 통합 테스트 표시 |
| `@pytest.mark.redis` | Redis 필요 |
| `@pytest.mark.kubernetes` | Kubernetes 클러스터 필요 |
| `@pytest.mark.github_mock` | GitHub Mock 서버 필요 |

## 환경 변수

| 변수 | 기본값 | 설명 |
|-----|-------|------|
| `GHES_URL` | `http://localhost:8080` | GitHub Mock 서버 URL |
| `GHES_API_URL` | `http://localhost:8080/api/v3` | GitHub API URL |
| `GITHUB_PAT` | `test-integration-token` | 테스트용 PAT |
| `WEBHOOK_SECRET` | `test-webhook-secret` | Webhook 서명 시크릿 |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 연결 URL |
| `REDIS_PASSWORD` | `testpassword` | Redis 비밀번호 |
| `ADMIN_API_KEY` | `test-admin-key` | Admin API 키 |
| `APP_URL` | `http://localhost:8000` | 앱 서버 URL |
| `RUNNER_NAMESPACE` | `jit-runners` | Kubernetes 네임스페이스 |

## 문제 해결

### Redis 연결 실패

```bash
# Redis 컨테이너 확인
docker ps | grep redis

# Redis 로그 확인
docker logs redis-test

# 수동 연결 테스트
redis-cli -h localhost -p 6379 -a testpassword ping
```

### GitHub Mock 서버 연결 실패

```bash
# 프로세스 확인
ps aux | grep "python.*app.py"

# 포트 사용 확인
netstat -tlnp | grep 8080

# 수동 테스트
curl -v http://localhost:8080/
```

### Kind 클러스터 문제

```bash
# 클러스터 상태 확인
kind get clusters

# 클러스터 삭제 후 재생성
kind delete cluster --name jit-runner-test
./local-infra/kind/setup-cluster.sh

# Docker 리소스 정리
docker system prune -f
```

### 테스트가 스킵되는 경우

`--integration` 플래그 없이 실행하면 통합 테스트가 스킵됩니다:

```bash
# 잘못된 방법 (테스트 스킵됨)
pytest tests_integration/

# 올바른 방법
pytest tests_integration/ --integration
```

### Kubernetes 테스트 실패

```bash
# 네임스페이스 확인
kubectl get ns --context kind-jit-runner-test

# jit-runners 네임스페이스 생성
kubectl create namespace jit-runners --context kind-jit-runner-test

# RBAC 권한 확인
kubectl auth can-i create pods --namespace jit-runners --context kind-jit-runner-test
```

## 추가 리소스

- [Kind 문서](https://kind.sigs.k8s.io/)
- [pytest 마커](https://docs.pytest.org/en/stable/how-to/mark.html)
- [GitHub Actions 서비스 컨테이너](https://docs.github.com/en/actions/using-containerized-services)
