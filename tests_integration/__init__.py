"""
Integration Tests for JIT Runner Manager

이 패키지는 실제 서비스(Redis, Kubernetes)와 Mock GitHub API를 사용하는
통합 테스트를 포함합니다.

일반 pytest 실행에서는 제외되며, 별도의 명령으로 실행해야 합니다:
  pytest tests_integration/ --integration

또는 GitHub Actions에서 자동으로 실행됩니다.
"""
