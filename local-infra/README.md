# Local Infrastructure for Integration Testing

JIT Runner Manager 통합 테스트를 위한 로컬 인프라 구성요소입니다.

## 디렉토리 구조

```
local-infra/
├── docker-compose.yaml      # 전체 인프라 구성
├── github-mock/             # GitHub API Mock 서버
│   ├── app.py              # FastAPI 앱
│   ├── Dockerfile
│   └── requirements.txt
├── kind/                    # Kubernetes 클러스터 설정
│   ├── cluster-config.yaml # Kind 설정
│   ├── setup-cluster.sh    # 생성 스크립트
│   └── teardown-cluster.sh # 삭제 스크립트
├── redis/
│   └── redis.conf          # Redis 설정
├── scripts/
│   ├── run-integration-tests.sh   # Linux/macOS 실행 스크립트
│   └── run-integration-tests.ps1  # Windows 실행 스크립트
└── README.md
```

## 빠른 시작

### Linux/macOS

```bash
# 전체 통합 테스트 실행
./local-infra/scripts/run-integration-tests.sh --all

# 특정 테스트만 실행
./local-infra/scripts/run-integration-tests.sh --redis
./local-infra/scripts/run-integration-tests.sh --github
./local-infra/scripts/run-integration-tests.sh --k8s
./local-infra/scripts/run-integration-tests.sh --e2e

# 인프라만 설정 (테스트 수동 실행)
./local-infra/scripts/run-integration-tests.sh --setup

# 인프라 정리
./local-infra/scripts/run-integration-tests.sh --teardown
```

### Windows (PowerShell)

```powershell
# 전체 통합 테스트 실행
.\local-infra\scripts\run-integration-tests.ps1 -All

# 특정 테스트만 실행
.\local-infra\scripts\run-integration-tests.ps1 -Redis
.\local-infra\scripts\run-integration-tests.ps1 -GitHub
.\local-infra\scripts\run-integration-tests.ps1 -K8s
.\local-infra\scripts\run-integration-tests.ps1 -E2E

# 인프라만 설정
.\local-infra\scripts\run-integration-tests.ps1 -Setup

# 인프라 정리
.\local-infra\scripts\run-integration-tests.ps1 -Teardown
```

## 수동 설정

### Docker Compose로 서비스 시작

```bash
cd local-infra
docker-compose up -d

# 상태 확인
docker-compose ps

# 로그 확인
docker-compose logs -f

# 종료
docker-compose down -v
```

### Kind 클러스터 설정

```bash
# 생성
./local-infra/kind/setup-cluster.sh

# 확인
kubectl get nodes --context kind-jit-runner-test

# 삭제
./local-infra/kind/teardown-cluster.sh
```

## 구성 요소

### Redis

- 이미지: `redis:7-alpine`
- 포트: `6379`
- 비밀번호: `testpassword`

### GitHub Mock Server

- 포트: `8080`
- 기본 Organization: `test-org`, `another-org`
- 테스트 헬퍼 API: `/test/*`

### Kind Kubernetes

- 클러스터 이름: `jit-runner-test`
- 네임스페이스: `jit-runners`

## 자세한 내용

전체 문서는 [docs/integration-testing.md](../docs/integration-testing.md)를 참조하세요.
