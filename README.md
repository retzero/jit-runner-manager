# JIT Runner Manager

GitHub Enterprise Server 환경에서 1000개 이상의 Organization을 지원하는 Just-In-Time Self-Hosted Runner 관리 시스템입니다.

---

## 목차

1. [개요](#개요)
2. [아키텍처](#아키텍처)
3. [주요 기능](#주요-기능)
4. [사전 요구사항](#사전-요구사항)
5. [설치 가이드](#설치-가이드)
6. [설정](#설정)
7. [운영 가이드](#운영-가이드)
8. [모니터링](#모니터링)
9. [트러블슈팅](#트러블슈팅)
10. [API 레퍼런스](#api-레퍼런스)

### 상세 문서

- [Runner 생성 로직 상세 설명](docs/runner-creation-logic.md) - 대기열 처리 및 제한 로직
- [Enterprise Webhook 설정 가이드](docs/enterprise-webhook-setup.md) - GitHub Webhook 구성

---

## 개요

### 배경

GitHub Actions의 Self-Hosted Runner를 대규모로 운영할 때 다음과 같은 문제가 발생합니다:

- **ARC(Actions Runner Controller)의 한계**: Organization별로 Runner Scale Set을 배포하면 각각 Listener Pod가 필요하여 1000개 Organization 기준 ~128GB 메모리 오버헤드 발생
- **리소스 효율성**: 미리 모든 Organization에 runner를 등록해두면 유휴 리소스 낭비

### 솔루션

JIT Runner Manager는 Enterprise Webhook을 통해 workflow 요청을 실시간으로 수신하고, 필요한 순간에만 Runner를 동적으로 생성합니다.

| 항목 | ARC (Org별) | JIT Runner Manager |
|------|------------|-------------------|
| 1000 Org 지원 | 어려움 | **지원** |
| Listener Pod | 1,000개 | **0개** |
| 메모리 오버헤드 | ~128GB | **~2GB** |
| Org별 제한 | 가능 | **가능** |
| 실시간 스케일링 | 가능 | **가능** |

---

## 아키텍처

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     GitHub Enterprise Server 3.14.17                     │
│                                                                          │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐         ┌──────────┐          │
│   │  Org A   │ │  Org B   │ │  Org C   │   ...   │ Org 1000 │          │
│   │ Workflow │ │ Workflow │ │ Workflow │         │ Workflow │          │
│   └────┬─────┘ └────┬─────┘ └────┬─────┘         └────┬─────┘          │
│        │            │            │                    │                 │
│        └────────────┴────────────┴────────────────────┘                 │
│                              │                                          │
│                   Enterprise Webhook                                    │
│                    (workflow_job)                                       │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                        Kubernetes Cluster                                 │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │                    JIT Runner Manager                               │  │
│  │                                                                     │  │
│  │   ┌─────────────────┐      ┌─────────────────┐                     │  │
│  │   │ FastAPI Webhook │      │     Redis       │                     │  │
│  │   │    Receiver     │─────▶│  State Store    │                     │  │
│  │   │   (Port 8000)   │      │  Message Queue  │                     │  │
│  │   └────────┬────────┘      └────────┬────────┘                     │  │
│  │            │                        │                              │  │
│  │            │    ┌───────────────────┘                              │  │
│  │            │    │                                                  │  │
│  │            ▼    ▼                                                  │  │
│  │   ┌─────────────────┐                                              │  │
│  │   │ Celery Workers  │                                              │  │
│  │   │ - Runner 생성    │                                              │  │
│  │   │ - Runner 정리    │                                              │  │
│  │   │ - 상태 관리      │                                              │  │
│  │   └────────┬────────┘                                              │  │
│  │            │                                                       │  │
│  └────────────┼───────────────────────────────────────────────────────┘  │
│               │                                                          │
│               ▼                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │                     Runner Pods (Dynamic)                          │  │
│  │                                                                     │  │
│  │   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐                 │  │
│  │   │Runner 1 │ │Runner 2 │ │Runner 3 │ │   ...   │  Max 200       │  │
│  │   │(Org A)  │ │(Org A)  │ │(Org B)  │ │         │                 │  │
│  │   │DinD     │ │DinD     │ │DinD     │ │         │                 │  │
│  │   └─────────┘ └─────────┘ └─────────┘ └─────────┘                 │  │
│  │                                                                     │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

### 처리 흐름

```
1. Workflow 시작
   └── GitHub: workflow_job.queued 이벤트 발생 (1회만!)
              │
              ▼
2. Webhook 수신
   └── FastAPI: 이벤트 검증 → Redis 대기열에 Job 저장
              │
              ▼
3. 대기열 처리 (5초마다 실행)
   └── Celery Beat: process_pending_queues 태스크
       │
       ├── K8s Pod 상태 조회 → Redis 카운터 동기화
       │   (Pod 종료 시 카운터 자동 감소)
       │
       └── 각 Org 대기열 확인
           │
           ├── org_running < org_limit?
           │       │
           │      Yes → Job 추출 → Runner 생성
           │
           └── total_running < max_total?
                   │
                  Yes → 다음 Org 처리
              │
              ▼
4. Runner 생성
   └── Celery Worker:
       - GitHub API: JIT token 발급
       - K8s: Pod 생성 (Ephemeral Runner)
       - Redis: 카운터 증가
              │
              ▼
5. Workflow 실행
   └── Runner Pod: GitHub Actions 작업 수행
              │
              ▼
6. Pod 자동 종료 (Ephemeral Runner)
   └── K8s: Pod 종료 (Succeeded/Failed)
              │
              ▼
7. 상태 동기화 (다음 대기열 처리 시)
   └── process_pending_queues:
       - K8s Pod 상태 조회
       - Redis 카운터 갱신 (종료된 Pod 반영)
       - 대기 Job 있으면 → Runner 생성
```

**주요 특징:**
- `completed` 이벤트 처리 없음 (Ephemeral Runner가 자동 종료)
- Pod 종료 감지는 주기적 K8s 상태 조회로 수행
- 5초마다 대기열 처리 → 빠른 응답성

---

## 주요 기능

### Organization별 동시 실행 제한

| 설정 | 기본값 | 설명 |
|------|--------|------|
| `MAX_RUNNERS_PER_ORG` | 10 | Organization당 최대 동시 Runner 수 (기본값) |
| `MAX_TOTAL_RUNNERS` | 200 | 전체 최대 동시 Runner 수 |

#### 커스텀 Organization 제한

특정 Organization에 대해 기본값과 다른 제한을 설정할 수 있습니다.

**방법 1: 설정 파일 (초기 로드용)**

`config/org-limits.yaml` 파일에 정의:

```yaml
org_limits:
  platform-team: 25    # 25개로 증가
  small-project: 5     # 5개로 감소
  special-org: 50      # 50개로 증가
```

**방법 2: Admin API (동적 변경)**

```bash
# 특정 Organization 제한 설정
curl -X PUT "https://jit-runner.example.com/admin/org-limits/platform-team" \
  -H "X-Admin-Key: YOUR_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"limit": 25}'

# 제한 조회
curl "https://jit-runner.example.com/admin/org-limits/platform-team" \
  -H "X-Admin-Key: YOUR_ADMIN_API_KEY"

# 모든 커스텀 제한 조회
curl "https://jit-runner.example.com/admin/org-limits" \
  -H "X-Admin-Key: YOUR_ADMIN_API_KEY"

# 커스텀 제한 삭제 (기본값 사용)
curl -X DELETE "https://jit-runner.example.com/admin/org-limits/platform-team" \
  -H "X-Admin-Key: YOUR_ADMIN_API_KEY"
```

### 지원 이벤트

| Webhook Event | Action | 처리 내용 |
|---------------|--------|----------|
| `workflow_job` | `queued` | Runner 생성 요청 |
| `workflow_job` | `in_progress` | 상태 업데이트 |
| `workflow_job` | `completed` | Runner 정리 |

### Runner 특성

- **Ephemeral**: 1회 실행 후 자동 삭제
- **DinD**: Docker-in-Docker privileged 모드 지원
- **라벨**: `code-linux` (모든 Organization 공통)

---

## 사전 요구사항

### 인프라

| 구성요소 | 요구사항 |
|---------|---------|
| Kubernetes | 1.24+ |
| Node | 20개 (Runner용) |
| Redis | 6.0+ |
| GitHub Enterprise Server | 3.9+ (권장: 3.14.17) |

### 도구

```bash
# 설치 확인
kubectl version --client    # 1.24+
helm version               # 3.8+
docker version             # 20.10+
```

### GitHub PAT 권한

| Scope | 설명 |
|-------|------|
| `admin:org` | Organization runner 등록/삭제 |
| `repo` | Private repository workflow 접근 |

### 네트워크

- GitHub Enterprise Server → Kubernetes Ingress (Webhook)
- Kubernetes → GitHub Enterprise Server (API 호출)

---

## 설치 가이드

### 1. 네임스페이스 생성

```bash
kubectl create namespace jit-runner-manager
kubectl create namespace jit-runners
```

### 2. Secret 생성

```bash
# GitHub PAT
kubectl create secret generic github-credentials \
  --namespace jit-runner-manager \
  --from-literal=pat='YOUR_GITHUB_PAT'

# Webhook Secret (GitHub에서 설정한 값과 동일해야 함)
kubectl create secret generic webhook-secret \
  --namespace jit-runner-manager \
  --from-literal=secret='YOUR_WEBHOOK_SECRET'

# Admin API Key (선택사항, 권장)
kubectl create secret generic admin-credentials \
  --namespace jit-runner-manager \
  --from-literal=api-key='YOUR_ADMIN_API_KEY'
```

> **참고**: Admin API Key를 설정하지 않으면 Admin API 인증이 비활성화됩니다.

### 3. Helm Chart 설치

```bash
# values.yaml 수정 후 설치
helm install jit-runner-manager ./helm/jit-runner-manager \
  --namespace jit-runner-manager \
  -f ./helm/jit-runner-manager/values.yaml
```

### 4. GitHub Enterprise Webhook 설정

Enterprise 설정에서 Webhook을 추가합니다:

| 항목 | 값 |
|------|-----|
| Payload URL | `https://your-ingress-url/webhook` |
| Content type | `application/json` |
| Secret | `YOUR_WEBHOOK_SECRET` |
| Events | `Workflow jobs` |

자세한 내용은 [Enterprise Webhook 설정 가이드](docs/enterprise-webhook-setup.md)를 참조하세요.

### 5. 설치 확인

```bash
# Pod 상태 확인
kubectl get pods -n jit-runner-manager

# 로그 확인
kubectl logs -n jit-runner-manager -l app=jit-runner-manager -f
```

---

## 설정

### 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `GHES_URL` | - | GitHub Enterprise Server URL |
| `GITHUB_PAT` | - | Personal Access Token |
| `WEBHOOK_SECRET` | - | Webhook 검증용 Secret |
| `REDIS_URL` | `redis://redis:6379/0` | Redis 연결 URL |
| `RUNNER_NAMESPACE` | `jit-runners` | Runner Pod가 생성될 네임스페이스 |
| `RUNNER_IMAGE` | `ghcr.io/actions/actions-runner:latest` | Runner 이미지 |
| `MAX_RUNNERS_PER_ORG` | `10` | Org별 최대 Runner 수 |
| `MAX_TOTAL_RUNNERS` | `200` | 전체 최대 Runner 수 |
| `RUNNER_LABELS` | `code-linux` | Runner 라벨 |

### Helm Values

```yaml
# helm/jit-runner-manager/values.yaml

config:
  ghesUrl: "https://github.example.com"
  maxRunnersPerOrg: 10
  maxTotalRunners: 200
  runnerLabels: "code-linux"
  runnerNamespace: "jit-runners"

runner:
  image: "ghcr.io/actions/actions-runner:latest"
  resources:
    limits:
      cpu: "2"
      memory: "4Gi"
    requests:
      cpu: "500m"
      memory: "1Gi"
  dind:
    enabled: true
    image: "docker:dind"
    resources:
      limits:
        cpu: "2"
        memory: "4Gi"

redis:
  enabled: true  # 내장 Redis 사용
  # external:
  #   url: "redis://external-redis:6379/0"

ingress:
  enabled: true
  className: "nginx"
  hosts:
    - host: jit-runner.example.com
      paths:
        - path: /
          pathType: Prefix
```

---

## 운영 가이드

### Runner 상태 확인

```bash
# 현재 실행 중인 Runner Pod 목록
kubectl get pods -n jit-runners -o wide

# 특정 Organization의 Runner 확인
kubectl get pods -n jit-runners -l org=your-org-name

# Runner 상세 정보
kubectl describe pod <pod-name> -n jit-runners
```

### Redis 상태 확인

```bash
# Redis CLI 접속
kubectl exec -it -n jit-runner-manager deploy/redis -- redis-cli

# Organization별 실행 중인 Runner 수
GET org:your-org-name:running

# 전체 실행 중인 Runner 수
GET global:total_running

# 모든 Organization 상태 조회
KEYS org:*:running
```

### 수동 Runner 정리

비정상 종료된 Runner를 수동으로 정리:

```bash
# 특정 Runner Pod 삭제
kubectl delete pod <pod-name> -n jit-runners

# 오래된 Runner 일괄 삭제 (1시간 이상)
kubectl delete pods -n jit-runners --field-selector=status.phase=Succeeded

# Redis 카운터 리셋 (주의: 실제 상태와 불일치 가능)
kubectl exec -it -n jit-runner-manager deploy/redis -- redis-cli SET org:your-org-name:running 0
```

### 스케일링

Worker 수 조정:

```bash
# Celery Worker 스케일 조정
kubectl scale deployment jit-runner-manager-worker \
  --replicas=5 \
  -n jit-runner-manager
```

---

## 모니터링

### 로그 확인

```bash
# Webhook Receiver 로그
kubectl logs -n jit-runner-manager -l component=webhook -f

# Celery Worker 로그
kubectl logs -n jit-runner-manager -l component=worker -f

# 특정 Runner 로그
kubectl logs -n jit-runners <pod-name> -c runner
kubectl logs -n jit-runners <pod-name> -c dind
```

### 메트릭

API 엔드포인트에서 메트릭 조회:

```bash
# 전체 상태
curl http://jit-runner.example.com/health

# 상세 메트릭
curl http://jit-runner.example.com/metrics
```

응답 예시:
```json
{
  "status": "healthy",
  "total_running": 45,
  "total_pending": 12,
  "organizations": {
    "org-alpha": {"running": 8, "pending": 2},
    "org-beta": {"running": 10, "pending": 5}
  }
}
```

### Prometheus 메트릭 (선택사항)

```yaml
# ServiceMonitor 설정
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: jit-runner-manager
spec:
  selector:
    matchLabels:
      app: jit-runner-manager
  endpoints:
    - port: http
      path: /metrics
```

---

## 트러블슈팅

### 문제 1: Webhook이 수신되지 않음

**증상**: Workflow가 시작되어도 Runner가 생성되지 않음

**확인**:
```bash
# Webhook Receiver 로그 확인
kubectl logs -n jit-runner-manager -l component=webhook | tail -100

# Ingress 상태 확인
kubectl get ingress -n jit-runner-manager
```

**해결**:
1. GitHub Enterprise → Settings → Hooks에서 Webhook 전송 이력 확인
2. Ingress URL이 올바른지 확인
3. Webhook Secret이 일치하는지 확인

### 문제 2: Runner Pod가 생성되지 않음

**증상**: Webhook은 수신되지만 Pod가 생성되지 않음

**확인**:
```bash
# Celery Worker 로그
kubectl logs -n jit-runner-manager -l component=worker | grep -i error

# Redis 상태
kubectl exec -it -n jit-runner-manager deploy/redis -- redis-cli GET global:total_running
```

**해결**:
1. Organization 제한(10개)에 도달했는지 확인
2. 전체 제한(200개)에 도달했는지 확인
3. GitHub PAT 권한 확인

### 문제 3: Runner가 GitHub에 등록되지 않음

**증상**: Pod는 생성되지만 GitHub에서 Runner가 보이지 않음

**확인**:
```bash
# Runner Pod 로그
kubectl logs -n jit-runners <pod-name> -c runner
```

**해결**:
1. GitHub PAT 권한 확인 (`admin:org`)
2. GHES URL이 올바른지 확인
3. 네트워크 연결 확인 (Pod → GHES)

### 문제 4: Docker 빌드 실패

**증상**: DinD 관련 오류 발생

**확인**:
```bash
# DinD 컨테이너 로그
kubectl logs -n jit-runners <pod-name> -c dind
```

**해결**:
1. privileged 모드가 활성화되어 있는지 확인
2. PodSecurityPolicy/PodSecurityStandard 확인
3. 노드에서 privileged 컨테이너 허용 여부 확인

### 문제 5: Redis 연결 실패

**증상**: "Redis connection error" 로그 발생

**확인**:
```bash
# Redis Pod 상태
kubectl get pods -n jit-runner-manager -l app=redis

# Redis 연결 테스트
kubectl exec -it -n jit-runner-manager deploy/jit-runner-manager -- \
  python -c "import redis; r = redis.from_url('redis://redis:6379/0'); print(r.ping())"
```

**해결**:
1. Redis Pod가 정상 실행 중인지 확인
2. Service 이름이 올바른지 확인
3. 네트워크 정책 확인

---

## API 레퍼런스

### Health Check

```
GET /health
```

응답:
```json
{
  "status": "healthy",
  "redis": "connected",
  "kubernetes": "connected"
}
```

### Metrics

```
GET /metrics
```

응답:
```json
{
  "total_running": 45,
  "total_pending": 12,
  "max_total": 200,
  "max_per_org": 10,
  "organizations": {}
}
```

### Organization 상태 조회

```
GET /orgs/{org_name}/status
```

응답:
```json
{
  "organization": "org-alpha",
  "running": 8,
  "pending": 2,
  "max": 25,
  "default_max": 10,
  "is_custom_limit": true,
  "available": 17
}
```

### Webhook Endpoint

```
POST /webhook
Headers:
  X-GitHub-Event: workflow_job
  X-Hub-Signature-256: sha256=...
```

### Admin API (Organization 제한 관리)

> **인증**: 모든 Admin API는 `X-Admin-Key` 헤더가 필요합니다.

#### 모든 커스텀 제한 조회

```
GET /admin/org-limits
Headers:
  X-Admin-Key: YOUR_ADMIN_API_KEY
```

응답:
```json
{
  "default_limit": 10,
  "custom_limits": {
    "platform-team": 25,
    "small-project": 5
  },
  "total_custom_orgs": 2
}
```

#### 특정 Organization 제한 조회

```
GET /admin/org-limits/{org_name}
Headers:
  X-Admin-Key: YOUR_ADMIN_API_KEY
```

응답:
```json
{
  "organization": "platform-team",
  "limit": 25,
  "is_custom": true,
  "current_running": 12,
  "available": 13
}
```

#### Organization 제한 설정

```
PUT /admin/org-limits/{org_name}
Headers:
  X-Admin-Key: YOUR_ADMIN_API_KEY
  Content-Type: application/json
Body:
  {"limit": 25}
```

응답:
```json
{
  "organization": "platform-team",
  "limit": 25,
  "previous_limit": 10,
  "is_custom": true,
  "message": "커스텀 제한이 설정되었습니다: 25"
}
```

#### 벌크 제한 설정

```
PUT /admin/org-limits
Headers:
  X-Admin-Key: YOUR_ADMIN_API_KEY
  Content-Type: application/json
Body:
  {"limits": {"org-a": 25, "org-b": 5, "org-c": 15}}
```

응답:
```json
{
  "updated": 3,
  "limits": {"org-a": 25, "org-b": 5, "org-c": 15},
  "message": "3개 Organization의 제한이 설정되었습니다."
}
```

#### 커스텀 제한 삭제

```
DELETE /admin/org-limits/{org_name}
Headers:
  X-Admin-Key: YOUR_ADMIN_API_KEY
```

응답:
```json
{
  "organization": "platform-team",
  "limit": 10,
  "previous_limit": 25,
  "is_custom": false,
  "message": "커스텀 제한이 삭제되었습니다. 기본값(10) 사용"
}
```

#### 설정 파일 리로드

```
POST /admin/org-limits/reload?force=false
Headers:
  X-Admin-Key: YOUR_ADMIN_API_KEY
```

- `force=false`: Redis에 기존 설정이 없는 경우에만 파일에서 로드
- `force=true`: 기존 설정을 무시하고 파일에서 강제 리로드

---

## 버전 정보

| 구성요소 | 버전 |
|---------|------|
| GitHub Enterprise Server | 3.14.17 |
| Python | 3.11+ |
| FastAPI | 0.104+ |
| Celery | 5.3+ |
| Redis | 6.0+ |
| Kubernetes Python Client | 28.1+ |

---

## 라이선스

내부 사용 전용

---

## 참고 자료

### 내부 문서

- [Runner 생성 로직 상세 설명](docs/runner-creation-logic.md) - 제한 확인, 대기열 처리, 시나리오 예시
- [Enterprise Webhook 설정 가이드](docs/enterprise-webhook-setup.md) - GitHub Enterprise Webhook 구성

### 외부 문서

- [GitHub Actions Self-Hosted Runner](https://docs.github.com/en/actions/hosting-your-own-runners)
- [GitHub REST API - Self-hosted runners](https://docs.github.com/en/rest/actions/self-hosted-runners)
- [GitHub Webhooks - workflow_job](https://docs.github.com/en/webhooks/webhook-events-and-payloads#workflow_job)

