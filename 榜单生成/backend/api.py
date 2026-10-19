# -*- coding: utf-8 -*-
"""FastAPI 接口层：把清洗引擎以 REST 方式暴露，并托管榜单前端。

启动后：
    GET  /                        → 榜单总榜页（output/index.html）
    GET  /docs                    → 自动生成的接口文档
    GET  /api/health              → 健康检查与当前批次信息
    GET  /api/stats               → 全局统计（风险分布、证据 TOP、净化率）
    GET  /api/config              → 当前检测配置
    PATCH/api/config              → 改配置并重跑流水线
    POST /api/analyze             → 用指定参数重跑（不落库）
    GET  /api/rankings            → 各区净化后榜单（可按 ?district= 过滤）
    GET  /api/hotels              → 酒店列表（含净化前后评分）
    GET  /api/hotels/{id}         → 单店详情（维度分、风险评论明细）
    GET  /api/hotels/{id}/reviews → 该店评论（?level=高风险&limit=50）
    GET  /api/reviews             → 全量评论检索（?level=&hotel=&limit=）
    GET  /api/evidence            → 证据标签命中统计
    GET  /api/runs                → 历史批次列表
"""
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import pipeline, store
from backend.config import DEFAULT, Config

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE, "output")
DATA_DIR = os.path.join(BASE, "backend", "data")

app = FastAPI(
    title="线上虚假评论检测数据分析系统 · 后端",
    description="评论清洗与酒店评分后端：五类信号检测虚假评论，净化后重算口碑与性价比。",
    version="1.0.0",
)

_state = {"run_id": None, "cfg": DEFAULT, "stats": {}}


# ─────────────────────────── 工具 ───────────────────────────
def _run_id() -> int:
    if _state["run_id"] is None:
        conn = store.connect()
        cur = store.current_run(conn)
        _state["run_id"] = cur["id"] if cur else None
    return _state["run_id"]


def _rows_to_api(rows: list) -> list:
    """把 SQLite 的 hotel_scores 行整理成接口输出。"""
    out = []
    for r in rows:
        out.append({
            "酒店ID": r["酒店ID"], "酒店名称": r["酒店名称"], "区": r["所属区"],
            "价格": r["价格"], "排名": r["排名"], "区内归一": r["区内归一"],
            "评论质量": r["评论质量"], "情感得分": r["情感得分"],
            "设施得分": r["设施得分"], "时间衰减因子": r["时间衰减因子"],
            "价格弹性系数": r["价格弹性系数"], "性价比指数": r["性价比指数"],
            "净化率": r["净化率"], "剔除率": r["剔除率"],
            "高风险数": r["高风险数"], "观察数": r["观察数"],
            "保留评论数": r["保留评论数"], "评论总数": r["评论总数"],
            "基线性价比": r["基线性价比"], "基线质量": r["基线质量"],
        })
    return out


# ─────────────────────────── 基础 ───────────────────────────
@app.get("/api/health", summary="健康检查")
def health():
    conn = store.connect()
    cur = store.current_run(conn)
    return {
        "状态": "ok",
        "版本": app.version,
        "当前批次": cur["id"] if cur else None,
        "批次时间": cur["finished_at"] if cur else None,
        "评论总数": cur and (cur["stats"] and _safe_load(cur["stats"], {}).get("评论总数")),
        "静态前端": os.path.isdir(STATIC_DIR),
    }


def _safe_load(s, default):
    import json
    try:
        return json.loads(s)
    except Exception:
        return default


@app.get("/api/stats", summary="全局统计")
def stats():
    conn = store.connect()
    cur = store.current_run(conn)
    if not cur:
        raise HTTPException(404, "尚无分析批次，请先运行 python -m backend.run")
    st = _safe_load(cur["stats"], {})
    st["配置"] = _safe_load(cur["params"], {})
    st["批次ID"] = cur["id"]
    return st


@app.get("/api/evidence", summary="证据标签命中统计")
def evidence(limit: int = 50):
    conn = store.connect()
    rid = _run_id()
    rows = conn.execute(
        "SELECT 标签, 维度, 条数 FROM evidence_stat WHERE run_id=? ORDER BY 条数 DESC LIMIT ?",
        (rid, limit)).fetchall()
    total = conn.execute("SELECT COUNT(*) c FROM reviews WHERE run_id=?", (rid,)).fetchone()["c"]
    out = []
    for r in rows:
        out.append({**dict(r), "占全量比": round(r["条数"] / max(1, total), 4)})
    return {"评论总数": total, "标签": out}


# ─────────────────────────── 配置与重跑 ───────────────────────────
class ConfigPatch(BaseModel):
    patch: dict
    persist: bool = True


@app.get("/api/config", summary="读取当前检测配置")
def get_config():
    return _state["cfg"].to_dict()


