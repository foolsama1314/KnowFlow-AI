"""FastAPI 应用入口。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import FRONTEND_DIST, ensure_directories, get_settings
from app.core.database import SessionLocal
from app.core.errors import AppError
from app.core.logging import setup_logging
from app.core.migrations import upgrade_database
from app.ai.vector_store import vector_store
from app.repositories.task_repository import fail_stale_tasks
from app.services.index_service import get_index_status
from app.tasks.runner import runner

logger = logging.getLogger(__name__)

settings = get_settings()
setup_logging(settings.debug)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_directories()
    upgrade_database()

    db = SessionLocal()
    try:
        interrupted = fail_stale_tasks(db)
        if interrupted:
            logger.warning("已把 %d 个中断任务标记为失败", interrupted)
        try:
            get_index_status(db)
        except Exception:  # noqa: BLE001
            logger.warning("向量索引状态初始化失败", exc_info=True)
    finally:
        db.close()

    runner.start()
    if vector_store.healthy():
        logger.info("Qdrant 就绪：%s", vector_store.mode)
    else:
        logger.warning("Qdrant 当前不可用，上传任务可能失败")

    yield

    await runner.shutdown()
    vector_store.close()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="多模态个人知识管理与智能分析平台",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "code": exc.code},
    )


@app.get("/", include_in_schema=False)
def index():
    index_file = FRONTEND_DIST / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return {"app": settings.app_name, "version": settings.app_version, "docs": "/docs"}


from app.api import api_router  # noqa: E402  （避免循环导入）

app.include_router(api_router, prefix=settings.api_prefix)


class SPAStaticFiles(StaticFiles):
    """单页应用静态资源：未命中的前端路由统一回退到 index.html。"""

    async def get_response(self, path: str, scope):  # type: ignore[no-untyped-def]
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and "." not in Path(path).name:
                return await super().get_response("index.html", scope)
            raise


if FRONTEND_DIST.is_dir():
    app.mount("/", SPAStaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
else:
    logger.info("未找到前端构建产物（%s），仅提供 API", FRONTEND_DIST)
