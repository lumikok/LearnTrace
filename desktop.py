"""Launch the local journal in its own Windows window."""

from __future__ import annotations

import ctypes
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.request import urlopen

from storage import prepare_shared_database

def webview2_runtime_version() -> str | None:
    """Read the per-machine and per-user WebView2 Evergreen registrations."""
    if sys.platform != "win32":
        return None
    import winreg

    client = r"{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    locations = (
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{client}"),
        (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{client}"),
    )
    for hive, path in locations:
        try:
            with winreg.OpenKey(hive, path) as key:
                version, _ = winreg.QueryValueEx(key, "pv")
                if version and version != "0.0.0.0":
                    return version
        except OSError:
            continue
    return None


def prepare_data() -> Path:
    database = prepare_shared_database()
    folder = database.parent
    os.environ["LEARNING_DB_PATH"] = str(database)
    os.environ["LEARNING_LOG_DIR"] = str(folder / "logs")
    return folder


def start_server():
    import uvicorn
    from app import app

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_config=None))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, name="local-api", daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/"
    for _ in range(100):
        if not thread.is_alive():
            break
        try:
            with urlopen(url, timeout=0.2) as response:
                if response.status == 200:
                    return server, thread, listener, url
        except OSError:
            time.sleep(0.1)
    server.should_exit = True
    thread.join(timeout=2)
    listener.close()
    raise RuntimeError("本地服务未能启动")


def main() -> int:
    server = thread = listener = None
    try:
        folder = prepare_data()
        if "--smoke-test" not in sys.argv and sys.platform == "win32" and not webview2_runtime_version():
            raise RuntimeError("未检测到 Microsoft Edge WebView2 运行时。请从 https://developer.microsoft.com/microsoft-edge/webview2/ 安装后重试。")
        server, thread, listener, url = start_server()
        if "--smoke-test" in sys.argv:
            with urlopen(f"{url}api/overview", timeout=3) as response:
                if response.status != 200:
                    raise RuntimeError("数据接口不可用")
            return 0

        import webview

        window = webview.create_window("拾光 · 学习记录", url, width=1100, height=780, min_size=(760, 540))
        loaded = threading.Event()
        if "--gui-smoke-test" in sys.argv:
            def close_after_load():
                loaded.set()
                window.destroy()

            window.events.loaded += close_after_load
        webview.start(gui="edgechromium", private_mode=False, storage_path=str(folder / "webview"))
        if "--gui-smoke-test" in sys.argv and not loaded.is_set():
            raise RuntimeError("桌面窗口未能加载页面")
        return 0
    except Exception as exc:
        logging.getLogger("learning-recording").exception("desktop.start_failed")
        if not {"--smoke-test", "--gui-smoke-test"}.intersection(sys.argv) and sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(None, f"拾光启动失败：{exc}\n请查看本地日志。", "拾光", 0x10)
        return 1
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=5)
        if listener is not None:
            listener.close()


if __name__ == "__main__":
    raise SystemExit(main())
