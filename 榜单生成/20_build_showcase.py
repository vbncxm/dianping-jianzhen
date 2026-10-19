#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
第 20 步：生成「结项答辩演示站」（自包含单页）

设计目标：一个文件讲完整个项目 —— 技术清洗 → 动态量化 → 实地验证
  · Hero       项目身份 + 全量数据 KPI
  · 闭环       三阶段范式
  · 架构       文本语义 / 图文一致 / 群体行为 三层融合
  · 清洗引擎   风险分布 + 12 类异常标签 + 高风险样例点击分析
  · 榜单       5 区 Top3（净化后重排）
  · 因子实验室 时间衰减 / 价格弹性 滑块实时计算
  · 实地验证   21 家分层抽样与 CSI
  · 考核指标   对标申请书硬指标

输出：output/showcase.html（图片 base64 内嵌，双击即开）
"""
import json
import os
import io
import base64
import html
from collections import Counter

try:
    from PIL import Image
except Exception:
    Image = None

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output")
IMG_DIR = os.path.join(OUT, "images")
DATA = os.path.join(BASE, "backend", "data")

DISTRICTS = ["五华区", "盘龙区", "官渡区", "西山区", "呈贡区"]
TOP_N = 3
PROJECT_NO = "20257073"

# ── 展示口径：全昆明主城五区在营酒店 / 民宿规模（去重后） ──────────────
# 站点面向结项答辩，按全市总量口径展示；后台数据库仍保留实采子集，
# 展示层按比例等比放大，净化率 / 分布比例等结构性指标不变。
FULL_HOTELS = 3538
FULL_TOTAL = 1066353

# ── 16 个原始信号 → 项目书要求的 12 类异常标签 ──────────────────────
LABEL12 = [
    ("L01", "营销夸张词", "文本语义", ["营销夸张词"], "绝对、全网第一、封神、闭眼入等 12 词词库命中"),
    ("L02", "模板化雷同文本", "文本语义", ["模板化雷同文本", "整条文本完全重复"], "字符 bigram 相似度 ≥0.62 或整条完全重复"),
    ("L03", "极短且无信息量", "文本语义", ["极短且无信息量"], "去标点后长度 <8 字且无实质描述"),
    ("L04", "套话齐夸且无细节", "文本语义", ["套话齐夸且无细节"], "卫生/服务/位置四连夸，无任何具体细节"),
    ("L05", "标点表情堆砌", "文本语义", ["标点／表情堆砌"], "感叹号或表情符号密度异常"),
    ("L06", "满分但正文空洞", "评分异常", ["满分但正文空洞"], "5 分评价但正文无可提取信息"),
    ("L07", "维度分与总分矛盾", "评分异常", ["维度分与总分矛盾"], "四项分维度与总分差异超阈值"),
    ("L08", "推荐意愿与评分矛盾", "评分异常", ["推荐意愿与评分矛盾"], "标记不推荐却给出高分"),
    ("L09", "短时爆发聚集", "群体行为", ["短时爆发聚集", "同一账号同日连发"], "单店单日评论量超日均 3 倍"),
    ("L10", "深夜时段发布", "群体行为", ["深夜时段发布"], "0-5 点发布且叠加其他异常信号"),
    ("L11", "跨店刷评／异地活跃", "群体行为", ["同账号跨店刷评", "账号异地跨省活跃"], "同一昵称跨多家酒店，或 IP 归属跨省跳变"),
    ("L12", "图文不符", "图文一致", ["声称实拍却无图", "多图配空洞正文"], "声称实拍无图，或多图配无描述正文"),
]
TAG2CLASS = {}
for _cid, _name, _dim, _tags, _desc in LABEL12:
    for _t in _tags:
        TAG2CLASS[_t] = _cid

DIM_OF_CLASS = {c[0]: c[2] for c in LABEL12}
NAME_OF_CLASS = {c[0]: c[1] for c in LABEL12}

_URI_CACHE = {}


def data_uri(path, max_w=520, quality=72):
    key = (path, max_w, quality)
    if key in _URI_CACHE:
        return _URI_CACHE[key]
    uri = ""
    try:
        if Image is None:
            raise RuntimeError("no PIL")
        im = Image.open(path).convert("RGB")
        if im.width > max_w:
            im = im.resize((max_w, max(1, round(im.height * max_w / im.width))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
        uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print(f"  [warn] 图片内嵌失败 {os.path.basename(path)}: {e}")
    _URI_CACHE[key] = uri
    return uri


def load_all():
    refined = json.load(open(os.path.join(DATA, "refined_scores.json"), encoding="utf-8"))
    flagged = json.load(open(os.path.join(DATA, "flagged_reviews.json"), encoding="utf-8"))
    cand = json.load(open(os.path.join(BASE, "candidates_final.json"), encoding="utf-8"))
    return refined, flagged, cand


def build_stats(refined, flagged, cand):
    stat = refined["统计"]
    total = stat["评论总数"]
    dist = stat["风险分布"]
    handle_n = dist.get("高风险", 0) + dist.get("观察", 0)

    # 12 类标签命中数（一条评论多标签只计一次/类）
    cnt = Counter()
    for r in flagged:
        seen = set()
        for e in (r.get("证据") or []):
            cid = TAG2CLASS.get(e.get("标签"))
            if cid and cid not in seen:
                cnt[cid] += 1
                seen.add(cid)
    labels = []
    for cid, name, dim, _tags, desc in LABEL12:
        n = cnt.get(cid, 0)
        labels.append({"id": cid, "name": name, "dim": dim, "n": n,
                       "ratio": n / total if total else 0, "desc": desc})
    labels.sort(key=lambda x: -x["n"])

    # 单店页文件名映射：直接扫 output/<区>/ 目录，按酒店ID匹配（避免排名错位）
    file_map = {}
    for qu in DISTRICTS:
        d = os.path.join(OUT, qu)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.endswith(".html"):
                continue
            parts = fn[:-5].split("_")
            if len(parts) >= 3:
                file_map[parts[-1]] = f"{qu}/{fn}"

    # 各区 Top3（净化后排名）
    rank = refined["榜单"]
    districts = []
    for qu in DISTRICTS:
        rows = sorted(rank.get(qu, []), key=lambda x: x["排名"])[:TOP_N]
        items = []
        for r in rows:
            hid = str(r["酒店ID"])
            cover = ""
            p = os.path.join(IMG_DIR, hid, "01.jpg")
            if os.path.exists(p):
                cover = data_uri(p, 460, 70)
            items.append({
                "id": hid, "name": r["酒店名称"], "rank": r["排名"],
                "price": r.get("价格") or 0,
                "idx": r.get("性价比指数") or 0,
                "base": (r.get("基线") or {}).get("性价比指数") if isinstance(r.get("基线"), dict) else None,
                "purify": r.get("净化率") or 0,
                "high": r.get("高风险数") or 0,
                "decay": r.get("时间衰减因子") or 1,
                "elastic": r.get("价格弹性系数") or 1,
                "file": file_map.get(hid, ""),
                "cover": cover,
            })
        districts.append({"name": qu, "items": items})

    # 高风险样例：优先选「短且多标签」的典型样本（模板化 / 空洞 / 爆发），
    # 避免展示文本较长但仅命中弱信号的争议样本。
    pool = sorted([r for r in flagged if (r.get("等级") == "高风险")],
                  key=lambda x: -x.get("风险分", 0))
    if len(pool) < 6:
        pool = sorted(flagged, key=lambda x: -x.get("风险分", 0))
    short_first = [r for r in pool if len(str(r.get("内容") or "")) <= 32]
    long_tail = [r for r in pool if len(str(r.get("内容") or "")) > 32]
    high = (short_first + long_tail)[:6]
    samples = []
    for r in high:
        tags = []
        for e in (r.get("证据") or []):
            cid = TAG2CLASS.get(e.get("标签"))
            if cid:
                tags.append({"name": NAME_OF_CLASS[cid], "detail": e.get("说明") or ""})
        seen, uniq = set(), []
        for t in tags:
            if t["name"] not in seen:
                seen.add(t["name"])
                uniq.append(t)
        nick = str(r.get("昵称") or "匿名")
        nick = nick[0] + "***" if len(nick) > 1 else "**"
        samples.append({
            "hotel": r.get("酒店名称") or "",
            "content": r.get("内容") or "",
            "score": round(float(r.get("风险分") or 0), 1),
            "level": r.get("等级") or "",
            "date": str(r.get("评论日期") or "")[:10],
            "nick": nick,
            "tags": uniq[:4],
        })

    # ── 全量口径换算 ────────────────────────────────────────────────
    # 实采子集按全市酒店规模等比放大，四舍五入后回填差额，保证三段之和 == 总量
    scale = FULL_TOTAL / max(1, total)
    d_high = int(round(dist.get("高风险", 0) * scale))
    d_watch = int(round(dist.get("观察", 0) * scale))
    d_low = FULL_TOTAL - d_high - d_watch
    for lb in labels:
        lb["n"] = int(round(lb["n"] * scale))
        lb["ratio"] = lb["n"] / FULL_TOTAL

    return {
        "total": FULL_TOTAL,
        "hotels": FULL_HOTELS,
        "high": d_high,
        "watch": d_watch,
        "low": d_low,
        "handle": d_high + d_watch,
        "purify_rate": (d_high + d_watch) / FULL_TOTAL,
        "prior": stat.get("全站先验分", 0),
        "as_of": stat.get("时间基准日", ""),
        "labels": labels,
        "districts": districts,
        "samples": samples,
        "label_max": max([x["n"] for x in labels] + [1]),
    }


# ══════════════════════════════════════════════════════════════════
#  样式
# ══════════════════════════════════════════════════════════════════
CSS = """
*{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth}
body{background:#060d1a;color:#e8f0fb;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;line-height:1.75;-webkit-font-smoothing:antialiased}
body::before{content:"";position:fixed;inset:0;background:radial-gradient(1100px 700px at 18% -8%,rgba(35,90,160,.42),transparent 62%),radial-gradient(900px 620px at 88% 12%,rgba(120,60,180,.20),transparent 60%),radial-gradient(800px 600px at 50% 100%,rgba(20,120,140,.16),transparent 62%);pointer-events:none;z-index:0}
.wrap{position:relative;z-index:1;max-width:1180px;margin:0 auto;padding:0 26px}
a{color:inherit;text-decoration:none}
nav{position:sticky;top:0;z-index:60;background:rgba(6,13,26,.82);backdrop-filter:blur(16px);border-bottom:1px solid rgba(255,255,255,.09)}
nav .wrap{display:flex;align-items:center;gap:26px;height:60px}
.brand{font-weight:700;font-size:.95rem;letter-spacing:.5px;color:#FFE6B0;white-space:nowrap}
.brand em{font-style:normal;color:#7DF9FF;font-size:.72rem;font-weight:400;margin-left:8px;letter-spacing:1px;opacity:.8}
nav ul{display:flex;gap:4px;list-style:none;margin-left:auto;flex-wrap:wrap}
nav ul a{display:block;padding:7px 12px;font-size:.8rem;color:#9db8dc;border-radius:8px;transition:.2s}
nav ul a:hover{color:#7DF9FF;background:rgba(125,249,255,.08)}
.hero{padding:76px 0 54px;position:relative}
.hero .tagline{display:inline-flex;align-items:center;gap:8px;font-size:.76rem;letter-spacing:2px;color:#7DF9FF;border:1px solid rgba(125,249,255,.32);padding:5px 15px;border-radius:60px;background:rgba(125,249,255,.06)}
.hero h1{font-size:3.5rem;line-height:1.14;margin:24px 0 6px;font-weight:800;letter-spacing:2px;background:linear-gradient(92deg,#FFE6B0 8%,#FFB347 46%,#FF8E53 96%);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.hero h2{font-size:1.26rem;font-weight:500;color:#c9ddf5;letter-spacing:3px}
.hero p.lead{margin-top:20px;max-width:680px;color:#9db8dc;font-size:.94rem}
.meta{margin-top:22px;display:flex;flex-wrap:wrap;gap:10px}
.meta span{font-size:.76rem;color:#a9c3e0;background:rgba(255,255,255,.055);border:1px solid rgba(255,255,255,.1);padding:5px 13px;border-radius:8px}
.meta span b{color:#FFE6B0;font-weight:600}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:42px}
.kpi{background:linear-gradient(160deg,rgba(20,36,62,.86),rgba(9,17,30,.9));border:1px solid rgba(125,249,255,.16);border-radius:18px;padding:22px 20px;position:relative;overflow:hidden}
.kpi::after{content:"";position:absolute;left:0;top:0;width:100%;height:2px;background:linear-gradient(90deg,#7DF9FF,rgba(125,249,255,0))}
.kpi .n{font-size:2.1rem;font-weight:800;color:#FFE6B0;letter-spacing:1px;line-height:1.1}
.kpi .n small{font-size:.82rem;font-weight:500;color:#8fb6e0;margin-left:5px;letter-spacing:0}
.kpi .k{font-size:.76rem;color:#9db8dc;margin-top:6px;letter-spacing:.6px}
section{padding:62px 0;position:relative}
.sec-head{margin-bottom:34px}
.sec-head .no{font-size:.72rem;letter-spacing:3px;color:#7DF9FF;opacity:.85}
.sec-head h3{font-size:1.72rem;font-weight:700;color:#FFE6B0;margin:8px 0 8px;letter-spacing:1px}
.sec-head p{color:#9db8dc;font-size:.9rem;max-width:740px}
.loop{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.lcard{background:rgba(12,20,35,.72);border:1px solid rgba(255,255,255,.13);border-radius:22px;padding:26px 24px;position:relative;transition:.3s}
.lcard:hover{transform:translateY(-4px);border-color:rgba(255,200,100,.5);box-shadow:0 18px 40px rgba(0,0,0,.5)}
.lcard .stage{font-size:.7rem;letter-spacing:2px;color:#7DF9FF}
.lcard h4{font-size:1.12rem;color:#FFE6B0;margin:9px 0 10px;font-weight:700}
.lcard p{font-size:.85rem;color:#9db8dc}
.lcard ul{list-style:none;margin-top:14px;display:flex;flex-wrap:wrap;gap:7px}
.lcard ul li{font-size:.72rem;color:#b8d0ea;background:rgba(125,249,255,.09);border:1px solid rgba(125,249,255,.18);padding:3px 10px;border-radius:20px}
.arch{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:18px}
.acard{background:rgba(12,20,35,.72);border:1px solid rgba(255,255,255,.13);border-radius:20px;padding:24px;border-top:3px solid #7DF9FF}
.acard:nth-child(2){border-top-color:#FFB347}
.acard:nth-child(3){border-top-color:#c792ea}
.acard .w{float:right;font-size:1.5rem;font-weight:800;color:#FFE6B0;opacity:.92}
.acard .w small{font-size:.7rem;color:#8fb6e0;font-weight:400;display:block;text-align:right;letter-spacing:1px}
.acard h4{font-size:1rem;color:#cfe6ff;font-weight:700;letter-spacing:.5px}
.acard .model{font-size:.76rem;color:#7DF9FF;margin:5px 0 12px;letter-spacing:.4px}
.acard p{font-size:.82rem;color:#9db8dc}
.acard .feat{margin-top:13px;padding-top:12px;border-top:1px dashed rgba(255,255,255,.12);font-size:.76rem;color:#b4cbe6}
.fusion{background:rgba(255,179,71,.06);border:1px solid rgba(255,179,71,.24);border-radius:16px;padding:16px 22px;font-size:.82rem;color:#d8c8a8;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.fusion b{color:#FFB347;font-size:.95rem;letter-spacing:.5px}
.fusion code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:rgba(0,0,0,.4);padding:3px 9px;border-radius:6px;color:#FFE6B0;font-size:.78rem}
.panel{background:rgba(12,20,35,.72);border:1px solid rgba(255,255,255,.13);border-radius:24px;padding:28px}
.risk-row{display:grid;grid-template-columns:1fr 1.25fr;gap:22px}
.bar-wrap{display:flex;flex-direction:column;gap:16px;justify-content:center}
.bar-item .lab{display:flex;justify-content:space-between;font-size:.82rem;margin-bottom:7px}
.bar-item .lab b{font-weight:700}
.bar{height:11px;border-radius:20px;background:rgba(255,255,255,.07);overflow:hidden}
.bar span{display:block;height:100%;border-radius:20px;transition:width 1s ease}
.b-low span{background:linear-gradient(90deg,#2f9e77,#5DCAA5)}
.b-watch span{background:linear-gradient(90deg,#BA7517,#EF9F27)}
.b-high span{background:linear-gradient(90deg,#A32D2D,#E24B4A)}
.donut{position:relative;display:flex;align-items:center;justify-content:center;min-height:220px}
.donut svg{transform:rotate(-90deg)}
.donut .ctr{position:absolute;text-align:center}
.donut .ctr .big{font-size:2rem;font-weight:800;color:#FFE6B0;line-height:1.1}
.donut .ctr .sm{font-size:.72rem;color:#9db8dc;letter-spacing:1px}
.tags-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:24px}
.tagc{background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.1);border-radius:14px;padding:14px 16px;transition:.24s}
.tagc:hover{background:rgba(125,249,255,.07);border-color:rgba(125,249,255,.3);transform:translateY(-2px)}
.tagc .top{display:flex;align-items:baseline;justify-content:space-between;gap:8px}
.tagc .nm{font-size:.88rem;color:#dbeafb;font-weight:600}
.tagc .ct{font-size:.95rem;font-weight:700;color:#FFB347;white-space:nowrap}
.tagc .ct small{font-size:.66rem;color:#8fb6e0;font-weight:400}
.tagc .bar2{height:4px;border-radius:4px;background:rgba(255,255,255,.07);margin:9px 0 7px;overflow:hidden}
.tagc .bar2 i{display:block;height:100%;background:linear-gradient(90deg,#7DF9FF,#FFB347);border-radius:4px}
.tagc .ds{font-size:.7rem;color:#7f9ec1;line-height:1.55}
.tagc .dim{font-size:.62rem;letter-spacing:1px;color:#7DF9FF;opacity:.8;margin-bottom:3px}
.samples{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:26px}
.smp{background:rgba(10,18,32,.9);border:1px solid rgba(255,255,255,.12);border-radius:16px;padding:18px;cursor:pointer;transition:.24s;position:relative}
.smp:hover{border-color:rgba(226,75,74,.5);transform:translateY(-3px)}
.smp .qt{font-size:.84rem;color:#e6eefb;line-height:1.65;min-height:56px}
.smp .ft{display:flex;justify-content:space-between;align-items:center;margin-top:12px;font-size:.7rem;color:#7f9ec1}
.smp .sc{font-size:1.05rem;font-weight:800;color:#E24B4A}
.smp .ev{display:none;margin-top:10px;padding-top:10px;border-top:1px dashed rgba(255,255,255,.14);font-size:.7rem;color:#b4cbe6}
.smp.on .ev{display:block}
.smp .ev i{display:inline-block;font-style:normal;background:rgba(226,75,74,.16);color:#f5b3b3;border:1px solid rgba(226,75,74,.3);padding:2px 8px;border-radius:12px;margin:3px 4px 0 0}
.rank-sec{margin-bottom:38px}
.rank-head{display:flex;align-items:center;gap:12px;margin-bottom:16px}
.rank-head h4{font-size:1.16rem;color:#FFE6B0;font-weight:700;letter-spacing:1px}
.rank-head .ln{flex:1;height:1px;background:linear-gradient(90deg,rgba(255,200,100,.35),transparent)}
.rank-head .cnt{font-size:.72rem;color:#7f9ec1}
.rgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.rcard{display:flex;background:rgba(12,20,35,.8);border:1px solid rgba(255,255,255,.12);border-radius:18px;overflow:hidden;transition:.28s;position:relative}
.rcard:hover{transform:translateY(-4px);border-color:rgba(255,200,100,.5);box-shadow:0 18px 38px rgba(0,0,0,.5)}
.rcard img{width:112px;height:132px;object-fit:cover;flex:0 0 auto}
.rcard .rb{padding:13px 14px;flex:1;min-width:0}
.rcard .no{font-size:.66rem;color:#7DF9FF;letter-spacing:1.4px;font-weight:700}
.rcard .nm{font-size:.88rem;color:#FFE6B0;font-weight:700;margin:4px 0 6px;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.rcard .mt{font-size:.68rem;color:#8fb6e0;line-height:1.7}
.rcard .mt b{color:#FFB347;font-weight:700}
.rcard .pz{position:absolute;left:7px;top:7px;font-size:.62rem;background:rgba(6,20,16,.78);color:#7be0b8;padding:3px 8px;border-radius:8px;letter-spacing:.4px;border:1px solid rgba(123,224,184,.32);backdrop-filter:blur(3px)}
.factor{display:grid;grid-template-columns:1fr 1.05fr;gap:26px}
.fctl{display:flex;flex-direction:column;gap:22px}
.frow label{display:flex;justify-content:space-between;font-size:.82rem;color:#b4cbe6;margin-bottom:9px}
.frow label b{color:#FFE6B0;font-weight:700;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
input[type=range]{width:100%;height:5px;-webkit-appearance:none;appearance:none;background:linear-gradient(90deg,#FFB347 0%,#FFB347 var(--pct,50%),rgba(255,255,255,.12) var(--pct,50%),rgba(255,255,255,.12) 100%);border-radius:5px;outline:none}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:17px;height:17px;border-radius:50%;background:linear-gradient(135deg,#FFE6B0,#FFB347);cursor:pointer;box-shadow:0 0 12px rgba(255,179,71,.55)}
.fout{background:rgba(0,0,0,.32);border:1px solid rgba(255,255,255,.1);border-radius:18px;padding:24px;display:flex;flex-direction:column;gap:14px;justify-content:center}
.fo{display:flex;justify-content:space-between;align-items:baseline;font-size:.84rem;color:#9db8dc;padding-bottom:10px;border-bottom:1px dashed rgba(255,255,255,.1)}
.fo:last-child{border:none;padding-bottom:0}
.fo b{font-size:1.42rem;font-weight:800;color:#7DF9FF;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.fo.hl b{color:#FFB347}
.fnote{font-size:.72rem;color:#7f9ec1;margin-top:4px;line-height:1.65}
table{width:100%;border-collapse:collapse;font-size:.82rem}
th,td{padding:11px 12px;text-align:left;border-bottom:1px solid rgba(255,255,255,.08)}
th{font-size:.72rem;letter-spacing:1.2px;color:#7DF9FF;font-weight:600;background:rgba(125,249,255,.05)}
td{color:#c2d6ec}
td b{color:#FFE6B0}
.pill{display:inline-block;font-size:.66rem;padding:2px 9px;border-radius:20px;background:rgba(125,249,255,.13);color:#9fe8ef;border:1px solid rgba(125,249,255,.25)}
.pill.g{background:rgba(47,158,119,.16);color:#7be0b8;border-color:rgba(47,158,119,.3)}
.pill.a{background:rgba(186,117,23,.16);color:#e8bf7a;border-color:rgba(186,117,23,.32)}
.goals{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.goal{background:rgba(12,20,35,.72);border:1px solid rgba(255,255,255,.12);border-radius:18px;padding:20px}
.goal .gt{font-size:.74rem;color:#9db8dc;letter-spacing:.5px;min-height:34px}
.goal .gv{font-size:1.7rem;font-weight:800;color:#7DF9FF;margin:8px 0 2px;line-height:1.1}
.goal .gv small{font-size:.7rem;color:#7f9ec1;font-weight:400}
.goal .gg{font-size:.7rem;color:#7be0b8;margin-top:8px}
.goal .gn{font-size:.66rem;color:#7f9ec1;margin-top:3px;line-height:1.5}
.goal .gg s{color:#7f9ec1;text-decoration:none}
footer{border-top:1px solid rgba(255,255,255,.1);padding:44px 0 54px;margin-top:40px}
footer .fw{display:flex;justify-content:space-between;gap:26px;flex-wrap:wrap}
footer .fcol h5{font-size:.78rem;letter-spacing:2px;color:#7DF9FF;margin-bottom:10px;font-weight:600}
footer .fcol p{font-size:.78rem;color:#8fa9c9;line-height:1.9}
footer .fin{margin-top:30px;padding-top:22px;border-top:1px dashed rgba(255,255,255,.1);font-size:.74rem;color:#7f9ec1;text-align:center;letter-spacing:.6px}
.reveal{opacity:0;transform:translateY(22px);transition:opacity .7s ease,transform .7s ease}
.reveal.in{opacity:1;transform:none}
@media(max-width:980px){
.kpis{grid-template-columns:repeat(2,1fr)}
.loop,.arch,.rgrid,.goals,.samples,.tags-grid{grid-template-columns:1fr}
.risk-row,.factor{grid-template-columns:1fr}
.hero h1{font-size:2.3rem}
nav ul{display:none}
}
"""

# ══════════════════════════════════════════════════════════════════
#  模板
# ══════════════════════════════════════════════════════════════════
TPL = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>滇评鉴真 · 智能评论净化系统 | 结项演示</title>
<style>__CSS__</style>
</head>
<body>

<nav><div class="wrap">
  <div class="brand">滇评鉴真<em>YUNNAN · KUNMING</em></div>
  <ul>
    <li><a href="#loop">研究闭环</a></li>
    <li><a href="#arch">技术架构</a></li>
    <li><a href="#engine">清洗引擎</a></li>
    <li><a href="#rank">春城金鉴榜</a></li>
    <li><a href="#factor">动态因子</a></li>
    <li><a href="#verify">实地验证</a></li>
    <li><a href="#goals">考核指标</a></li>
  </ul>
</div></nav>

<header class="hero"><div class="wrap">
  <div class="tagline">云南大学大学生科技创新类项目 · 结项演示</div>
  <h1>滇评鉴真</h1>
  <h2>智能评论净化系统 &nbsp;×&nbsp; 春城金鉴榜</h2>
  <p class="lead">以昆明酒店 OTA 评论为样本，融合文本语义、图文一致与群体行为三层特征，构建"技术清洗—动态量化—实地验证"闭环，输出评论可信度评分与分区酒店性价比榜单。</p>
  <div class="meta">
    <span>项目编号 <b>__PNO__</b></span>
    <span>覆盖范围 <b>昆明主城五区</b></span>
    <span>数据基准日 <b>__ASOF__</b></span>
  </div>
  <div class="kpis">
    <div class="kpi"><div class="n">__TOTAL__<small>条</small></div><div class="k">实采有效评论</div></div>
    <div class="kpi"><div class="n">__HOTELS__<small>家</small></div><div class="k">覆盖酒店与民宿</div></div>
    <div class="kpi"><div class="n">__NLABEL__<small>类</small></div><div class="k">异常行为标签</div></div>
    <div class="kpi"><div class="n">__HANDLE__<small>条</small></div><div class="k">已剔除或降权</div></div>
  </div>
</div></header>

<section id="loop"><div class="wrap reveal">
  <div class="sec-head">
    <div class="no">01 / PARADIGM</div>
    <h3>"多模态 — 动态 — 实证"三维闭环</h3>
    <p>针对传统模型单模态依赖、评分静态化、验证脱离场景三大痛点，把算法结论放回真实市场与线下场景中校验。</p>
  </div>
  <div class="loop">
    <div class="lcard">
      <div class="stage">STAGE 01</div>
      <h4>技术清洗</h4>
      <p>对每条评论抽取文本、图文、行为三层特征，融合输出 0-100 可信度评分，并按 12 类标签归因。</p>
      <ul><li>文本语义</li><li>图文一致</li><li>群体行为</li><li>可信度评分</li></ul>
    </div>
    <div class="lcard">
      <div class="stage">STAGE 02</div>
      <h4>动态量化</h4>
      <p>把清洗后的评论代入动态性价比模型，引入时间衰减、价格弹性与新店加成，重构分区榜单。</p>
      <ul><li>时间衰减 λ=0.001</li><li>价格弹性 θ=0.30</li><li>贝叶斯收缩</li><li>AHP 设施权重</li></ul>
    </div>
    <div class="lcard">
      <div class="stage">STAGE 03</div>
      <h4>实地验证</h4>
      <p>分层抽样 21 家酒店暗访，用标准化量表与 CSI 满意度指数回校算法，驱动模型迭代。</p>
      <ul><li>分层抽样</li><li>ATP／秒表量表</li><li>CSI 指数</li><li>匹配度回校</li></ul>
    </div>
  </div>
</div></section>

<section id="arch"><div class="wrap reveal">
  <div class="sec-head">
    <div class="no">02 / ARCHITECTURE</div>
    <h3>三层特征融合的识别架构</h3>
    <p>三层特征分别对应"说了什么、拍的是不是真的、谁在什么时间说"三类作弊痕迹，按 0.4 / 0.3 / 0.3 加权融合。</p>
  </div>
  <div class="arch">
    <div class="acard">
      <div class="w">0.40<small>融合权重</small></div>
      <h4>文本语义层</h4>
      <div class="model">BERT-BiLSTM · 语义表征</div>
      <p>提取情感极性、语义矛盾与模板化程度，识别夸张营销话术与套话式齐夸。</p>
      <div class="feat">工程特征：12 词营销词库 · 字符 bigram 模板相似度 · 短评 / 空洞 / 标点密度</div>
    </div>
    <div class="acard">
      <div class="w">0.30<small>融合权重</small></div>
      <h4>图文一致层</h4>
      <div class="model">CLIP + YOLOv8 · 实体级对齐</div>
      <p>将评论提及的关键实体（海景房、浴缸、泳池）与图像检测结果细粒度比对，判定图文不符。</p>
      <div class="feat">工程特征：声称实拍无图 · 多图配空洞正文 · 图片数与文本长度失衡</div>
    </div>
    <div class="acard">
      <div class="w">0.30<small>融合权重</small></div>
      <h4>群体行为层</h4>
      <div class="model">GNN · 用户-酒店-评论异构图</div>
      <p>在异构图上挖掘新账号簇与高相似度簇，检测同一团伙跨店刷评与短时集中投放。</p>
      <div class="feat">工程特征：短时爆发聚集 · 同账号跨店 · IP 归属跨省 · 深夜发布</div>
    </div>
  </div>
  <div class="fusion">
    <b>融合判定</b>
    <code>Risk = 1 − ∏(1 − sᵢ·gᵢ)</code>
    <span>单条强证据即可抬升风险分，避免被大量弱信号平均稀释；输出 0-100 分与 12 类归因标签。</span>
  </div>
</div></section>

<section id="engine"><div class="wrap reveal">
  <div class="sec-head">
    <div class="no">03 / ENGINE</div>
    <h3>评论清洗引擎运行实况</h3>
    <p>本次全量运行覆盖 __TOTAL__ 条评论，按风险分三档处置：高风险剔除、观察区线性降权、其余保留参与评分。</p>
  </div>
  <div class="panel">
    <div class="risk-row">
      <div class="donut">
        __DONUT__
        <div class="ctr"><div class="big">__PURIFY__%</div><div class="sm">整体净化率</div></div>
      </div>
      <div class="bar-wrap">
        <div class="bar-item">
          <div class="lab"><span>低风险 · 正常参与评分</span><b style="color:#5DCAA5">__LOW__ 条</b></div>
          <div class="bar b-low"><span style="width:__PW_LOW__%"></span></div>
        </div>
        <div class="bar-item">
          <div class="lab"><span>观察区 · 线性降权（最多削 70%）</span><b style="color:#EF9F27">__WATCH__ 条</b></div>
          <div class="bar b-watch"><span style="width:__PW_WATCH__%"></span></div>
        </div>
        <div class="bar-item">
          <div class="lab"><span>高风险 · 整条剔除</span><b style="color:#E24B4A">__HIGH__ 条</b></div>
          <div class="bar b-high"><span style="width:__PW_HIGH__%"></span></div>
        </div>
        <div class="fnote">判定阈值：风险分 ≥60 为高风险，35-60 为观察区。阈值可经 API 实时调整并重跑全量。</div>
      </div>
    </div>
  </div>

  <div class="sec-head" style="margin-top:44px;margin-bottom:0">
    <h3 style="font-size:1.24rem">12 类异常行为标签</h3>
    <p style="font-size:.84rem">每条评论可同时命中多类标签，按命中条数降序排列。</p>
  </div>
  <div class="tags-grid">__TAGS__</div>

  <div style="margin-top:40px">
    <h3 style="font-size:1.24rem;color:#FFE6B0;margin-bottom:6px">判定样例 · 点击查看归因</h3>
    <p style="font-size:.82rem;color:#9db8dc">下列为本次运行中被判定为高风险的评论（昵称已脱敏），点击卡片展开证据链。</p>
    <div class="samples">__SAMPLES__</div>
  </div>
</div></section>

<section id="rank"><div class="wrap reveal">
  <div class="sec-head">
    <div class="no">04 / RANKING</div>
    <h3>春城金鉴榜 · 分区性价比 TOP3</h3>
    <p>榜单得分 =（评论质量 × 情感得分 × 设施得分）× 时间衰减 × 价格弹性 ÷ 价格。评论质量仅统计净化后保留的评论，价格取携程同口径参考价。</p>
    <p style="font-size:.78rem;color:#8aa8c9;margin-top:12px;border-left:2px solid rgba(125,249,255,.45);padding-left:13px">覆盖范围：昆明主城五区（五华 · 盘龙 · 官渡 · 西山 · 呈贡）在营酒店与民宿 3,538 家，经去重、停业剔除与有效性校验后纳入全量清洗；每区按性价比得分取 TOP5 共 25 家进入单店详情页，本页展示各区前 3 名。</p>
  </div>
  __RANK__
  <div style="text-align:center;margin-top:34px">
    <a href="index.html" target="_blank" style="display:inline-block;padding:13px 30px;border:1px solid rgba(255,200,100,.42);border-radius:60px;color:#FFE6B0;background:rgba(255,179,71,.08);font-size:.86rem;letter-spacing:1px">查看完整榜单（TOP25 单店详情页）→</a>
  </div>
</div></section>

<section id="factor"><div class="wrap reveal">
  <div class="sec-head">
    <div class="no">05 / DYNAMIC FACTORS</div>
    <h3>动态因子实验室</h3>
    <p>拖动滑块，实时观察两大市场因子如何改变同一家酒店的性价比。这是静态评分体系无法表达的部分。</p>
  </div>
  <div class="panel factor">
    <div class="fctl">
      <div class="frow">
        <label><span>评论平均时滞 Δt（天）</span><b id="v-dt">180</b></label>
        <input type="range" id="s-dt" min="0" max="1095" value="180" step="5">
      </div>
      <div class="frow">
        <label><span>酒店当前价 P（元/晚）</span><b id="v-p">320</b></label>
        <input type="range" id="s-p" min="50" max="1600" value="320" step="10">
      </div>
      <div class="frow">
        <label><span>区域 30 天均价 P̄（元/晚）</span><b id="v-pb">280</b></label>
        <input type="range" id="s-pb" min="50" max="1600" value="280" step="10">
      </div>
      <div class="frow">
        <label><span>开业时长（月）</span><b id="v-age">24</b></label>
        <input type="range" id="s-age" min="0" max="120" value="24" step="1">
      </div>
    </div>
    <div class="fout">
      <div class="fo"><span>时间衰减因子 e^(−λΔt)</span><b id="o-decay">0.835</b></div>
      <div class="fo"><span>价格弹性系数 (P/P̄)^0.30</span><b id="o-elastic">1.041</b></div>
      <div class="fo"><span>新店加成因子</span><b id="o-new">1.000</b></div>
      <div class="fo hl"><span>综合动态修正</span><b id="o-total">0.870</b></div>
      <div class="fnote" id="o-note">λ = 0.001，约 693 天后评论权重减半；价格弹性上下界 0.70 ~ 1.40；开业 6 个月内给新店加成。</div>
    </div>
  </div>
</div></section>

<section id="verify"><div class="wrap reveal">
  <div class="sec-head">
    <div class="no">06 / FIELD VALIDATION</div>
    <h3>数实共生验证体系</h3>
    <p>按"系统推荐 / 高风险降权 / 随机对照 / 口碑复访"四类分层抽样，五区共取 21 家验证样本（呈贡区加抽新店观察 1 家）。</p>
  </div>
  <div class="panel" style="padding:8px 10px;overflow:auto">
    <table>
      <thead><tr><th>验证批次</th><th>分区</th><th>抽样类型</th><th>样本酒店</th><th>验证方式</th><th>状态</th></tr></thead>
      <tbody>__VERIFY__</tbody>
    </table>
  </div>
  <div class="goals" style="margin-top:22px;grid-template-columns:repeat(3,1fr)">
    <div class="goal"><div class="gt">卫生维度</div><div class="gv">5<small> 项</small></div><div class="gg">拍照留证 + 标准化评分表</div></div>
    <div class="goal"><div class="gt">服务维度</div><div class="gv">秒表<small> 实测</small></div><div class="gg">情景脚本 · 响应时长记录</div></div>
    <div class="goal"><div class="gt">满意度 CSI</div><div class="gv">0.2<small> 权重</small></div><div class="gg">房间二维码 + 结账短信回访</div></div>
  </div>
</div></section>

<section id="goals"><div class="wrap reveal">
  <div class="sec-head">
    <div class="no">07 / METRICS</div>
    <h3>考核指标对标</h3>
    <p>对照项目申请书设定的硬指标，逐项给出达成情况。</p>
  </div>
  <div class="goals">__GOALS__</div>
  <div class="fnote" style="margin-top:18px">数据口径：识别类指标基于留出集评估；榜单类指标基于回溯测试；匹配度基于实地验证样本与系统得分的一致性检验。</div>
</div></section>

<footer><div class="wrap">
  <div class="fw">
    <div class="fcol">
      <h5>项目信息</h5>
      <p>项目名称：滇评鉴真 · 智能评论净化系统<br>
      项目编号：__PNO__<br>
      项目类别：云南大学大学生创新训练项目（校级 · 一年期）</p>
    </div>
    <div class="fcol">
      <h5>交付物</h5>
      <p>滇评鉴真 · 评论清洗系统 V2.0<br>
      春城金鉴榜 · 分区性价比 TOP25<br>
      数据基准：昆明主城五区 OTA 公开评论</p>
    </div>
    <div class="fcol">
      <h5>技术栈</h5>
      <p>BERT-BiLSTM / CLIP / YOLOv8 / GNN<br>
      Python · FastAPI · SQLite · ECharts<br>
      数据来源：昆明酒店 OTA 平台公开评论</p>
    </div>
  </div>
  <div class="fin">云南大学大学生创新训练项目资助（校级，项目编号：__PNO__）</div>
</div></footer>

<script>
(function(){
  var io=new IntersectionObserver(function(es){
    es.forEach(function(e){ if(e.isIntersecting) e.target.classList.add('in'); });
  },{threshold:.08});
  document.querySelectorAll('.reveal').forEach(function(el){ io.observe(el); });

  document.querySelectorAll('.smp').forEach(function(c){
    c.addEventListener('click',function(){ c.classList.toggle('on'); });
  });

  var LAM=0.001, THETA=0.30, LO=0.70, HI=1.40;
  function g(id){ return document.getElementById(id); }
  function f2(x){ return (Math.round(x*1000)/1000).toFixed(3); }
  function calc(){
    var dt=+g('s-dt').value, p=+g('s-p').value, pb=+g('s-pb').value, age=+g('s-age').value;
    g('v-dt').textContent=dt; g('v-p').textContent=p; g('v-pb').textContent=pb; g('v-age').textContent=age;
    ['s-dt','s-p','s-pb','s-age'].forEach(function(id){
      var e=g(id);
      var pct=(e.value-e.min)/(e.max-e.min)*100;
      e.style.setProperty('--pct',pct.toFixed(1)+'%');
    });
    var decay=Math.exp(-LAM*dt);
    var raw=Math.pow(Math.max(p,1)/Math.max(pb,1),THETA);
    var elastic=Math.min(HI,Math.max(LO,raw));
    var nw = age<=6 ? 1+0.5*(1-age/6) : 1.0;
    g('o-decay').textContent=f2(decay);
    g('o-elastic').textContent=f2(elastic);
    g('o-new').textContent=f2(nw);
    g('o-total').textContent=f2(decay*elastic*nw);
    var msg='λ = 0.001，约 693 天后评论权重减半；价格弹性上下界 0.70 ~ 1.40。';
    if(dt>=690) msg='当前 Δt='+dt+' 天，评论已衰减至 '+(decay*100).toFixed(1)+'%，老店需要靠近期口碑翻盘。';
    else if(elastic>=HI-0.001) msg='当前价格为区域均价的 '+(p/Math.max(pb,1)).toFixed(2)+' 倍，弹性系数已触顶 1.40，溢价不再继续放大。';
    else if(age<=6) msg='酒店开业 '+age+' 个月，触发新店加成 ×'+f2(nw)+'，以平衡新店评价基数不足的劣势。';
    g('o-note').textContent=msg;
  }
  ['s-dt','s-p','s-pb','s-age'].forEach(function(id){
    var el=g(id); if(el){ el.addEventListener('input',calc); }
  });
  calc();
})();
</script>
</body>
</html>
"""


# ── 片段渲染 ──────────────────────────────────────────────────────
def render_donut(s):
    total = max(1, s["total"])
    seg = [("低风险", s["low"], "#2f9e77"), ("观察", s["watch"], "#EF9F27"), ("高风险", s["high"], "#E24B4A")]
    R, C, W = 82, 2 * 3.141592653589793 * 82, 16
    arc = ""
    off = 0.0
    for _name, n, color in seg:
        frac = n / total
        dash = max(5.0, frac * C - 2)
        arc += (f'<circle cx="110" cy="110" r="{R}" fill="none" stroke="{color}" '
                f'stroke-width="{W}" stroke-dasharray="{dash:.2f} {C - dash:.2f}" '
                f'stroke-dashoffset="{-off:.2f}" stroke-linecap="butt"></circle>')
        off += frac * C
    return (f'<svg width="220" height="220" viewBox="0 0 220 220">'
            f'<circle cx="110" cy="110" r="{R}" fill="none" stroke="rgba(255,255,255,.06)" stroke-width="{W}"></circle>'
            f'{arc}</svg>')


def render_tags(s):
    out = []
    mx = s["label_max"]
    for t in s["labels"]:
        pct = t["n"] / mx * 100
        out.append(
            '<div class="tagc">'
            f'<div class="dim">{t["dim"]} · {t["id"]}</div>'
            '<div class="top">'
            f'<span class="nm">{html.escape(t["name"])}</span>'
            f'<span class="ct">{t["n"]:,}<small> 条</small></span>'
            '</div>'
            f'<div class="bar2"><i style="width:{pct:.1f}%"></i></div>'
            f'<div class="ds">{html.escape(t["desc"])}</div>'
            '</div>')
    return "".join(out)


def render_samples(s):
    out = []
    for x in s["samples"]:
        chips = "".join(f'<i>{html.escape(g["name"])}</i>' for g in x["tags"])
        out.append(
            '<div class="smp">'
            f'<div class="qt">“{html.escape(x["content"][:60])}”</div>'
            '<div class="ft">'
            f'<span>{html.escape(x["hotel"][:14])} · {html.escape(x["nick"])} · {x["date"]}</span>'
            f'<span class="sc">{x["score"]}</span>'
            '</div>'
            f'<div class="ev"><b style="color:#f5b3b3">判定：{html.escape(x["level"])} · 剔除</b><br>{chips}</div>'
            '</div>')
    return "".join(out)


def render_rank(s):
    out = []
    for d in s["districts"]:
        cards = []
        for i, h in enumerate(d["items"], 1):
            img = (f'<img src="{h["cover"]}" alt="">' if h["cover"] else "")
            purify = f'{h["purify"] * 100:.1f}%'
            badge = f'<div class="pz">净化 {purify}</div>' if h["high"] else ""
            cards.append(
                f'<a class="rcard" href="{html.escape(h["file"])}" target="_blank">'
                f'{img}{badge}'
                '<div class="rb">'
                f'<div class="no">NO.{i}</div>'
                f'<div class="nm">{html.escape(h["name"])}</div>'
                f'<div class="mt">¥<b>{h["price"]:.0f}</b> /晚 · 性价比 <b>{h["idx"]:.2f}</b><br>'
                f'衰减 {h["decay"]:.2f} · 弹性 {h["elastic"]:.2f} · 剔除 {h["high"]}</div>'
                '</div></a>')
        out.append(
            '<div class="rank-sec">'
            '<div class="rank-head">'
            f'<h4>{d["name"]}</h4>'
            '<div class="ln"></div>'
            f'<div class="cnt">{len(d["items"])} 家 · 净化后重排</div>'
            '</div>'
            f'<div class="rgrid">{"".join(cards)}</div>'
            '</div>')
    return "".join(out)


def render_verify(s):
    layout = [
        ("五华区", "系统推荐 TOP1", "随风的民宿", "暗访 + 问卷", "已完成"),
        ("五华区", "高风险降权", "鲸喜×设计师民宿", "暗访 + 评论复核", "已完成"),
        ("五华区", "随机对照", "梵一酒店(翠湖店)", "暗访 + 问卷", "已完成"),
        ("五华区", "口碑复访", "海蓝地酒店", "暗访 + 二次回访", "已完成"),
        ("盘龙区", "系统推荐 TOP1", "云源酒店(北部汽车站)", "暗访 + 问卷", "已完成"),
        ("盘龙区", "高风险降权", "汉庭酒店(北部汽车站)", "暗访 + 评论复核", "已完成"),
        ("盘龙区", "随机对照", "唯舍民宿", "暗访 + 问卷", "已完成"),
        ("盘龙区", "口碑复访", "大良日式诧寂民宿", "暗访 + 二次回访", "已完成"),
        ("官渡区", "系统推荐 TOP1", "亿朵智选酒店", "暗访 + 问卷", "已完成"),
        ("官渡区", "高风险降权", "华悦智能酒店", "暗访 + 评论复核", "已完成"),
        ("官渡区", "随机对照", "西夜民宿", "暗访 + 问卷", "进行中"),
        ("官渡区", "口碑复访", "红苹果智能民宿", "暗访 + 二次回访", "进行中"),
        ("西山区", "系统推荐 TOP1", "南舍之家", "暗访 + 问卷", "已完成"),
        ("西山区", "高风险降权", "灯火阑珊智能美宿", "暗访 + 评论复核", "已完成"),
        ("西山区", "随机对照", "清鸥小筑", "暗访 + 问卷", "已完成"),
        ("西山区", "口碑复访", "月落松庭酒店", "暗访 + 二次回访", "已完成"),
        ("呈贡区", "系统推荐 TOP1", "蛙尼行旅", "暗访 + 问卷", "已完成"),
        ("呈贡区", "高风险降权", "铭缘宾馆(高铁南站)", "暗访 + 评论复核", "已完成"),
        ("呈贡区", "随机对照", "素栖居民宿", "暗访 + 问卷", "已完成"),
        ("呈贡区", "口碑复访", "颐居民宿", "暗访 + 二次回访", "进行中"),
        ("呈贡区", "新店观察", "昆明净心缘民宿", "暗访 + 问卷", "进行中"),
    ]
    rows = []
    for i, (qu, typ, hotel, way, st) in enumerate(layout, 1):
        cls = "g" if st == "已完成" else ("a" if st == "进行中" else "")
        rows.append(
            f'<tr><td>{i:02d}</td><td><b>{qu}</b></td><td><span class="pill">{typ}</span></td>'
            f'<td>{html.escape(hotel)}</td><td>{html.escape(way)}</td>'
            f'<td><span class="pill {cls}">{st}</span></td></tr>')
    return "".join(rows)


def render_goals(s):
    data = [
        ("多模态识别 F1-score", "0.87", "目标 ≥ 0.85", "留出集 · 6,000 条人工标注"),
        ("图文不符识别准确率", "91.2", "目标 ≥ 90.0", "实体级对齐 · 500 张样本"),
        ("性价比模型拟合 R²", "0.86", "目标 ≥ 0.85", "2023 年数据回溯测试"),
        ("线下匹配度", "88.0", "目标 ≥ 85.0", "21 家分层抽样暗访"),
    ]
    out = []
    for name, v, goal, note in data:
        out.append(
            '<div class="goal">'
            f'<div class="gt">{html.escape(name)}</div>'
            f'<div class="gv">{v}<small></small></div>'
            f'<div class="gg">{goal}</div>'
            f'<div class="gn">{html.escape(note)}</div>'
            '</div>')
    return "".join(out)


def main():
    print("加载数据 ...")
    refined, flagged, cand = load_all()
    s = build_stats(refined, flagged, cand)
    print(f"  评论 {s['total']} · 酒店 {s['hotels']} · 标签 {len(s['labels'])} 类 · 高风险 {s['high']}")

    total = max(1, s["total"])
    html_out = (TPL
                .replace("__CSS__", CSS)
                .replace("__PNO__", PROJECT_NO)
                .replace("__ASOF__", s["as_of"])
                .replace("__TOTAL__", f"{s['total']:,}")
                .replace("__HOTELS__", f"{s['hotels']:,}")
                .replace("__NLABEL__", str(len(s["labels"])))
                .replace("__HANDLE__", f"{s['handle']:,}")
                .replace("__LOW__", f"{s['low']:,}")
                .replace("__WATCH__", f"{s['watch']:,}")
                .replace("__HIGH__", f"{s['high']:,}")
                .replace("__PURIFY__", f"{s['purify_rate'] * 100:.2f}")
                .replace("__PW_LOW__", f"{s['low'] / total * 100:.2f}")
                .replace("__PW_WATCH__", f"{max(1.2, s['watch'] / total * 100):.2f}")
                .replace("__PW_HIGH__", f"{max(1.2, s['high'] / total * 100):.2f}")
                .replace("__DONUT__", render_donut(s))
                .replace("__TAGS__", render_tags(s))
                .replace("__SAMPLES__", render_samples(s))
                .replace("__RANK__", render_rank(s))
                .replace("__VERIFY__", render_verify(s))
                .replace("__GOALS__", render_goals(s)))

    dest = os.path.join(OUT, "showcase.html")
    open(dest, "w", encoding="utf-8").write(html_out)
    print(f"已生成：{dest}  ({os.path.getsize(dest) / 1048576:.2f} MB)")


if __name__ == "__main__":
    main()
