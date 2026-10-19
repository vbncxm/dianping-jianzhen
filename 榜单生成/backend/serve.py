# -*- coding: utf-8 -*-
"""启动后端服务：清洗引擎 + REST 接口 + 榜单前端一体化。

用法（在 榜单生成/ 目录下）：
    python -m backend.serve                 # 默认 http://127.0.0.1:8000
    python -m backend.serve --port 8080
    python -m backend.serve --reload        # 开发模式，改代码自动重载
    python -m backend.serve --analyze       # 启动前先跑一次流水线
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser(description="启动虚假评论清洗后端")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true")
    ap.add_argument("--analyze", action="store_true", help="启动前先跑一次分析流水线")
    a = ap.parse_args()

    if a.analyze:
        from backend import pipeline
        print("[启动] 先运行一次清洗流水线 …")
        pipeline.run(verbose=True)

    import uvicorn
    print(f"[启动] 后端地址 http://{a.host}:{a.port}")
    print(f"[启动] 接口文档 http://{a.host}:{a.port}/docs")
    print(f"[启动] 榜单前端 http://{a.host}:{a.port}/")
    uvicorn.run("backend.api:app", host=a.host, port=a.port, reload=a.reload)


if __name__ == "__main__":
    main()
