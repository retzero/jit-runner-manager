# GitHub Enterprise Server Webhook 설정 가이드

JIT Runner Manager가 workflow 요청을 수신하려면 GitHub Enterprise Server에서 Enterprise 레벨 Webhook을 설정해야 합니다.

---

## 목차

1. [사전 요구사항](#사전-요구사항)
2. [Webhook URL 준비](#webhook-url-준비)
3. [Enterprise Webhook 생성](#enterprise-webhook-생성)
4. [Webhook Secret 설정](#webhook-secret-설정)
5. [테스트 및 검증](#테스트-및-검증)
6. [트러블슈팅](#트러블슈팅)

---

## 사전 요구사항

### 필요한 권한

- **Enterprise Owner** 또는 **Enterprise Admin** 권한이 필요합니다.
- Site Admin 권한만으로는 Enterprise Webhook을 설정할 수 없습니다.

### 네트워크 요구사항

GitHub Enterprise Server에서 JIT Runner Manager의 Webhook 엔드포인트로 HTTPS 통신이 가능해야 합니다.

| 항목 | 값 |
|------|-----|
| 프로토콜 | HTTPS (권장) 또는 HTTP |
| 포트 | 443 (HTTPS) 또는 커스텀 포트 |
| 방화벽 | GitHub Enterprise Server → JIT Runner Manager Ingress |

---

## Webhook URL 준비

### 1. Ingress URL 확인

JIT Runner Manager가 배포된 후 Ingress URL을 확인합니다:

```bash
kubectl get ingress -n jit-runner-manager
```

출력 예시:
```
NAME                 CLASS   HOSTS                      ADDRESS        PORTS   AGE
jit-runner-manager   nginx   jit-runner.example.com     10.0.0.100     80      1d
```

### 2. Webhook Endpoint URL

Webhook URL은 다음 형식입니다:

```
https://jit-runner.example.com/webhook
```

> **참고**: `/webhook` 경로를 정확히 지정해야 합니다.

### 3. TLS 인증서 확인

HTTPS를 사용하는 경우, GitHub Enterprise Server가 신뢰할 수 있는 인증서인지 확인합니다:

- 공인 CA에서 발급한 인증서 사용 (권장)
- 자체 서명 인증서 사용 시, GitHub Enterprise Server에 CA 인증서 등록 필요

---

## Enterprise Webhook 생성

### 방법 1: Web UI를 통한 설정

1. **GitHub Enterprise Server 접속**
   - Enterprise 관리자 계정으로 로그인

2. **Enterprise 설정 페이지 이동**
   - 우측 상단 프로필 아이콘 클릭
   - **Your enterprises** 선택
   - 해당 Enterprise 선택

3. **Settings 메뉴 이동**
   - 좌측 사이드바에서 **Settings** 클릭

4. **Hooks 메뉴 선택**
   - 좌측 메뉴에서 **Hooks** 클릭
   - **Add webhook** 버튼 클릭

5. **Webhook 정보 입력**

   | 필드 | 값 | 설명 |
   |------|-----|------|
   | Payload URL | `https://jit-runner.example.com/webhook` | Webhook 수신 URL |
   | Content type | `application/json` | JSON 형식 사용 |
   | Secret | `your-secret-here` | Webhook 서명 검증용 |
   | SSL verification | Enable (권장) | SSL 인증서 검증 |
   | Active | ✓ | Webhook 활성화 |

6. **이벤트 선택**
   - **Let me select individual events** 선택
   - **Workflow jobs** 체크
   - 다른 이벤트는 선택 해제

7. **저장**
   - **Add webhook** 버튼 클릭

### 방법 2: API를 통한 설정

Enterprise Admin PAT를 사용하여 API로 Webhook을 생성할 수 있습니다:

```bash
# 환경 변수 설정
GHES_URL="https://github.example.com"
ENTERPRISE_SLUG="your-enterprise"
ADMIN_PAT="ghp_your_admin_pat"
WEBHOOK_URL="https://jit-runner.example.com/webhook"
WEBHOOK_SECRET="your-webhook-secret"

# Webhook 생성
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer ${ADMIN_PAT}" \
  "${GHES_URL}/api/v3/enterprises/${ENTERPRISE_SLUG}/hooks" \
  -d '{
    "name": "web",
    "active": true,
    "events": ["workflow_job"],
    "config": {
      "url": "'"${WEBHOOK_URL}"'",
      "content_type": "json",
      "secret": "'"${WEBHOOK_SECRET}"'",
      "insecure_ssl": "0"
    }
  }'
```

응답 예시:
```json
{
  "id": 1,
  "name": "web",
  "active": true,
  "events": ["workflow_job"],
  "config": {
    "url": "https://jit-runner.example.com/webhook",
    "content_type": "json",
    "insecure_ssl": "0"
  },
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z"
}
```

---

## Webhook Secret 설정

### Secret 생성

강력한 랜덤 문자열을 생성합니다:

```bash
# OpenSSL을 사용한 랜덤 문자열 생성
openssl rand -hex 32
```

출력 예시:
```
a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6
```

### Kubernetes Secret 생성

```bash
kubectl create secret generic webhook-secret \
  --namespace jit-runner-manager \
  --from-literal=secret='a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6'
```

### GitHub Enterprise Webhook에 동일한 Secret 설정

Web UI 또는 API에서 동일한 Secret 값을 설정합니다.

> **중요**: Kubernetes Secret과 GitHub Enterprise Webhook의 Secret 값이 정확히 일치해야 합니다.

---

## 테스트 및 검증

### 1. Webhook Ping 테스트

GitHub Enterprise Server에서 Webhook을 생성하면 자동으로 ping 이벤트가 전송됩니다.

**JIT Runner Manager 로그 확인:**

```bash
kubectl logs -n jit-runner-manager -l component=webhook -f
```

성공 시 로그:
```
INFO - Webhook 수신: event=ping, delivery=xxx-xxx-xxx
```

### 2. 수동 테스트

GitHub Enterprise Server의 Webhook 설정 페이지에서:

1. 생성한 Webhook 클릭
2. **Recent Deliveries** 탭 선택
3. **Redeliver** 버튼으로 재전송 테스트

### 3. 실제 Workflow 테스트

테스트용 Repository에서 간단한 Workflow를 실행합니다:

```yaml
# .github/workflows/test-runner.yaml
name: Test JIT Runner

on:
  workflow_dispatch:

jobs:
  test:
    runs-on: code-linux
    steps:
      - name: Test
        run: |
          echo "Hello from JIT Runner!"
          docker --version
```

1. **Actions** 탭에서 **Run workflow** 실행
2. JIT Runner Manager 로그에서 이벤트 수신 확인
3. Runner Pod 생성 확인:
   ```bash
   kubectl get pods -n jit-runners -w
   ```

---

## 트러블슈팅

### 문제 1: Webhook이 전송되지 않음

**증상**: Recent Deliveries에 기록이 없음

**확인 사항**:
- Webhook이 **Active** 상태인지 확인
- **Workflow jobs** 이벤트가 선택되어 있는지 확인

### 문제 2: Webhook 전송 실패 (Connection refused)

**증상**: Recent Deliveries에서 `Connection refused` 오류

**해결 방법**:
1. Ingress URL이 올바른지 확인
2. 네트워크 연결 확인 (방화벽, 보안 그룹)
3. JIT Runner Manager Pod가 실행 중인지 확인:
   ```bash
   kubectl get pods -n jit-runner-manager
   ```

### 문제 3: Webhook 전송 실패 (SSL Certificate Error)

**증상**: `SSL certificate problem` 오류

**해결 방법**:
- **옵션 1**: 유효한 SSL 인증서 사용 (권장)
- **옵션 2**: Webhook 설정에서 **Disable SSL verification** 선택 (비권장)

### 문제 4: Webhook 전송 성공하지만 401 Unauthorized

**증상**: Response가 `401 Unauthorized`

**해결 방법**:
1. Webhook Secret이 일치하는지 확인
2. Kubernetes Secret 값 확인:
   ```bash
   kubectl get secret webhook-secret -n jit-runner-manager -o jsonpath='{.data.secret}' | base64 -d
   ```
3. GitHub Enterprise Webhook의 Secret과 비교

### 문제 5: Webhook 전송 성공하지만 Runner가 생성되지 않음

**증상**: Response가 `200 OK`이지만 Runner Pod가 생성되지 않음

**확인 사항**:
1. Celery Worker 로그 확인:
   ```bash
   kubectl logs -n jit-runner-manager -l component=worker
   ```
2. Redis 연결 상태 확인
3. GitHub PAT 권한 확인
4. Runner 라벨이 `code-linux`인지 확인

---

## Webhook 이벤트 상세

### workflow_job 이벤트 구조

```json
{
  "action": "queued",
  "workflow_job": {
    "id": 123456789,
    "run_id": 987654321,
    "name": "build",
    "labels": ["code-linux"],
    "runner_name": null,
    "runner_id": null
  },
  "repository": {
    "id": 12345,
    "full_name": "org-name/repo-name",
    "owner": {
      "login": "org-name",
      "type": "Organization"
    }
  },
  "organization": {
    "login": "org-name",
    "id": 67890
  },
  "sender": {
    "login": "user-name"
  }
}
```

### 지원되는 Action

| Action | 설명 | JIT Runner Manager 동작 |
|--------|------|------------------------|
| `queued` | Workflow job이 대기열에 추가됨 | Runner 생성 요청 |
| `in_progress` | Workflow job 실행 시작 | 상태 업데이트 (로깅) |
| `completed` | Workflow job 완료 | Runner 정리 |

---

## 참고 자료

- [GitHub Enterprise Server - Managing webhooks](https://docs.github.com/en/enterprise-server/admin/configuration/configuring-webhooks)
- [GitHub Webhooks - workflow_job event](https://docs.github.com/en/webhooks/webhook-events-and-payloads#workflow_job)
- [Enterprise webhooks](https://docs.github.com/en/enterprise-server/admin/policies/enforcing-policies-for-your-enterprise/enforcing-policies-for-github-actions-in-your-enterprise)

