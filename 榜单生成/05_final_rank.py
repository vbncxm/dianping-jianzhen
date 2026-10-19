# -*- coding: utf-8 -*-
"""
第五步：价格接入后，套用《项目计划申请书》的完整公式重排，输出最终 Top5。

输入（三选一，优先级从高到低）：
    1) prices.json            —— {"酒店ID": 价格, ...}
    2) 价格采集模板.csv        —— 填好「价格（元/晚，待填）」列
    3) 携程价格采集.csv        —— 含 hotelId / price 两列（脚本自动识别列名）

公式（与申请书口径对齐）：
    性价比指数 =（评论质量 × 情感得分 × 设施得分）× 时间衰减因子 × 价格弹性系数 ÷ 价格

    评论质量 = 信赖质量分 / 5         （口碑四维 AHP 加权 + 评论数贝叶斯收缩，0~1）
    情感得分 = 一句话点评情感极性      （0~1）
    设施得分 = 设施评分 / 5           （0~1）
    时间衰减 e^(-λΔt) = 1            ★数据源无评论时间戳，取中性值
    价格弹性系数      = 1            ★数据源无区域 30 天均价，取中性值

用法：
    python 05_final_rank.py            # 有价格→出最终榜；无价格→提示缺哪些
"""
import json, os, csv, collections

BASE = os.path.dirname(os.path.abspath(__file__))
DISTRICTS = ["五华区", "盘龙区", "官渡区", "西山区", "呈贡区"]
TOP_N = 5
NEUTRAL_DECAY = 1.0     # 时间衰减因子（中性值，缺时间戳）
NEUTRAL_ELASTIC = 1.0   # 价格弹性系数（中性值，缺区域均价）
SCALE = 1000.0          # 仅用于把指数拉到易读量级，不改变排序


def load_prices():
    """返回 {酒店ID: 价格(float)}"""
    pj = os.path.join(BASE, "prices.json")
    if os.path.exists(pj):
        raw = json.load(open(pj, encoding="utf-8"))
        return {str(k): float(v) for k, v in raw.items() if v not in (None, "")}, "prices.json"

    for fn in ("价格采集模板.csv", "携程价格采集.csv"):
        fp = os.path.join(BASE, fn)
        if not os.path.exists(fp):
            continue
        out = {}
        with open(fp, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                keys = {k.strip() if k else k: v for k, v in row.items()}
                hid = next((keys[k] for k in keys
                            if k and ("酒店ID" in k or k.lower() in ("hotelid", "id"))), None)
                pcol = next((keys[k] for k in keys
                             if k and ("价格" in k or k.lower() in ("price",))), None)
                if not hid:
                    continue
                try:
                    p = float(str(pcol).replace("¥", "").replace("元", "").strip())
                except Exception:
                    continue
                if p > 0:
                    out[str(hid).strip()] = p
        if out:
            return out, fn
    return {}, None


def main():
    cands = json.load(open(os.path.join(BASE, "candidates_top15.json"), encoding="utf-8"))
    prices, src = load_prices()

    need = [c["酒店ID"] for d in cands.values() for c in d]
    miss = [i for i in need if i not in prices]
    print(f"价格来源：{src or '未找到价格文件'}")
    print(f"候选 {len(need)} 家 · 已匹配价格 {len(need)-len(miss)} 家 · 缺 {len(miss)} 家")
    if miss:
        print("  缺失明细：", ", ".join(miss[:20]) + (" ..." if len(miss) > 20 else ""))

    if not prices:
        print("\n⚠ 尚无价格数据。三条补价路径：")
        print("  1) 浏览器登录携程后导出 cookie，交给脚本批量采（见 06_fetch_prices.py）")
        print("  2) 人工填 价格采集模板.csv 的「价格（元/晚，待填）」列")
        print("  3) 自建 prices.json：{\"酒店ID\": 价格}")
        print("  补好后重跑本脚本即可 → candidates_final.json → 03_build_pages.py")
        return

    final = {}
    for d in DISTRICTS:
        pool = cands.get(d, [])
        rows = []
        for c in pool:
            p = prices.get(c["酒店ID"])
            if not p:
                continue
            q = c["信赖质量分"] / 5.0
            s = c["情感得分"]
            fa = c["设施"] / 5.0
            base = q * s * fa
            idx = base * NEUTRAL_DECAY * NEUTRAL_ELASTIC * SCALE / p
            r = dict(c)
            r.update({"_base": round(base, 4), "价格": round(p, 0),
                      "性价比指数": round(idx, 2)})
            rows.append(r)

        if not rows:
            continue
        rows.sort(key=lambda x: x["性价比指数"], reverse=True)
        hi = rows[0]["性价比指数"]
        for i, r in enumerate(rows, 1):
            r["排名"] = i
            r["区内归一"] = round(r["性价比指数"] / hi * 100, 1)
            r.pop("_base", None)
        final[d] = rows[:TOP_N]

        print(f"\n{'='*118}")
        print(f"【{d}】性价比榜 Top{TOP_N}（候选池 {len(rows)} 家有价）")
        print(f"{'='*118}")
        for r in final[d]:
            print(f" {r['排名']:>2}. {r['酒店名称'][:30]:<30} ¥{int(r['价格']):>5} "
                  f"性价比{r['性价比指数']:>7.2f}（归一{r['区内归一']:>5}）"
                  f" 信赖{r['信赖质量分']:.3f} 情{r['情感得分']:.2f} 设施{r['设施']}")

    json.dump(final, open(os.path.join(BASE, "candidates_final.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # 口碑榜 vs 性价比榜 对比表（写报告用）
    cmp_path = os.path.join(BASE, "口碑榜与性价比榜对比.csv")
    with open(cmp_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["区", "口碑榜名次", "口碑榜酒店", "性价比榜名次", "性价比榜酒店",
                    "价格（元/晚）", "性价比指数"])
        for d in DISTRICTS:
            old = {c["酒店ID"]: c for c in cands.get(d, [])}
            new = {r["酒店ID"]: r for r in final.get(d, [])}
            for i in range(1, TOP_N + 1):
                o = cands[d][i-1] if len(cands.get(d, [])) >= i else None
                n = final[d][i-1] if len(final.get(d, [])) >= i else None
                w.writerow([d,
                            i if o else "", o["酒店名称"] if o else "",
                            i if n else "", n["酒店名称"] if n else "",
                            int(n["价格"]) if n else "", n["性价比指数"] if n else ""])

    print(f"\n\n已导出：candidates_final.json（各区 Top{TOP_N}）")
    print(f"已导出：口碑榜与性价比榜对比.csv")
    print("下一步：python 03_build_pages.py   → 重新生成 25 个单店页 + 总榜页")


if __name__ == "__main__":
    main()
