# -*- coding: utf-8 -*-
"""命令行入口：跑一遍完整的清洗与评分流水线。

用法（在 榜单生成/ 目录下）：
    python -m backend.run                  # 用默认参数跑一遍
    python -m backend.run --high 60        # 调低高风险阈值
    python -m backend.run --no-persist     # 只算不写库
    python -m backend.run --json           # 额外打印导出 JSON 路径与摘要
"""
import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pipeline
from backend.config import Config


def main():
    ap = argparse.ArgumentParser(description="虚假评论清洗与酒店评分流水线")
    ap.add_argument("--high", type=float, help="高风险阈值（默认 70）")
    ap.add_argument("--watch", type=float, help="观察阈值（默认 40）")
    ap.add_argument("--max-downweight", type=float, help="观察区最大降权（默认 0.7）")
    ap.add_argument("--keep-high", action="store_true", help="高风险评论不剔除，仅降权")
    ap.add_argument("--lambda-decay", type=float, help="时间衰减系数（默认 0.001）")
    ap.add_argument("--theta", type=float, help="价格弹性指数（默认 0.30）")
    ap.add_argument("--bayes-c", type=float, help="贝叶斯收缩强度（默认 30）")
    ap.add_argument("--as-of", type=str, help="时间衰减基准日 YYYY-MM-DD")
    ap.add_argument("--no-persist", action="store_true", help="不写入 SQLite")
    a = ap.parse_args()

    cfg = Config()
    patch = {}
    if a.high is not None:
        patch["high_threshold"] = a.high
    if a.watch is not None:
        patch["watch_threshold"] = a.watch
    if a.max_downweight is not None:
        patch["max_downweight"] = a.max_downweight
    if a.keep_high:
        patch["drop_high"] = False
    if a.lambda_decay is not None:
        patch["lambda_decay"] = a.lambda_decay
    if a.theta is not None:
        patch["theta_elastic"] = a.theta
    if a.bayes_c is not None:
        patch["bayes_c"] = a.bayes_c
    if a.as_of:
        patch["as_of"] = a.as_of
    cfg.update(patch)

    res = pipeline.run(cfg, persist=not a.no_persist)
    print(f"导出：backend/data/refined_scores.json（run_id={res['run_id']}）")


if __name__ == "__main__":
    main()
