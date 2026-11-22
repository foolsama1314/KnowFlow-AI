"""知枢 AI 桌面版入口：内置启动本地服务，并用原生窗口加载界面。"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def _setup_file_logging() -> Path:
    from app.core.config import DATA_DIR

    log_dir = DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "desktop.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    )
    root.addHandler(handler)

    for noisy in ("httpx", "qdrant_client", "uvicorn.access", "pythonnet"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return log_file


def _pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until_ready(url: str, timeout: float = 90.0) -> bool:
    import httpx

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=2.0)
            if response.status_code == 200:
                health = response.json()
                if health.get("database") is True and health.get("qdrant") is True:
                    return True
        except Exception:  # noqa: BLE001  （服务尚未就绪）
            pass
        time.sleep(0.25)
    return False


def _show_error(message: str) -> None:
    logging.getLogger("desktop").error(message)
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, "知枢 AI", 0x10)
    except Exception:  # noqa: BLE001
        pass


def _icon_path() -> str | None:
    for candidate in (
        _resource_dir() / "app.ico",
        _resource_dir() / "favicon.ico",
        _resource_dir().parent / "frontend" / "public" / "favicon_io" / "favicon.ico",
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def _ensure_writable(directory: Path) -> tuple[bool, str]:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".write_test_{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, ""
    except OSError as exc:
        return False, str(exc)


def main() -> int:
    try:
        log_file = _setup_file_logging()
    except OSError as exc:
        _show_error(
            "无法在程序目录写入数据："
            f"{exc}\n请把「知枢 AI」移动到有写入权限的目录（例如 D:\\知枢AI）后重试。"
        )
        return 1
    log = logging.getLogger("desktop")

    if getattr(sys, "frozen", False):
        os.chdir(Path(sys.executable).resolve().parent)

    from app.core.config import get_settings

    settings = get_settings()
    writable, reason = _ensure_writable(Path(settings.data_dir))
    if not writable:
        _show_error(
            "数据目录不可写："
            f"{settings.data_dir}\n{reason}\n"
            "请将程序放到有写入权限的目录，或以普通用户可写位置运行。"
        )
        return 1

    from app.main import app as fastapi_app

    import uvicorn
    import webview

    port = _pick_port()
    base_url = f"http://127.0.0.1:{port}"
    log.info("本地服务启动：%s，数据目录 %s，日志 %s", base_url, settings.data_dir, log_file)

    server = uvicorn.Server(
        uvicorn.Config(
            fastapi_app,
            host="127.0.0.1",
            port=port,
            log_level="info",
            log_config=None,
            loop="asyncio",
            http="h11",
            access_log=False,
        )
    )
    def _run_server() -> None:
        try:
            server.run()
        except Exception:  # noqa: BLE001
            log.exception("本地服务异常退出")

    server_thread = threading.Thread(
        target=_run_server, name="knowflow-server", daemon=True
    )
    server_thread.start()

    if not _wait_until_ready(f"{base_url}/api/v1/system/health"):
        _show_error(f"本地服务启动失败，请查看日志：\n{log_file}")
        server.should_exit = True
        return 1

    webview.create_window(
        "知枢 AI",
        f"{base_url}/dashboard",
        width=1440,
        height=900,
        min_size=(1200, 760),
        maximized=True,
        background_color="#F5F7FB",
        text_select=True,
        zoomable=True,
    )

    try:
        webview.start(
            icon=_icon_path(),
            private_mode=False,
            storage_path=str(Path(settings.data_dir) / "webview"),
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("桌面窗口启动失败")
        _show_error(
            f"窗口启动失败：{exc}\n请确认系统已安装 Microsoft Edge WebView2 运行时。"
        )
        return 1
    finally:
        server.should_exit = True
        server_thread.join(timeout=15)
        log.info("桌面程序已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
