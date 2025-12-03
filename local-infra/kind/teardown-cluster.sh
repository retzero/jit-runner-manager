#!/bin/bash
# Kind Cluster 삭제 스크립트

set -e

CLUSTER_NAME="${CLUSTER_NAME:-jit-runner-test}"

echo "=========================================="
echo "Kind Cluster 삭제"
echo "=========================================="

# 클러스터 삭제
if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    echo "클러스터 삭제 중: ${CLUSTER_NAME}"
    kind delete cluster --name "${CLUSTER_NAME}"
    echo "클러스터가 삭제되었습니다."
else
    echo "클러스터가 존재하지 않습니다: ${CLUSTER_NAME}"
fi
