# -*- coding: utf-8 -*-
"""
第二步：按《项目计划申请书》的动态性价比算法给每家酒店打分

计划原公式：
    性价比指数 = (评论质量 × 情感得分 × 设施得分) × 时间衰减因子 × 价格弹性系数 ÷ 价格

各因子在本数据源下的可得性：
    评论质量        → 可得：总评分 + 卫生/设施/环境/服务四项分项
    情感得分        → 可得：对「一句话点评」做情感极性分析
    设施得分        → 可得：设施评分（AHP 权重）
    时间衰减 e^(-λΔt) → ★不可得：数据源无评论时间戳，暂置中性值 1
    价格弹性系数    → ★不可得：数据源无价格，无法算区域 30 天均价，暂置中性值 1
    价格            → ★不可得：数据源无任何价格字段

因此本脚本先产出「质量维度得分」（= 公式中去掉三个缺失因子后的部分），
并输出各区候选池；价格到位后只需在 PRICE 字典里填值即可得到最终性价比排名。
"""
import json, os, csv, collections, statistics as st

BASE = os.path.dirname(os.path.abspath(__file__))
DISTRICTS = ["五华区", "盘龙区", "官渡区", "西山区", "呈贡区"]

# ---- 评分参数（与申请书口径对齐，可调）----
W_SCORE, W_HYGIENE, W_FACILITY, W_ENV, W_SERVICE = 0.40, 0.15, 0.15, 0.15, 0.15
C_PRIOR = 30          # 贝叶斯收缩常数：评论数低于 30 的酒店向区均值靠拢
LAMBDA = 0.001        # 时间衰减系数（本次无时间戳，未启用）
CAND_PER_DISTRICT = 12   # 每区候选池大小

# ---- 价格（★待补：填入 酒店ID -> 价格 后即可出最终性价比排名）----
PRICE = {}

# ---- 轻量情感词典（对「一句话点评」）----
POS = ["超赞", "超棒", "很好", "干净", "卫生", "舒适", "安静", "热情", "方便", "推荐",
       "满意", "贴心", "不错", "好", "新", "大", "全", "快", "美", "赞", "喜欢", "完善", "合理"]
NEG = ["差", "吵", "脏", "旧", "小", "臭", "慢", "不好", "失望", "一般", "难", "堵",
       "异味", "破", "偏", "贵", "敷衍", "不推荐", "问题"]


def num(x):
    if x is None:
        return None
    s = str(x).strip().replace("条点评", "").replace(",", "").replace("分", "")
    try:
        return float(s)
    except Exception:
        return None


def sentiment(text):
    """返回 0-1 的情感得分，0.5 为中性"""
    if not text:
        return 0.5
    p = sum(1 for w in POS if w in text)
    n = sum(1 for w in NEG if w in text)
    tot = p + n
    if tot == 0:
        return 0.5
    return round(p / tot, 4)


def main():
    hotels = json.load(open(os.path.join(BASE, "hotels_clean.json"), encoding="utf-8"))
    by_district = collections.defaultdict(list)

    for r in hotels:
        sc = num(r.get("评分")); n = num(r.get("评论数量"))
        hy = num(r.get("卫生评分")); fa = num(r.get("设施评分"))
        en = num(r.get("环境评分")); se = num(r.get("服务评分"))
        if None in (sc, n, hy, fa, en, se) or n <= 0:
            continue
        quality = (W_SCORE * sc + W_HYGIENE * hy + W_FACILITY * fa
                   + W_ENV * en + W_SERVICE * se)
        senti = sentiment(r.get("一句话点评"))
        rec = dict(r)
        rec.update({
            "_评分": sc, "_评论数": n, "_卫生": hy, "_设施": fa,
            "_环境": en, "_服务": se,
            "_情感得分": senti,
            "_质量分": round(quality, 4),
            "_评论数门槛": n >= C_PRIOR,
        })
        by_district[r["所属区"]].append(rec)

    all_ranked = {}
    for d in DISTRICTS:
        pool = by_district.get(d, [])
        if not pool:
            continue
        mean_q = st.mean(x["_质量分"] for x in pool)
        # 贝叶斯收缩：评论数少的酒店向区均值回归，抑制「12 条点评刷出 5.0」
        for x in pool:
            x["_质量分_信赖加权"] = round(
                (x["_评论数"] * x["_质量分"] + C_PRIOR * mean_q) / (x["_评论数"] + C_PRIOR), 4)

        ranked = sorted(pool, key=lambda x: x["_质量分_信赖加权"], reverse=True)
        all_ranked[d] = ranked

        print(f"\n{'='*100}")
        print(f"【{d}】入围 {len(pool)} 家（评论数>0） · 区质量均值 {mean_q:.3f}")
        print(f"{'='*100}")
        for i, x in enumerate(ranked[:CAND_PER_DISTRICT], 1):
            flag = "" if x["_评论数门槛"] else "  ⚠评论数<30"
            print(f" {i:>2}. {x['酒店名称'][:32]:<32} {x['星级']}星 {int(x['_评论数']):>5}条 "
                  f"评{x['_评分']} 卫{x['_卫生']}/设{x['_设施']}/环{x['_环境']}/服{x['_服务']} "
                  f"质量{x['_质量分']:.3f}→信赖{x['_质量分_信赖加权']:.3f} 情{x['_情感得分']:.2f}{flag}")

    # 导出各区候选池
    out = {}
    for d, ranked in all_ranked.items():
        out[d] = [{
            "排名": i,
            "酒店ID": x["唯一酒店ID"], "酒店名称": x["酒店名称"], "星级": x["星级"],
            "评分": x["_评分"], "评论数": int(x["_评论数"]),
            "卫生": x["_卫生"], "设施": x["_设施"], "环境": x["_环境"], "服务": x["_服务"],
            "质量分": x["_质量分"], "信赖质量分": x["_质量分_信赖加权"],
            "情感得分": x["_情感得分"], "所属商圈": x["所属商圈"],
            "位置描述": x["位置描述"], "详细地址": x["详细地址"],
            "经度": x["经度"], "纬度": x["纬度"], "首图URL": x["首图URL"],
            "入住房型": x["入住房型"], "床型描述": x["床型描述"],
            "一句话点评": x["一句话点评"],
            "价格": PRICE.get(x["唯一酒店ID"]),
        } for i, x in enumerate(ranked[:CAND_PER_DISTRICT], 1)]
    json.dump(out, open(os.path.join(BASE, "candidates_top12.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n\n已导出各区候选池 Top{CAND_PER_DISTRICT} → candidates_top12.json")
    print("★ 待补：价格（填入脚本 PRICE 字典）后即可套用完整公式出最终性价比 Top5")


if __name__ == "__main__":
    main()
