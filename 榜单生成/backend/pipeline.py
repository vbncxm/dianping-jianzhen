# -*- coding: utf-8 -*-
"""端到端流水线：加载 → 特征 → 检测 → 清洗 → 评分 → 排名 → 落库 → 导出 JSON。"""
import datetime as dt
import json
import os
from collections import Counter, defaultdict
from typing import Dict

from . import detector, features, loader, scorer, store
from .config import Config, DEFAULT

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "backend", "data")
OUT_JSON = os.path.join(DATA_DIR, "refined_scores.json")
REVIEWS_SAMPLE = os.path.join(DATA_DIR, "flagged_reviews.json")

DISTRICTS = ["五华区", "盘龙区", "官渡区", "西山区", "呈贡区"]


def _parse(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(str(s))
    except Exception:
        return None


def run(cfg: Config = None, persist: bool = True, verbose: bool = True) -> dict:
    cfg = cfg or DEFAULT
    hotels, reviews, summary = loader.load_all()

    # ── 时间衰减基准日 ────────────────────────────────────────────
    dates = [_parse(r.get("评论日期")) for r in reviews]
    dates = [d for d in dates if d]
    as_of = _parse(cfg.as_of) if cfg.as_of else (max(dates) if dates else dt.datetime.now())
    for r in reviews:
        d = _parse(r.get("评论日期"))
        r["_age_days"] = (as_of - d).days if d else None

    # ── 特征 + 检测 ───────────────────────────────────────────────
    features.extract(reviews, cfg, as_of)
    detector.detect_all(reviews, cfg)

    # ── 全站先验分（净化后加权均分），用于贝叶斯收缩 ──────────────
    num = den = 0.0
    for r in reviews:
        w = r.get("清洗权重", 1.0)
        if w > 0 and r.get("总分") is not None:
            num += r["总分"] * w
            den += w
    prior_score = (num / den) if den else 4.5

    # ── 按酒店聚合 ────────────────────────────────────────────────
    by_hotel = defaultdict(list)
    for r in reviews:
        by_hotel[r["酒店ID"]].append(r)

    # 区内价格池
    dist_prices = defaultdict(list)
    for hid, h in hotels.items():
        d = h.get("区") or h.get("所属区")
        p = h.get("价格")
        if d and p:
            dist_prices[d].append(float(p))

    scored = []
    for hid, rows in by_hotel.items():
        h = hotels.get(hid, {})
        dist = h.get("区") or h.get("所属区") or rows[0].get("所属区")
        price = h.get("价格") or (float(h["价格"]) if str(h.get("价格", "")).replace(".", "").isdigit() else None)
        price = float(price) if price else None
        res = scorer.score_hotel(rows, price, dist_prices.get(dist, []), cfg, prior_score)
        before = scorer.score_before(rows, price, cfg)
        base = dict(h)
        base.update(res)
        base["酒店ID"] = hid
        base["区"] = dist
        base["酒店名称"] = h.get("酒店名称") or rows[0].get("酒店名称")
        base["价格"] = price
        base["基线"] = before
        base["评论数"] = len(rows)
        base["评论日期范围"] = [
            min([r["评论日期"] for r in rows if r.get("评论日期")] or [""]),
            max([r["评论日期"] for r in rows if r.get("评论日期")] or [""]),
        ]
        scored.append(base)

    # ── 区内排名 ──────────────────────────────────────────────────
    ranked = []
    for d in DISTRICTS:
        sub = [s for s in scored if s["区"] == d and s.get("价格")]
        ranked += scorer.rank_district(sub, top_n=99)

    # ── 证据标签统计 ──────────────────────────────────────────────
    ev_counter = Counter()
    level_counter = Counter()
    for r in reviews:
        level_counter[r["detection"]["等级"]] += 1
        for e in r["detection"]["证据"]:
            ev_counter[(e["标签"], e["维度"])] += 1

    stats = {
        "批次时间": dt.datetime.now().isoformat(timespec="seconds"),
        "评论总数": len(reviews),
        "酒店数": len(by_hotel),
        "风险分布": dict(level_counter),
        "高风险占比": round(level_counter.get("高风险", 0) / max(1, len(reviews)), 4),
        "观察占比": round(level_counter.get("观察", 0) / max(1, len(reviews)), 4),
        "整体净化率": round(
            sum(1 - r.get("清洗权重", 1.0) for r in reviews) / max(1, len(reviews)), 4),
        "全站先验分": round(prior_score, 4),
        "时间基准日": as_of.date().isoformat(),
        "证据标签TOP": [{"标签": k[0], "维度": k[1], "条数": v}
                    for k, v in ev_counter.most_common(20)],
    }

    # ── 落库 ──────────────────────────────────────────────────────
    run_id = None
    if persist:
        conn = store.connect()
        run_id = store.new_run(conn, cfg.to_dict())
        store.save_reviews(conn, run_id, reviews)
        store.save_hotel_scores(conn, run_id, ranked)
        store.save_evidence(conn, run_id, ev_counter)
        store.finish_run(conn, run_id, stats)

    # ── 导出 JSON（供前端消费）───────────────────────────────────
    export = {
        "生成时间": stats["批次时间"],
        "配置": cfg.to_dict(),
        "统计": stats,
        "榜单": {},
        "酒店": {},
    }
    for d in DISTRICTS:
        export["榜单"][d] = [{
            "排名": s["排名"], "酒店ID": s["酒店ID"], "酒店名称": s["酒店名称"],
            "价格": s.get("价格"), "性价比指数": s["性价比指数"],
            "区内归一": s["区内归一"], "评论质量": s["评论质量"],
            "情感得分": s["情感得分"], "设施得分": s["设施得分"],
            "时间衰减因子": s["时间衰减因子"], "价格弹性系数": s["价格弹性系数"],
            "净化率": s["净化率"], "剔除率": s["剔除率"],
            "高风险数": s["高风险数"], "观察数": s["观察数"],
            "保留评论数": s["保留评论数"], "评论总数": s["评论总数"],
            "基线性价比": (s.get("基线") or {}).get("性价比指数"),
        } for s in ranked if s["区"] == d]

    for s in ranked:
        hid = s["酒店ID"]
        rows = by_hotel.get(hid, [])
        flagged = sorted(
            [r for r in rows if r["detection"]["等级"] in ("高风险", "观察")],
            key=lambda r: -r["detection"]["风险分"])[:60]
        export["酒店"][hid] = {
            "酒店ID": hid, "酒店名称": s["酒店名称"], "区": s["区"],
            "价格": s.get("价格"), "排名": s["排名"], "区内归一": s["区内归一"],
            "评论质量": s["评论质量"], "情感得分": s["情感得分"],
            "设施得分": s["设施得分"], "时间衰减因子": s["时间衰减因子"],
            "价格弹性系数": s["价格弹性系数"], "性价比指数": s["性价比指数"],
            "净化率": s["净化率"], "剔除率": s["剔除率"],
            "高风险数": s["高风险数"], "观察数": s["观察数"],
            "保留评论数": s["保留评论数"], "评论总数": s["评论总数"],
            "评论日期范围": s["评论日期范围"],
            "基线": s.get("基线"),
            "风险评论": [{
                "评论ID": r["评论ID"], "昵称": r.get("昵称"), "日期": r.get("评论日期"),
                "总分": r.get("总分"), "图片数": r.get("图片数"),
                "风险分": r["detection"]["风险分"], "等级": r["detection"]["等级"],
                "清洗权重": r.get("清洗权重"),
                "维度分": r["detection"]["维度分"],
                "证据": r["detection"]["证据"],
                "摘要": (r.get("评论内容") or "")[:90],
            } for r in flagged],
        }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=1, default=str)

    with open(REVIEWS_SAMPLE, "w", encoding="utf-8") as f:
        json.dump([{
            "评论ID": r["评论ID"], "酒店ID": r["酒店ID"], "酒店名称": r.get("酒店名称"),
            "昵称": r.get("昵称"), "评论日期": r.get("评论日期"), "总分": r.get("总分"),
            "风险分": r["detection"]["风险分"], "等级": r["detection"]["等级"],
            "清洗权重": r.get("清洗权重"), "维度分": r["detection"]["维度分"],
            "证据": r["detection"]["证据"], "内容": r.get("评论内容"),
        } for r in reviews], f, ensure_ascii=False, default=str)

    if verbose:
        _print_report(stats, ranked, export)

    return {"run_id": run_id, "stats": stats, "ranking": export["榜单"],
            "hotels": export["酒店"], "config": cfg.to_dict(), "reviews": reviews}


