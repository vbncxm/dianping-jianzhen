# -*- coding: utf-8 -*-
"""数据加载：把抓取到的评论与酒店元信息读成统一结构。

数据源（均在 榜单生成/ 目录下）：
    reviews/all_reviews.jsonl   7534 条评论全量（主数据源）
    reviews/summary.json        每店采集概览
    candidates_top15.json       75 家候选酒店元信息
    candidates_final.json       25 家榜单酒店（含价格、性价比指数）
    prices.json                 {酒店ID: 价格}
"""
import json
import os
from typing import Dict, List

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # …/榜单生成
REVIEWS_DIR = os.path.join(BASE, "reviews")


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _walk_hotels(obj) -> List[dict]:
    """递归收集所有含 酒店ID/酒店名称 的字典。"""
    out = []

    def rec(o):
        if isinstance(o, dict):
            if "酒店ID" in o and "酒店名称" in o:
                out.append(o)
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)
    rec(obj)
    return out


def load_hotels() -> Dict[str, dict]:
    """返回 {酒店ID(str): 酒店元信息}，合并候选池与榜单信息。"""
    hotels: Dict[str, dict] = {}

    for fn in ("candidates_top15.json", "candidates_final.json"):
        data = _read_json(os.path.join(BASE, fn))
        if not data:
            continue
        for h in _walk_hotels(data):
            hid = str(h["酒店ID"])
            cur = hotels.setdefault(hid, {})
            cur.update({k: v for k, v in h.items() if v not in (None, "")})

    prices = _read_json(os.path.join(BASE, "prices.json"), {}) or {}
    for hid, p in prices.items():
        if str(hid) in hotels:
            hotels[str(hid)]["价格"] = float(p)

    return hotels


def load_reviews(path: str = None) -> List[dict]:
    """读取 all_reviews.jsonl，返回归一化后的评论列表。"""
    path = path or os.path.join(REVIEWS_DIR, "all_reviews.jsonl")
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            r["评论ID"] = str(r.get("评论ID") or "")
            r["酒店ID"] = str(r.get("酒店ID") or "")
            r["总分"] = _num(r.get("总分"))
            r["位置分"] = _num(r.get("位置分"))
            r["设施分"] = _num(r.get("设施分"))
            r["服务分"] = _num(r.get("服务分"))
            r["客房分"] = _num(r.get("客房分"))
            r["图片数"] = int(r.get("图片数") or 0)
            r["有用数"] = int(r.get("有用数") or 0)
            r["评论内容"] = (r.get("评论内容") or "").strip()
            rows.append(r)
    return rows


def _num(v):
    try:
        return float(v)
    except Exception:
        return None


def load_summary() -> dict:
    return _read_json(os.path.join(REVIEWS_DIR, "summary.json"), {}) or {}


def load_all():
    """一次性返回 (酒店字典, 评论列表, 采集概览)。"""
    hotels = load_hotels()
    reviews = load_reviews()
    # 用评论里出现的酒店名补全缺失的元信息
    for r in reviews:
        hid = r["酒店ID"]
        h = hotels.setdefault(hid, {"酒店ID": hid})
        h.setdefault("酒店名称", r.get("酒店名称"))
        h.setdefault("区", r.get("所属区"))
        h.setdefault("所属区", r.get("所属区"))
    return hotels, reviews, load_summary()
