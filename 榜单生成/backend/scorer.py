# -*- coding: utf-8 -*-
"""酒店评分：在净化后的评论集合上重算口碑与性价比。

与《项目申请书》公式的对应关系：
    性价比指数 =（评论质量 × 情感得分 × 设施得分）× 时间衰减因子 × 价格弹性系数 ÷ 价格

三处「更真实」的升级（原脚本因缺数据只能用中性值 1.0）：
    ① 时间衰减因子 e^(-λΔt)：现在有真实评论日期，Δt 逐条计算后按清洗权重加权
    ② 价格弹性系数 (P/P̄)^θ：以区内中位价为基准，θ<1 表示价格敏感度递减，
       避免榜单被「绝对最低价」单一维度主导
    ③ 评论质量 / 情感得分 / 设施得分：全部只统计净化后保留、且按清洗权重加权的评论，
       并做贝叶斯收缩，抑制小样本刷分
"""
import math
from typing import Dict, List, Tuple

from .config import Config

SCALE = 1000.0
DIMS = ("总分", "客房分", "设施分", "服务分")
# AHP 权重：总评分 0.40；客房分代理「卫生 + 环境」两项各 0.15 → 0.30；设施 0.15；服务 0.15
AHP_W = {"总分": 0.40, "客房分": 0.30, "设施分": 0.15, "服务分": 0.15}


def _dim_avg(rows: List[dict], key: str, cfg: Config) -> Tuple[float, float]:
    num = den = 0.0
    for r in rows:
        v = r.get(key)
        w = r.get("清洗权重", 1.0)
        if v is None or w <= 0:
            continue
        num += v * w
        den += w
    return (num / den if den else 0.0), den


def score_hotel(reviews: List[dict], price: float, district_prices: List[float],
                cfg: Config, prior_score: float) -> dict:
    """对一家酒店的在榜评论集合打分。"""
    kept = [r for r in reviews if r.get("清洗权重", 1.0) > 0]
    n_total = len(reviews)
    n_kept = len(kept)
    n_high = sum(1 for r in reviews if r["detection"]["等级"] == "高风险")
    n_watch = sum(1 for r in reviews if r["detection"]["等级"] == "观察")
    eff_n = sum(r.get("清洗权重", 1.0) for r in reviews)

    # ── ① 评论质量：AHP 四维加权（净化后）──────────────────────────
    quality_raw = 0.0
    if kept:
        dim_vals = []
        for k, aw in AHP_W.items():
            v, _ = _dim_avg(kept, k, cfg)
            dim_vals.append((v, aw))
        tot_w = sum(w for _, w in dim_vals) or 1.0
        quality_raw = sum(v * w for v, w in dim_vals) / tot_w
    # 贝叶斯收缩：向全站基准分收缩，抑制小样本
    C = cfg.bayes_c
    quality_shrunk = ((eff_n * quality_raw + C * prior_score) / (eff_n + C)
                      if (eff_n + C) > 0 else prior_score)
    quality = max(0.0, min(1.0, quality_shrunk / 5.0))

    # ── ② 情感得分 ────────────────────────────────────────────────
    sn = sd = 0.0
    for r in kept:
        w = r.get("清洗权重", 1.0)
        st = r.get("总分")
        if st is None:
            continue
        p, ng = r.get("feats", {}).get("text", {}).get("_sent", (0, 0))
        polar = 0.5 + 0.5 * (p - ng) / (p + ng + 2.0)
        reco = 1.0 if r.get("推荐") is True else 0.0
        s = (cfg.sent_score_w * (st / 5.0)
             + cfg.sent_text_w * polar
             + cfg.sent_reco_w * reco)
        sn += s * w
        sd += w
    senti = (sn / sd) if sd else 0.5

    # ── ③ 设施得分 ────────────────────────────────────────────────
    fa, _ = _dim_avg(kept, "设施分", cfg)
    facility = max(0.0, min(1.0, fa / 5.0))

    # ── ④ 时间衰减因子（真实评论日期）─────────────────────────────
    dn = dd = 0.0
    for r in reviews:
        if r.get("清洗权重", 1.0) <= 0:
            continue
        dt_days = r.get("_age_days")
        if dt_days is None:
            continue
        w = r.get("清洗权重", 1.0)
        dn += math.exp(-cfg.lambda_decay * max(0, dt_days)) * w
        dd += w
    decay = (dn / dd) if dd else 1.0

    # ── ⑤ 价格弹性系数 ────────────────────────────────────────────
    if price and district_prices:
        srt = sorted(district_prices)
        median_p = srt[len(srt) // 2] or price
        elastic = (price / median_p) ** cfg.theta_elastic
        elastic = max(cfg.elastic_lo, min(cfg.elastic_hi, elastic))
    else:
        elastic = 1.0

    base = quality * senti * facility
    idx = (base * decay * elastic * SCALE / price) if price else 0.0

    return {
        "评论质量": round(quality, 4),
        "评论质量_原始均分": round(quality_raw, 3),
        "情感得分": round(senti, 4),
        "设施得分": round(facility, 4),
        "时间衰减因子": round(decay, 4),
        "价格弹性系数": round(elastic, 4),
        "性价比指数": round(idx, 3),
        "有效评论数": round(eff_n, 1),
        "评论总数": n_total,
        "保留评论数": n_kept,
        "高风险数": n_high,
        "观察数": n_watch,
        "剔除率": round((n_total - n_kept) / n_total, 4) if n_total else 0.0,
        "净化率": round(1 - eff_n / n_total, 4) if n_total else 0.0,
        "_base": round(base, 5),
        "_decay": decay, "_elastic": elastic,
    }


def score_before(reviews: List[dict], price: float, cfg: Config) -> dict:
    """净化前基线：全部评论等权、时间衰减与价格弹性取中性值 1.0。"""
    n = len(reviews)
    if not n:
        return {"评论质量": 0, "情感得分": 0, "设施得分": 0, "性价比指数": 0}
    dim_vals = []
    for k, aw in AHP_W.items():
        vals = [r[k] for r in reviews if r.get(k) is not None]
        dim_vals.append((sum(vals) / len(vals) if vals else 0.0, aw))
    tot_w = sum(w for _, w in dim_vals) or 1.0
    q_raw = sum(v * w for v, w in dim_vals) / tot_w
    q = max(0.0, min(1.0, q_raw / 5.0))
    senti = sum(r["总分"] for r in reviews if r.get("总分") is not None) / n / 5.0
    fa = [r["设施分"] for r in reviews if r.get("设施分") is not None]
    facility = (sum(fa) / len(fa) / 5.0) if fa else 0.0
    base = q * senti * facility
    idx = (base * SCALE / price) if price else 0.0
    return {"评论质量": round(q, 4), "情感得分": round(senti, 4),
            "设施得分": round(facility, 4), "性价比指数": round(idx, 3),
            "_base": round(base, 5)}


def rank_district(rows: List[dict], top_n: int = 99) -> List[dict]:
    """区内按性价比指数降序排名。"""
    rows = sorted(rows, key=lambda x: x["性价比指数"], reverse=True)
    hi = rows[0]["性价比指数"] if rows else 0
    out = []
    for i, r in enumerate(rows, 1):
        r = dict(r)
        r["排名"] = i
        r["区内归一"] = round(r["性价比指数"] / hi * 100, 1) if hi else 0.0
        out.append(r)
    return out[:top_n]
