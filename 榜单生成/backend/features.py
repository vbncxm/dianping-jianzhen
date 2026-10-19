# -*- coding: utf-8 -*-
"""评论特征抽取：把一条原始评论转成检测器可用的数值／布尔特征。

输出结构（每条评论一个 dict）：
    text     —— 文本痕迹特征
    temporal —— 时间行为特征
    account  —— 账号行为特征
    rating   —— 评分异常特征
    media    —— 图文一致性特征
"""
import collections
import datetime as dt
from typing import Dict, List

from . import lexicon as LX
from .config import Config

DIM_FIELDS = ("位置分", "设施分", "服务分", "客房分")


def _parse_dt(s):
    if not s:
        return None
    s = str(s).strip().replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s[:len(fmt) + 2].strip(), fmt)
        except Exception:
            continue
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


def normalize_text(t: str) -> str:
    """去标点／空白／emoji，用于重复与模板比对。"""
    if not t:
        return ""
    t = LX.EMOJI_RE.sub("", t)
    t = LX.PUNCT_RE.sub("", t)
    return t.strip()


def bigrams(t: str):
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) >= 2 else ({t} if t else set())


def _max_template_sim(texts_norm: List[str], min_shared: int = 4):
    """同店内互相比对，返回 (每条评论的最大 Jaccard 相似度, 与之最像的下标)。

    用倒排表 + 共享 shingle 门槛剪枝，避免 O(n²) 全量比较。
    """
    n = len(texts_norm)
    sims = [0.0] * n
    partner = [-1] * n
    grams = [bigrams(t) for t in texts_norm]

    inverted = collections.defaultdict(list)
    for i, gs in enumerate(grams):
        for g in gs:
            inverted[g].append(i)

    for i in range(n):
        gi = grams[i]
        if not gi:
            continue
        cand = collections.Counter()
        for g in gi:
            for j in inverted[g]:
                if j > i:
                    cand[j] += 1
        best, bj = 0.0, -1
        for j, shared in cand.most_common(60):
            if shared < min_shared:
                break
            gj = grams[j]
            inter = shared
            union = len(gi) + len(gj) - inter
            if union <= 0:
                continue
            s = inter / union
            if s > best:
                best, bj = s, j
        sims[i] = best
        partner[i] = bj
    return sims, partner


def extract(reviews: List[dict], cfg: Config, as_of: dt.datetime = None) -> List[dict]:
    """就地给每条评论补充 feats 字段，并返回同一个列表。"""
    by_hotel = collections.defaultdict(list)
    for i, r in enumerate(reviews):
        r["_i"] = i
        by_hotel[r["酒店ID"]].append(r)

    # ── 账号维度：昵称 → 酒店集合 / IP 省份集合 ─────────────────────
    nick_hotels = collections.defaultdict(set)
    nick_prov = collections.defaultdict(set)
    nick_dates = collections.defaultdict(set)
    for r in reviews:
        nk = (r.get("昵称") or "").strip()
        if not nk or nk in LX.GENERIC_NICKS:
            continue
        nick_hotels[nk].add(r["酒店ID"])
        prov = (r.get("IP归属") or "").replace("发布于", "").strip()
        if prov:
            nick_prov[nk].add(prov)
        d = _parse_dt(r.get("评论日期"))
        if d:
            nick_dates[nk].add(d.date())

    # ── 聚合：店×日 条数、店 日均 ───────────────────────────────────
    for hid, rows in by_hotel.items():
        day_cnt = collections.Counter()
        day_nick = collections.Counter()
        for r in rows:
            d = _parse_dt(r.get("评论日期"))
            r["_dt"] = d
            if d:
                day_cnt[d.date()] += 1
                day_nick[(d.date(), (r.get("昵称") or "").strip())] += 1
        total = len(rows)
        days = max(1, len(day_cnt))
        avg_daily = total / days

        texts_norm = [normalize_text(r.get("评论内容") or "") for r in rows]
        exact = collections.Counter(t for t in texts_norm if len(t) >= 6)
        sims, partner = _max_template_sim(texts_norm)

        for k, r in enumerate(rows):
            r["feats"] = _one(r, cfg, day_cnt, day_nick, avg_daily,
                              texts_norm[k], exact, sims[k], partner[k],
                              nick_hotels, nick_prov, nick_dates, as_of)
    return reviews


