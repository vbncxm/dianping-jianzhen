# -*- coding: utf-8 -*-
"""虚假评论检测器：五类信号融合 → 0~100 风险分 + 证据标签 + 清洗权重。

评分逻辑（两级合成）
    ① 每个子信号先算 0~1 的强度，乘上各自的「增益 g」；
       同一维度内用**模糊或**累积：dim = 1 - Π(1 - sᵢ·gᵢ)。
       这样单个强证据（如整条文本完全重复、同账号跨店刷评）就能把该维度抬到 0.8 以上，
       不会被大量弱信号的平均值稀释掉。
    ② 五个维度分按 Config 权重加权 ×100 得风险分；
       命中「强证据」时再乘 1.25 并 +8，使其稳稳越过高风险线。

    增益 g 的含义：该信号单独出现时能把维度抬多高。
    g 越高越「定罪」，g 越低越只能做辅证。
"""
from typing import Dict, List, Tuple

from .config import Config

LEVEL_LOW = "低风险"
LEVEL_WATCH = "观察"
LEVEL_HIGH = "高风险"

# 每个信号的增益（单独命中时的维度贡献上限）
GAIN = {
    # 文本痕迹
    "hype": 0.55, "template": 0.85, "dup": 0.90, "punct": 0.45,
    "cliche": 0.50, "blank": 0.35,
    # 时间行为
    "burst": 0.80, "ratio": 0.40, "night": 0.20, "same_nick": 0.50, "gap": 0.35,
    # 账号行为
    "cross_hotel": 0.85, "cross_prov": 0.60, "activity": 0.30, "random_nick": 0.22,
    # 评分异常
    "blank5": 0.45, "spread": 0.50, "reco_contra": 0.65, "all5": 0.18,
    # 图文一致性
    "claim_img": 0.60, "imbalance": 0.45,
}
STRONG_TAGS = {"整条文本完全重复", "同账号跨店刷评", "短时爆发聚集", "模板化雷同文本"}


def fuzzy_or(pairs: List[Tuple[float, float]]) -> float:
    """pairs: [(强度0~1, 增益)] → 1 - Π(1 - s·g)"""
    prod = 1.0
    for s, g in pairs:
        s = min(1.0, max(0.0, s))
        prod *= (1.0 - min(1.0, s * g))
    return 1.0 - prod


def _text_score(f, cfg: Config):
    t = f["text"]
    ev, pairs = [], []

    hype = min(1.0, t["营销词数"] / max(1, cfg.hype_density_cap))
    pairs.append((hype, GAIN["hype"]))
    if hype > 0:
        ev.append(("营销夸张词", "文本痕迹", round(hype, 2),
                   "命中：" + "／".join(t["营销词"]) if t["营销词"] else ""))

    sim = t["模板相似度"]
    tmpl = 0.0 if sim < cfg.dup_sim_threshold else min(1.0, (sim - 0.45) / 0.5)
    pairs.append((tmpl, GAIN["template"]))
    if tmpl > 0:
        ev.append(("模板化雷同文本", "文本痕迹", round(tmpl, 2),
                   f"与同店另一条评论相似度 {sim:.0%}"))

    dup = 1.0 if t["完全重复"] else 0.0
    pairs.append((dup, GAIN["dup"]))
    if dup:
        ev.append(("整条文本完全重复", "文本痕迹", 1.0,
                   f"同店出现 {t['完全重复数']} 次相同正文"))

    ex = min(1.0, t["感叹号数"] / max(1, cfg.exclaim_cap)) if t["长度"] < 80 else 0.0
    ex = max(ex, min(1.0, t["emoji数"] / 6))
    pairs.append((ex, GAIN["punct"]))
    if ex >= 0.5:
        ev.append(("标点／表情堆砌", "文本痕迹", round(ex, 2),
                   f"感叹号 {t['感叹号数']} 个、表情 {t['emoji数']} 个"))

    cliche = min(1.0, t["套话维度数"] / 4) if t["无细节"] else 0.0
    pairs.append((cliche, GAIN["cliche"]))
    if cliche > 0:
        ev.append(("套话齐夸且无细节", "文本痕迹", round(cliche, 2),
                   f"同时夸奖 {t['套话维度数']} 个维度，全文无具体信息"))

    blank = 1.0 if (t["超短"] and t["无细节"]) else 0.0
    pairs.append((blank, GAIN["blank"]))
    if blank:
        ev.append(("极短且无信息量", "文本痕迹", 0.6, f"正文仅 {t['长度']} 字"))

    return fuzzy_or(pairs), ev


def _temporal_score(f, cfg: Config):
    t = f["temporal"]
    ev, pairs = [], []

    burst = 1.0 if t["爆发聚集"] else 0.0
    pairs.append((burst, GAIN["burst"]))
    if burst:
        ev.append(("短时爆发聚集", "时间行为", 0.9,
                   f"同日 {t['当日同店条数']} 条，为日均 {t['当日倍数']} 倍"))

    ratio = min(1.0, max(0.0, t["当日倍数"] / 6.0))
    pairs.append((ratio, GAIN["ratio"]))

    night = 1.0 if t["深夜发布"] else 0.0
    pairs.append((night, GAIN["night"]))
    if night:
        ev.append(("深夜时段发布", "时间行为", 0.35, f"{t['发布小时']} 点发布"))

    same = min(1.0, t["同日同昵称条数"] / 3.0)
    pairs.append((same, GAIN["same_nick"]))
    if same >= 0.5:
        ev.append(("同一账号同日连发", "时间行为", round(same, 2),
                   f"同一天同一昵称 {t['同日同昵称条数']} 条"))

    gap = 1.0 if t["时间错位"] else 0.0
    pairs.append((gap, GAIN["gap"]))
    if gap:
        ev.append(("评论与入住时间错位", "时间行为", 0.5,
                   f"离店后 {t['入住评论间隔天']} 天才评论"))

    return fuzzy_or(pairs), ev


