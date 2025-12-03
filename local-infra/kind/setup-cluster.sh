#!/bin/bash
# Kind Cluster 설정 스크립트
# Integration 테스트를 위한 로컬 Kubernetes 클러스터를 생성합니다.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-jit-runner-test}"

echo "=========================================="
echo "Kind Cluster 설정"
echo "=========================================="

# Kind 설치 확인
if ! command -v kind &> /dev/null; then
    echo "Error: kind가 설치되어 있지 않습니다."
    echo "설치 방법: https://kind.sigs.k8s.io/docs/user/quick-start/#installation"
    exit 1
fi

# kubectl 설치 확인
if ! command -v kubectl &> /dev/null; then
    echo "Error: kubectl이 설치되어 있지 않습니다."
    echo "설치 방법: https://kubernetes.io/docs/tasks/tools/install-kubectl/"
    exit 1
fi

# 기존 클러스터 삭제 (존재하는 경우)
if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    echo "기존 클러스터 삭제 중: ${CLUSTER_NAME}"
    kind delete cluster --name "${CLUSTER_NAME}"
fi

# 클러스터 생성
echo "Kind 클러스터 생성 중: ${CLUSTER_NAME}"
kind create cluster \
    --config "${SCRIPT_DIR}/cluster-config.yaml" \
    --name "${CLUSTER_NAME}" \
    --wait 120s

# Kubeconfig 설정
echo "Kubeconfig 설정 중..."
kubectl cluster-info --context "kind-${CLUSTER_NAME}"

# 네임스페이스 생성
echo "jit-runners 네임스페이스 생성 중..."
kubectl apply -f "${PROJECT_ROOT}/k8s/namespace.yaml" --context "kind-${CLUSTER_NAME}" || \
kubectl create namespace jit-runners --context "kind-${CLUSTER_NAME}" || true

# RBAC 설정
echo "RBAC 설정 적용 중..."
kubectl apply -f "${PROJECT_ROOT}/k8s/rbac.yaml" --context "kind-${CLUSTER_NAME}" || true

# 클러스터 상태 확인
echo ""
echo "=========================================="
echo "클러스터 설정 완료!"
echo "=========================================="
echo "클러스터 이름: ${CLUSTER_NAME}"
echo "컨텍스트: kind-${CLUSTER_NAME}"
echo ""
echo "노드 상태:"
kubectl get nodes --context "kind-${CLUSTER_NAME}"
echo ""
echo "네임스페이스:"
kubectl get namespaces --context "kind-${CLUSTER_NAME}"