def _one(r, cfg: Config, day_cnt, day_nick, avg_daily, tnorm, exact, max_sim,
         partner, nick_hotels, nick_prov, nick_dates, as_of) -> Dict:
    raw = r.get("评论内容") or ""
    d = r.get("_dt")

    # ══ 文本痕迹 ═══════════════════════════════════════════════════
    hype = LX.hit_hype(raw)
    exclaim = raw.count("!") + raw.count("！")
    emoji = len(LX.EMOJI_RE.findall(raw))
    concrete = LX.hit_concrete(raw)
    cliche = LX.cliche_hits(raw)
    tlen = len(raw)
    exact_n = exact.get(tnorm, 0) if len(tnorm) >= 6 else 0

    pos_cnt, neg_cnt = LX.get_sentiment(raw)
    text = {
        "长度": tlen,
        "_sent": (pos_cnt, neg_cnt),
        "正词数": pos_cnt,
        "负词数": neg_cnt,
        "营销词数": len(hype),
        "营销词": hype[:5],
        "感叹号数": exclaim,
        "emoji数": emoji,
        "具体词数": concrete,
        "套话维度数": cliche,
        "模板相似度": round(max_sim, 3),
        "完全重复数": exact_n,
        "疑似模板": max_sim >= cfg.dup_sim_threshold,
        "完全重复": exact_n >= 2,
        "超短": tlen < cfg.min_len_short,
        "无细节": concrete == 0 and not LX.DIGIT_RE.search(raw),
    }

    # ══ 时间行为 ═══════════════════════════════════════════════════
    night = bool(d and d.hour in cfg.night_hours)
    dcnt = day_cnt.get(d.date(), 0) if d else 0
    ratio = dcnt / avg_daily if avg_daily > 0 else 0.0
    burst = bool(dcnt >= cfg.city_burst_min and ratio >= cfg.burst_ratio)
    same_nick = day_nick.get((d.date(), (r.get("昵称") or "").strip()), 0) if d else 0

    gap_days = None
    c_dt = _parse_dt(r.get("评论日期"))
    i_dt = _parse_dt(r.get("入住日期"))
    if c_dt and i_dt:
        gap_days = (c_dt - i_dt).days

    temporal = {
        "发布小时": d.hour if d else None,
        "深夜发布": night,
        "当日同店条数": dcnt,
        "当日倍数": round(ratio, 2),
        "爆发聚集": burst,
        "同日同昵称条数": same_nick,
        "入住评论间隔天": gap_days,
        "时间错位": bool(gap_days is not None and gap_days > cfg.max_gap_days),
    }

    # ══ 账号行为 ═══════════════════════════════════════════════════
    nk = (r.get("昵称") or "").strip()
    generic = (not nk) or nk in LX.GENERIC_NICKS
    n_hotels = len(nick_hotels.get(nk, ())) if not generic else 0
    n_prov = len(nick_prov.get(nk, ())) if not generic else 0
    n_days = len(nick_dates.get(nk, ())) if not generic else 0

    account = {
        "昵称": nk,
        "通用昵称": generic,
        "随机串昵称": bool(LX.RANDOM_NICK.match(nk)) if nk else True,
        "昵称跨店数": n_hotels,
        "昵称跨省数": n_prov,
        "昵称活跃天数": n_days,
        "跨店刷评": n_hotels >= 2,
        "跨省刷评": n_prov >= 2,
    }

    # ══ 评分异常 ═══════════════════════════════════════════════════
    total = r.get("总分")
    dims = [r.get(f) for f in DIM_FIELDS]
    dims_v = [x for x in dims if x is not None]
    dim_avg = round(sum(dims_v) / len(dims_v), 3) if dims_v else None
    spread = round(max(dims_v) - min(dims_v), 3) if len(dims_v) >= 2 else 0.0
    all5 = bool(dims_v) and all(x >= 5 for x in dims_v)
    reco = r.get("推荐")

    rating = {
        "总分": total,
        "推荐": reco,
        "维度均分": dim_avg,
        "维度极差": spread,
        "全五星": all5 and total is not None and total >= 5,
        "满分无文本": bool(all5 and total is not None and total >= 5 and tlen < 12),
        "维度总分矛盾": bool(spread >= 1.0),
        "推荐与评分矛盾": bool((reco is True and total is not None and total <= 3)
                          or (reco is False and total is not None and total >= 4)),
    }

    # ══ 图文一致性 ═════════════════════════════════════════════════
    img = int(r.get("图片数") or 0)
    claims = bool(LX.CLAIM_IMAGE.search(raw))
    media = {
        "图片数": img,
        "声称实拍": claims,
        "声称实拍无图": bool(claims and img == 0),
        "图文失衡": bool(img >= 5 and tlen < 12),
    }
    return {"text": text, "temporal": temporal, "account": account,
            "rating": rating, "media": media}