def _account_score(f, cfg: Config):
    a = f["account"]
    ev, pairs = [], []
    if a["通用昵称"]:
        return 0.0, ev

    nh = a["昵称跨店数"]
    cross = 1.0 if nh >= 3 else (0.6 if nh == 2 else 0.0)
    pairs.append((cross, GAIN["cross_hotel"]))
    if cross > 0:
        ev.append(("同账号跨店刷评", "账号行为", round(cross, 2),
                   f"该昵称出现在 {nh} 家酒店"))

    npv = a["昵称跨省数"]
    cprov = 1.0 if npv >= 3 else (0.7 if npv == 2 else 0.0)
    pairs.append((cprov, GAIN["cross_prov"]))
    if cprov > 0:
        ev.append(("账号异地跨省活跃", "账号行为", round(cprov, 2),
                   f"IP 归属跨越 {npv} 个省份"))

    pairs.append((min(1.0, a["昵称活跃天数"] / 20.0), GAIN["activity"]))
    pairs.append((1.0 if a["随机串昵称"] else 0.0, GAIN["random_nick"]))
    return fuzzy_or(pairs), ev


def _rating_score(f, cfg: Config):
    r = f["rating"]
    ev, pairs = [], []

    blank5 = 1.0 if r["满分无文本"] else 0.0
    pairs.append((blank5, GAIN["blank5"]))
    if blank5:
        ev.append(("满分但正文空洞", "评分异常", 0.85, "四维与总分全 5 分，正文极短"))

    spread = r["维度极差"]
    contra = 1.0 if spread >= 1.5 else (0.6 if spread >= 1.0 else 0.0)
    pairs.append((contra, GAIN["spread"]))
    if contra > 0:
        ev.append(("维度分与总分矛盾", "评分异常", round(contra, 2),
                   f"各维度分极差 {spread}"))

    rec = 1.0 if r["推荐与评分矛盾"] else 0.0
    pairs.append((rec, GAIN["reco_contra"]))
    if rec:
        ev.append(("推荐意愿与评分矛盾", "评分异常", 0.8,
                   f"总分 {r['总分']}，但推荐={r.get('推荐')}"))

    pairs.append((1.0 if r["全五星"] else 0.0, GAIN["all5"]))
    return fuzzy_or(pairs), ev


def _media_score(f, cfg: Config):
    m = f["media"]
    ev, pairs = [], []
    claim = 1.0 if m["声称实拍无图"] else 0.0
    pairs.append((claim, GAIN["claim_img"]))
    if claim:
        ev.append(("声称实拍却无图", "图文一致性", 0.7, "正文提到图片／实拍，实际 0 张图"))
    imb = 1.0 if m["图文失衡"] else 0.0
    pairs.append((imb, GAIN["imbalance"]))
    if imb:
        ev.append(("多图配空洞正文", "图文一致性", 0.6, f"{m['图片数']} 张图但正文极短"))
    return fuzzy_or(pairs), ev


def detect_one(feats: dict, cfg: Config) -> dict:
    """对单条评论特征打分，返回风险分／等级／证据。"""
    w = cfg.normalized_weights()
    parts = {
        "text": _text_score(feats, cfg),
        "temporal": _temporal_score(feats, cfg),
        "account": _account_score(feats, cfg),
        "rating": _rating_score(feats, cfg),
        "media": _media_score(feats, cfg),
    }
    dims = {k: round(v[0], 4) for k, v in parts.items()}
    evidence = []
    for k, (s, ev) in parts.items():
        for it in ev:
            evidence.append({"标签": it[0], "维度": it[1],
                             "强度": it[2], "说明": it[3]})

    risk = 100.0 * sum(dims[k] * w[k] for k in dims)

    # 强证据提升：命中任一「定罪级」标签，直接抬升
    strong = any(e["标签"] in STRONG_TAGS and e["强度"] >= 0.6 for e in evidence)
    strong_multi = sum(1 for e in evidence if e["强度"] >= 0.7) >= 3
    if strong:
        risk = min(100.0, risk * 1.25 + 8)
    if strong_multi:
        risk = min(100.0, risk * 1.15 + 5)

    risk = round(risk, 2)
    if risk >= cfg.high_threshold:
        level = LEVEL_HIGH
    elif risk >= cfg.watch_threshold:
        level = LEVEL_WATCH
    else:
        level = LEVEL_LOW
    return {"风险分": risk, "等级": level, "维度分": dims, "证据": evidence}


def clean_weight(det: dict, cfg: Config) -> float:
    """按风险等级计算该条评论在酒店评分中的权重（0~1）。"""
    risk, level = det["风险分"], det["等级"]
    if level == LEVEL_HIGH:
        return 0.0 if cfg.drop_high else 1.0 - cfg.max_downweight
    if level == LEVEL_WATCH:
        span = max(1e-6, cfg.high_threshold - cfg.watch_threshold)
        t = (risk - cfg.watch_threshold) / span
        return 1.0 - cfg.max_downweight * max(0.0, min(1.0, t))
    return 1.0


def detect_all(reviews: List[dict], cfg: Config) -> List[dict]:
    """给每条评论写入 detection / 清洗权重 字段。"""
    for r in reviews:
        det = detect_one(r["feats"], cfg)
        r["detection"] = det
        r["清洗权重"] = round(clean_weight(det, cfg), 4)
    return reviews