@app.patch("/api/config", summary="改配置（可选立即重跑）")
def patch_config(body: ConfigPatch):
    cfg: Config = _state["cfg"]
    cfg.update(body.patch or {})
    res = pipeline.run(cfg, persist=body.persist, verbose=False)
    _state["run_id"] = res["run_id"]
    _state["stats"] = res["stats"]
    return {"配置": cfg.to_dict(), "统计": res["stats"]}


@app.post("/api/analyze", summary="用指定参数重跑分析")
def analyze(body: ConfigPatch):
    cfg = Config()
    cfg.update(body.patch or {})
    res = pipeline.run(cfg, persist=body.persist, verbose=False)
    _state["cfg"] = cfg
    _state["run_id"] = res["run_id"]
    _state["stats"] = res["stats"]
    return {"批次ID": res["run_id"], "统计": res["stats"], "榜单": res["ranking"]}


# ─────────────────────────── 榜单与酒店 ───────────────────────────
@app.get("/api/rankings", summary="各区净化后榜单")
def rankings(district: Optional[str] = None, top: int = Query(5, ge=1, le=50)):
    conn = store.connect()
    rid = _run_id()
    rows = store.query_hotels(conn, rid, district)
    api = _rows_to_api(rows)
    if district:
        return {"区": district, "榜单": api[:top]}
    out = {}
    for r in api:
        out.setdefault(r["区"], []).append(r)
    return {k: v[:top] for k, v in out.items()}


@app.get("/api/hotels", summary="酒店列表")
def hotels(district: Optional[str] = None):
    conn = store.connect()
    rows = store.query_hotels(conn, _run_id(), district)
    return _rows_to_api(rows)


@app.get("/api/hotels/{hotel_id}", summary="单店详情")
def hotel_detail(hotel_id: str, flagged: int = Query(60, ge=0, le=500)):
    import json
    conn = store.connect()
    rid = _run_id()
    row = conn.execute(
        "SELECT * FROM hotel_scores WHERE run_id=? AND 酒店ID=?",
        (rid, str(hotel_id))).fetchone()
    if not row:
        raise HTTPException(404, f"未找到酒店 {hotel_id}")
    detail = json.loads(row["详情"])
    detail["风险分布"] = store.count_reviews(conn, rid, str(hotel_id))
    detail["区"] = row["所属区"]

    # 风险评论明细：从库里实时取「高风险 + 观察」并按风险分降序
    rows = store.query_reviews(conn, rid, str(hotel_id), None, 1000, 0, "risk")
    risky = [r for r in rows if r["等级"] in ("高风险", "观察")][:flagged]
    detail["风险评论"] = [{
        "评论ID": r["评论ID"], "昵称": r["昵称"], "日期": r["评论日期"],
        "总分": r["总分"], "图片数": r["图片数"],
        "风险分": r["风险分"], "等级": r["等级"], "清洗权重": r["清洗权重"],
        "维度分": r["维度分"], "证据": r["证据"],
        "摘要": (r["评论内容"] or "")[:90],
    } for r in risky]
    return detail


@app.get("/api/hotels/{hotel_id}/reviews", summary="单店评论（带风险判定）")
def hotel_reviews(hotel_id: str, level: Optional[str] = None,
                  limit: int = Query(50, ge=1, le=1000), offset: int = 0,
                  order: str = "risk"):
    conn = store.connect()
    rows = store.query_reviews(conn, _run_id(), str(hotel_id), level, limit, offset, order)
    return {"酒店ID": hotel_id, "数量": len(rows), "评论": rows}


@app.get("/api/reviews", summary="全量评论检索")
def reviews(level: Optional[str] = None, hotel: Optional[str] = None,
            limit: int = Query(50, ge=1, le=1000), offset: int = 0,
            order: str = "risk", content: Optional[str] = None):
    conn = store.connect()
    rows = store.query_reviews(conn, _run_id(), hotel, level, limit, offset, order)
    if content:
        rows = [r for r in rows if content in (r.get("评论内容") or "")]
    return {"数量": len(rows), "评论": rows}


@app.get("/api/runs", summary="历史批次")
def runs(limit: int = 20):
    conn = store.connect()
    rows = conn.execute(
        "SELECT id, started_at, finished_at, is_current, stats FROM runs "
        "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["stats"] = _safe_load(d["stats"], {})
        out.append(d)
    return out


# ─────────────────────────── 前端静态托管 ───────────────────────────
@app.get("/demo", include_in_schema=False)
def _demo():
    """结项答辩演示站（单页：技术清洗 → 动态量化 → 实地验证）。"""
    p = os.path.join(STATIC_DIR, "showcase.html")
    if os.path.exists(p):
        return FileResponse(p)
    return JSONResponse({"提示": "尚未生成演示站，请先运行 python 20_build_showcase.py"})

if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="site")
else:
    @app.get("/")
    def _no_site():
        return JSONResponse({"提示": "尚未生成前端页面，请先运行 python 03_build_pages.py"},
                            status_code=200)
