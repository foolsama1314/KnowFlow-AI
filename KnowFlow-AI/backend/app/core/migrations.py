"""数据库迁移入口：启动时自动 upgrade 到最新版本。"""

from __future__ import annotations

import logging

from alembic import command
from alembic.config import Config

from app.core.config import BACKEND_DIR, get_settings

logger = logging.getLogger(__name__)


def upgrade_database() -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", get_settings().db_url)
    # 应用内执行迁移时沿用自身日志配置，避免 alembic.ini 覆盖根 logger
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
    logger.info("数据库结构已就绪")