def _print_report(stats, ranked, export):
    print("=" * 96)
    print("线上虚假评论检测数据分析系统 · 后端清洗流水线")
    print("=" * 96)
    print(f"评论 {stats['评论总数']} 条 · 酒店 {stats['酒店数']} 家 · "
          f"时间基准日 {stats['时间基准日']} · 全站先验分 {stats['全站先验分']}")
    d = stats["风险分布"]
    print(f"风险分布：高风险 {d.get('高风险',0)} · 观察 {d.get('观察',0)} · "
          f"低风险 {d.get('低风险',0)}　→　整体净化率 {stats['整体净化率']:.2%}")
    print()
    print("证据标签命中 TOP10：")
    for e in stats["证据标签TOP"][:10]:
        print(f"   {e['条数']:>5} 条  [{e['维度']}] {e['标签']}")
    print()
    for qu, rows in export["榜单"].items():
        print(f"【{qu}】")
        print(f"   {'名次':>3} {'酒店':<28}{'价格':>7}{'净化率':>8}{'高风险':>7}"
              f"{'性价比':>9}{'基线性价比':>11}{'时间衰减':>9}")
        for s in rows:
            base = s.get("基线性价比") or 0
            print(f"   {s['排名']:>3} {str(s['酒店名称'])[:26]:<28}"
                  f"{s['价格']:>7.0f}{s['净化率']:>8.1%}{s['高风险数']:>7}"
                  f"{s['性价比指数']:>9.2f}{base:>11.2f}{s['时间衰减因子']:>9.3f}")
        print()
