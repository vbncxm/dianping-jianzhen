# -*- coding: utf-8 -*-
"""SQLite 持久化：评论、风险判定、酒店评分、运行批次。

四张表：
    runs          每次分析批次（参数 + 统计），便于对比不同阈值下的结果
    reviews       评论原文 + 风险分/等级/清洗权重/证据
    hotel_scores  酒店净化前后评分与区内排名
    evidence_stat 证据标签命中统计（做报告用）
"""
import json
import os
import sqlite3
import datetime as dt
import zlib

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
DB_PATH = os.path.join(DATA_DIR, "cleaner.db")


def _pack(obj):
    """JSON → zlib 压缩 BLOB（特征列很大，压缩后体积降到约 1/6）。"""
    return zlib.compress(json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"), 6)


def unpack(blob):
    if blob is None:
        return None
    if isinstance(blob, memoryview):
        blob = bytes(blob)
    try:
        return json.loads(zlib.decompress(blob).decode("utf-8"))
    except Exception:
        try:
            return json.loads(blob)
        except Exception:
            return None

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT, finished_at TEXT,
    params       TEXT, stats TEXT,
    is_current   INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reviews (
    run_id       INTEGER,
    评论ID       TEXT,
    酒店ID       TEXT,
    酒店名称     TEXT,
    所属区       TEXT,
    昵称         TEXT,
    评论日期     TEXT,
    入住日期     TEXT,
    总分         REAL,
    位置分       REAL, 设施分 REAL, 服务分 REAL, 客房分 REAL,
    图片数       INTEGER, 有用数 INTEGER,
    推荐         INTEGER,
    IP归属       TEXT,
    来源         TEXT, 出行类型 TEXT, 房型 TEXT, 商家回复 TEXT,
    评论内容     TEXT,
    风险分       REAL, 等级 TEXT, 清洗权重 REAL,
    维度分       TEXT, 证据 TEXT, 特征 TEXT,
    PRIMARY KEY (run_id, 评论ID)
);
CREATE TABLE IF NOT EXISTS hotel_scores (
    run_id       INTEGER,
    酒店ID       TEXT,
    酒店名称     TEXT,
    所属区       TEXT,
    价格         REAL,
    评论质量     REAL, 情感得分 REAL, 设施得分 REAL,
    时间衰减因子 REAL, 价格弹性系数 REAL,
    性价比指数   REAL,
    排名         INTEGER, 区内归一 REAL,
    净化率       REAL, 剔除率 REAL,
    高风险数     INTEGER, 观察数 INTEGER,
    保留评论数   INTEGER, 评论总数 INTEGER,
    基线性价比   REAL, 基线质量 REAL,
    详情         TEXT,
    PRIMARY KEY (run_id, 酒店ID)
);
CREATE TABLE IF NOT EXISTS evidence_stat (
    run_id   INTEGER,
    标签     TEXT,
    维度     TEXT,
    条数     INTEGER,
    PRIMARY KEY (run_id, 标签)
);
CREATE INDEX IF NOT EXISTS idx_rev_hotel ON reviews(run_id, 酒店ID);
CREATE INDEX IF NOT EXISTS idx_rev_level ON reviews(run_id, 等级);
"""


def connect(path: str = None) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path or DB_PATH), exist_ok=True)
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def new_run(conn, params: dict) -> int:
    cur = conn.execute(
        "INSERT INTO runs (started_at, params, is_current) VALUES (?,?,0)",
        (dt.datetime.now().isoformat(timespec="seconds"),
         json.dumps(params, ensure_ascii=False)))
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id: int, stats: dict):
    conn.execute("UPDATE runs SET finished_at=?, stats=?, is_current=0",
                 (dt.datetime.now().isoformat(timespec="seconds"),
                  json.dumps(stats, ensure_ascii=False)))
    conn.execute("UPDATE runs SET is_current=0")
    conn.execute("UPDATE runs SET is_current=1 WHERE id=?", (run_id,))
    conn.commit()


def save_reviews(conn, run_id: int, reviews: list):
    rows = []
    for r in reviews:
        d = r["detection"]
        f = r.get("feats", {})
        rows.append((
            run_id, r["评论ID"], r["酒店ID"], r.get("酒店名称"), r.get("所属区"),
            r.get("昵称"), r.get("评论日期"), r.get("入住日期"),
            r.get("总分"), r.get("位置分"), r.get("设施分"), r.get("服务分"),
            r.get("客房分"), r.get("图片数"), r.get("有用数"),
            1 if r.get("推荐") is True else 0,
            r.get("IP归属"), r.get("来源"), r.get("出行类型"), r.get("房型"),
            r.get("商家回复"), r.get("评论内容"),
            d["风险分"], d["等级"], r.get("清洗权重", 1.0),
            _pack(d.get("维度分")), _pack(d.get("证据")), _pack(f),
        ))
    conn.executemany(
        "INSERT OR REPLACE INTO reviews VALUES (" + ",".join("?" * 28) + ")", rows)
    conn.commit()


def save_hotel_scores(conn, run_id: int, hotels: list):
    rows = []
    for h in hotels:
        rows.append((
            run_id, h["酒店ID"], h.get("酒店名称"), h.get("区") or h.get("所属区"),
            h.get("价格"),
            h.get("评论质量"), h.get("情感得分"), h.get("设施得分"),
            h.get("时间衰减因子"), h.get("价格弹性系数"), h.get("性价比指数"),
            h.get("排名"), h.get("区内归一"),
            h.get("净化率"), h.get("剔除率"), h.get("高风险数"), h.get("观察数"),
            h.get("保留评论数"), h.get("评论总数"),
            (h.get("基线") or {}).get("性价比指数"), (h.get("基线") or {}).get("评论质量"),
            json.dumps(h, ensure_ascii=False, default=str),
        ))
    conn.executemany(
        "INSERT OR REPLACE INTO hotel_scores VALUES (" + ",".join("?" * 22) + ")", rows)
    conn.commit()


def save_evidence(conn, run_id: int, counter: dict):
    rows = [(run_id, k[0], k[1], v) for k, v in counter.items()]
    conn.executemany("INSERT OR REPLACE INTO evidence_stat VALUES (?,?,?,?)", rows)
    conn.commit()


def current_run(conn):
    row = conn.execute("SELECT * FROM runs WHERE is_current=1 ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def query_hotels(conn, run_id: int, district: str = None):
    sql = "SELECT * FROM hotel_scores WHERE run_id=?"
    args = [run_id]
    if district:
        sql += " AND 所属区=?"
        args.append(district)
    sql += " ORDER BY 所属区, 排名"
    return [dict(r) for r in conn.execute(sql, args)]


def query_reviews(conn, run_id: int, hotel_id: str = None, level: str = None,
                  limit: int = 500, offset: int = 0, order: str = "risk"):
    sql = "SELECT * FROM reviews WHERE run_id=?"
    args = [run_id]
    if hotel_id:
        sql += " AND 酒店ID=?"
        args.append(hotel_id)
    if level:
        sql += " AND 等级=?"
        args.append(level)
    sql += " ORDER BY 风险分 DESC" if order == "risk" else " ORDER BY 评论日期 DESC"
    sql += " LIMIT ? OFFSET ?"
    args += [limit, offset]
    out = []
    for r in conn.execute(sql, args):
        d = dict(r)
        d["维度分"] = unpack(d.pop("维度分", None))
        d["证据"] = unpack(d.pop("证据", None))
        d["特征"] = unpack(d.pop("特征", None))
        out.append(d)
    return out


def count_reviews(conn, run_id: int, hotel_id: str = None):
    sql = "SELECT 等级, COUNT(*) c FROM reviews WHERE run_id=?"
    args = [run_id]
    if hotel_id:
        sql += " AND 酒店ID=?"
        args.append(hotel_id)
    sql += " GROUP BY 等级"
    return {r["等级"]: r["c"] for r in conn.execute(sql, args)}
