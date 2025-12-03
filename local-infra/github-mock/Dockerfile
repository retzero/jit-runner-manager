# GitHub API Mock Server Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 의존성 설치
RUN pip install --no-cache-dir fastapi uvicorn[standard] pydantic

# 앱 복사
COPY app.py .

# 포트 노출
EXPOSE 8080

# 실행
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
