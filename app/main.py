"""
FastAPI 메인 애플리케이션

Webhook 수신 및 API 엔드포인트를 제공합니다.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_config
from app.webhook_handler import router as webhook_router
from app.redis_client import get_redis_client, RedisClient

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 라이프사이클 관리"""
    # Startup
    logger.info("JIT Runner Manager 시작 중...")
    config = get_config()
    logger.info(f"GHES URL: {config.github.url}")
    logger.info(f"Max runners per org: {config.runner.max_per_org}")
    logger.info(f"Max total runners: {config.runner.max_total}")
    logger.info(f"Runner labels: {config.runner.labels}")
    
    # Redis 연결 확인
    try:
        redis_client = get_redis_client()
        await redis_client.ping()
        logger.info("Redis 연결 성공")
    except Exception as e:
        logger.error(f"Redis 연결 실패: {e}")
    
    yield
    
    # Shutdown
    logger.info("JIT Runner Manager 종료 중...")


# FastAPI 앱 생성
app = FastAPI(
    title="JIT Runner Manager",
    description="GitHub Enterprise Server용 Just-In-Time Self-Hosted Runner 관리 시스템",
    version="1.0.0",
    lifespan=lifespan
)

# 라우터 등록
app.include_router(webhook_router, prefix="/webhook", tags=["Webhook"])


@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    config = get_config()
    
    # Redis 상태 확인
    redis_status = "disconnected"
    try:
        redis_client = get_redis_client()
        if await redis_client.ping():
            redis_status = "connected"
    except Exception:
        pass
    
    return {
        "status": "healthy" if redis_status == "connected" else "degraded",
        "redis": redis_status,
        "config": {
            "ghes_url": config.github.url,
            "max_per_org": config.runner.max_per_org,
            "max_total": config.runner.max_total
        }
    }


@app.get("/metrics")
async def get_metrics():
    """메트릭 엔드포인트"""
    config = get_config()
    
    try:
        redis_client = get_redis_client()
        total_running = await redis_client.get_total_running()
        org_stats = await redis_client.get_all_org_stats()
        
        return {
            "total_running": total_running,
            "max_total": config.runner.max_total,
            "max_per_org": config.runner.max_per_org,
            "organizations": org_stats
        }
    except Exception as e:
        logger.error(f"메트릭 조회 실패: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/orgs/{org_name}/status")
async def get_org_status(org_name: str):
    """Organization 상태 조회"""
    config = get_config()
    
    try:
        redis_client = get_redis_client()
        running = await redis_client.get_org_running_count(org_name)
        pending = await redis_client.get_org_pending_count(org_name)
        
        return {
            "organization": org_name,
            "running": running,
            "pending": pending,
            "max": config.runner.max_per_org,
            "available": max(0, config.runner.max_per_org - running)
        }
    except Exception as e:
        logger.error(f"Organization 상태 조회 실패: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """전역 예외 핸들러"""
    logger.error(f"처리되지 않은 예외: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

