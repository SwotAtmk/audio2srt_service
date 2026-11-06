"""audio2srt API 服务启动入口。

最简用法：
    python main.py                    # 默认 http://127.0.0.1:8000
    python main.py --port 8123        # 指定端口
    python main.py --host 0.0.0.0     # 允许局域网访问
    python main.py --reload           # 开发热重载

对应环境变量：HOST、PORT、AUDIO2SRT_RELOAD、AUDIO2SRT_LOG_LEVEL。
app/ 内部的分层结构不变，本文件只负责解析启动参数并调用 uvicorn。
"""

from __future__ import annotations

import argparse
import os

import uvicorn


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 audio2srt API 服务")
    parser.add_argument(
        "--host",
        default=os.environ.get("HOST", "127.0.0.1"),
        help="监听地址，默认 127.0.0.1（局域网访问用 0.0.0.0）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8000")),
        help="监听端口，默认 8000",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=_env_flag("AUDIO2SRT_RELOAD"),
        help="开发模式热重载（等价于 AUDIO2SRT_RELOAD=1）",
    )
    args = parser.parse_args()

    log_level = os.environ.get("AUDIO2SRT_LOG_LEVEL", "info").lower()

    print(
        f"audio2srt API 启动: http://{args.host}:{args.port} "
        f"(reload={args.reload}, Swagger 文档: /docs)"
    )
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=log_level,
    )


if __name__ == "__main__":
    main()
