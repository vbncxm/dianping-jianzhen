# -*- coding: utf-8 -*-
"""
第三步：生成单店展示页（复用 展示.html 的视觉风格）
- 每个区取前 N 名（默认 5），每名生成一个独立 HTML
- 另生成一个 index.html 总入口，按区分组
- 价格：若 candidates 中该酒店有「价格」，则启用「价格优势」维度与价格展示；
        否则该维度替换为「口碑热度」（按评论数归一），并在页面明确标注
输出目录：output/
"""
import json, os, html, math, shutil, subprocess, io, base64

try:
    from PIL import Image
except Exception:
    Image = None

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output")
IMG_DIR = os.path.join(OUT, "images")
DISTRICTS = ["五华区", "盘龙区", "官渡区", "西山区", "呈贡区"]
TOP_N = 5
DOWNLOAD_IMAGES = True

# 把图片内嵌为 base64，保证在「预览面板 / file:// / 发给别人」等任何环境都能显示
EMBED_IMAGES = True
EMBED_MAX_W = 800      # 相册大图重编码后的最大宽度
EMBED_QUALITY = 76
COVER_MAX_W = 520      # 总榜卡片封面（更小）
COVER_QUALITY = 72
_URI_CACHE = {}


def data_uri(path, max_w=EMBED_MAX_W, quality=EMBED_QUALITY):
    """读本地图片 → 缩放重编码 → 返回 data:image/jpeg;base64,..."""
    key = (path, max_w, quality)
    if key in _URI_CACHE:
        return _URI_CACHE[key]
    uri = ""
    try:
        if Image is None:
            raise RuntimeError("no PIL")
        im = Image.open(path)
        im = im.convert("RGB")
        if im.width > max_w:
            im = im.resize((max_w, max(1, round(im.height * max_w / im.width))),
                           Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
        uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print(f"    [warn] 内嵌失败 {os.path.basename(path)}: {e}")
        uri = ""
    _URI_CACHE[key] = uri
    return uri


def fetch_image(url, dest):
    """把首图下载到本地，失败则返回 False（页面会回退到远程地址）"""
    if not url or os.path.exists(dest):
        return os.path.exists(dest)
    try:
        r = subprocess.run(
            ["curl", "-s", "-L", "--max-time", "25",
             "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
             "-e", "https://hotels.ctrip.com/",
             "-o", dest, "-w", "%{http_code}", url],
            capture_output=True, text=True, timeout=40)
        ok = r.stdout.strip() == "200" and os.path.exists(dest) and os.path.getsize(dest) > 2000
        if not ok and os.path.exists(dest):
            os.remove(dest)
        return ok
    except Exception:
        return False

_CAND_FILE = "candidates_final.json"
if not os.path.exists(os.path.join(BASE, _CAND_FILE)):
    _CAND_FILE = "candidates_top12.json"
CAND = json.load(open(os.path.join(BASE, _CAND_FILE), encoding="utf-8"))
ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"
ECHARTS_SRC = ECHARTS_CDN     # main() 里若下载成功会改成相对路径，便于离线提交

# ── 后端清洗结果（backend/data/refined_scores.json）───────────────────
REFINED_FILE = os.path.join(BASE, "backend", "data", "refined_scores.json")


def load_refined():
    try:
        with open(REFINED_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  [提示] 未读取到后端净化结果（{e}），页面将不含净化区块")
        return None


REFINED = load_refined()
R_HOTELS = (REFINED or {}).get("酒店", {}) or {}
R_STATS = (REFINED or {}).get("统计", {}) or {}
R_RANK = (REFINED or {}).get("榜单", {}) or {}

_SIG_NAME = {"text": "文本痕迹", "temporal": "时间行为",
             "account": "账号行为", "rating": "评分异常", "media": "图文一致性"}


def build_purify(h, hid):
    """生成「评论净化」区块：净化后评分 + 因子拆解 + 风险评论明细。"""
    d = R_HOTELS.get(str(hid))
    if not d:
        return ""
    cfg = (REFINED or {}).get("配置", {})
    base = d.get("基线") or {}
    before = base.get("性价比指数") or 0
    after = d.get("性价比指数") or 0
    delta = ((after - before) / before * 100) if before else 0
    arrow = "↓" if delta < 0 else "↑"
    cls = "down" if delta < 0 else "up"

    def pc(k, v, sub="", klass=""):
        return (f'<div class="pcard {klass}"><div class="pk">{k}</div>'
                f'<div class="pv">{v}</div>'
                f'{f"<div class=pd>{sub}</div>" if sub else ""}</div>')

    cards = [
        pc("评论净化率", f"{d.get('净化率', 0)*100:.1f}%",
           f"有效评论 {d.get('保留评论数')}/{d.get('评论总数')}"),
        pc("剔除高风险", f"{d.get('高风险数', 0)}<small> 条</small>",
           f"另有 {d.get('观察数', 0)} 条降权", "warn" if d.get("高风险数") else ""),
        pc("时间衰减因子", f"{d.get('时间衰减因子', 1):.3f}",
           f"λ={cfg.get('lambda_decay', 0.001)}／天"),
        pc("价格弹性系数", f"{d.get('价格弹性系数', 1):.3f}",
           f"θ={cfg.get('theta_elastic', 0.30)}"),
        pc("净化后性价比", f"{after:.2f}",
           f"评论质量 {d.get('评论质量', 0):.3f} / 情感 {d.get('情感得分', 0):.3f}"),
    ]

    risky = d.get("风险评论", []) or []
    items = []
    for r in risky[:8]:
        evs = "".join(
            f'<span class="ev-tag" title="{html.escape(str(e.get("说明") or ""))}">'
            f'{html.escape(str(e.get("标签")))}</span>' for e in (r.get("证据") or [])[:5])
        nick = str(r.get("昵称") or "匿名")
        nick = nick[:3] + "***" if len(nick) > 4 else nick
        kls = "watch" if r.get("等级") == "观察" else ""
        items.append(
            f'<div class="risk-item {kls}">'
            f'<div class="risk-top"><span class="risk-score">风险分 {r.get("风险分")}</span>'
            f'<span>·</span><span>{html.escape(str(r.get("等级")))}</span>'
            f'<span>·</span><span>{html.escape(nick)}</span>'
            f'<span>·</span><span>{html.escape(str(r.get("日期") or "")[:10])}</span>'
            f'<span>·</span><span>清洗权重 {r.get("清洗权重")}</span></div>'
            f'<div class="risk-body">{html.escape(str(r.get("摘要") or ""))}</div>'
            f'<div class="risk-ev">{evs}</div></div>')

    more = (f'<div class="risk-more">另有 {len(risky)-8} 条风险评论未展示 · '
            f'可通过后端 <code>/api/hotels/{hid}/reviews</code> 查询全部</div>'
            if len(risky) > 8 else "")

    risk_block = ""
    if items:
        title = ("评论净化明细 · 已剔除／降权样本" if d.get("高风险数")
                 else "评论净化明细 · 发现疑点样本")
        risk_block = (f'<div class="risk-list"><h4>🔎 {title}</h4>'
                      + "".join(items) + more + "</div>")

    return f"""<div class="purify">
  <div class="purify-head">
    <span class="dot-live"></span>
    <span class="purify-title">🛡️ 后端评论净化</span>
    <span class="chip blue">五类信号检测</span>
    <span class="chip">文本痕迹 · 时间行为 · 账号行为 · 评分异常 · 图文一致性</span>
    <span class="purify-sub">阈值 观察≥{cfg.get('watch_threshold')}／高风险≥{cfg.get('high_threshold')} · 净化后重算口碑与性价比</span>
  </div>
  <div class="pgrid">{''.join(cards)}</div>
  <div class="delta">净化前后对比：基线性价比 <b>{before:.2f}</b> →
    净化后 <b>{after:.2f}</b>
    <span class="{cls}">{arrow} {abs(delta):.1f}%</span>
    <span class="chip">评论质量 {base.get('评论质量', 0):.3f} → {d.get('评论质量', 0):.3f}</span>
    <span class="chip">情感得分 {base.get('情感得分', 0):.3f} → {d.get('情感得分', 0):.3f}</span>
  </div>
  {risk_block}
</div>"""

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>__NAME__ | 春城金鉴榜 · __DIST__</title>
<script src="__ECHARTS__"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{min-height:100vh;background:radial-gradient(circle at 20% 30%,#0a0f2a,#030617);display:flex;align-items:center;justify-content:center;font-family:'Poppins','Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;padding:24px;position:relative;overflow-x:hidden}
.particle-bg{position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;background-image:radial-gradient(2px 2px at 20% 40%,rgba(255,200,100,.25),rgba(0,0,0,0)),radial-gradient(3px 3px at 80% 70%,rgba(100,180,255,.3),rgba(0,0,0,0)),radial-gradient(1px 1px at 40% 90%,rgba(255,120,80,.4),rgba(0,0,0,0));background-repeat:no-repeat;background-size:200px 200px,300px 300px,150px 150px;animation:floatParticles 18s infinite alternate}
@keyframes floatParticles{0%{opacity:.5;transform:scale(1) translateY(0)}100%{opacity:1;transform:scale(1.08) translateY(-20px)}}
.glass-card{max-width:1100px;width:100%;background:rgba(12,20,35,.65);backdrop-filter:blur(14px);border-radius:64px;border:1px solid rgba(255,255,255,.25);box-shadow:0 30px 50px rgba(0,0,0,.5),0 0 0 .5px rgba(255,255,255,.1) inset,0 0 20px rgba(0,255,255,.2);transition:transform .3s ease,box-shadow .4s ease;z-index:10;overflow:hidden;animation:cardGlow 4s infinite alternate;position:relative}
@keyframes cardGlow{0%{box-shadow:0 30px 50px rgba(0,0,0,.5),0 0 0 .5px rgba(255,255,255,.1) inset,0 0 15px rgba(0,255,255,.15);border-color:rgba(255,255,200,.2)}100%{box-shadow:0 35px 65px rgba(0,0,0,.7),0 0 0 1px rgba(255,220,150,.4) inset,0 0 35px rgba(0,210,255,.4);border-color:rgba(255,200,100,.5)}}
.glass-card:hover{transform:translateY(-5px) scale(1.01)}
.rank-ribbon{position:absolute;top:0;right:0;background:linear-gradient(135deg,#FFB347,#FF7A18);color:#231000;font-weight:800;padding:10px 26px 10px 34px;border-bottom-left-radius:28px;font-size:.95rem;letter-spacing:1px;z-index:5;box-shadow:0 6px 18px rgba(255,120,20,.4)}
.hotel-header{padding:28px 32px 20px 32px;position:relative;background:linear-gradient(135deg,rgba(255,255,245,.08) 0%,rgba(20,30,55,.4) 100%);border-bottom:1px solid rgba(255,215,150,.3)}
.hotel-name{font-size:2rem;font-weight:700;background:linear-gradient(135deg,#FFE6B0,#FFB347,#7DF9FF);background-clip:text;-webkit-background-clip:text;color:transparent;display:flex;align-items:baseline;flex-wrap:wrap;gap:12px;line-height:1.25}
.star-badge{font-size:.75rem;background:rgba(255,180,70,.25);backdrop-filter:blur(4px);padding:5px 14px;border-radius:60px;color:#FFDD99;font-weight:600;border:1px solid rgba(255,200,100,.6);letter-spacing:1px}
.address-info{font-size:.85rem;color:#B9D0F0;margin-top:12px;display:flex;flex-wrap:wrap;gap:18px;font-weight:400}
.price-highlight{margin-top:18px;background:linear-gradient(95deg,rgba(0,20,40,.7),rgba(255,140,50,.2));backdrop-filter:blur(8px);display:inline-flex;align-items:baseline;gap:12px;padding:8px 24px;border-radius:60px;font-weight:700;color:#FFD966;font-size:1rem;border:1px solid rgba(255,170,80,.6);box-shadow:0 0 12px rgba(255,100,0,.3)}
.price-highlight strong{font-size:1.7rem;color:#FFAA44;margin-right:6px;text-shadow:0 0 5px #ff9f2e}
.price-pending{color:#9fd8ff;border-color:rgba(120,200,255,.5);box-shadow:none;background:linear-gradient(95deg,rgba(0,20,40,.7),rgba(40,120,200,.18));font-weight:500}
.dashboard{display:flex;flex-wrap:wrap;gap:20px;padding:20px 24px 10px 24px}
.radar-wrapper{flex:1.4;min-width:260px;background:rgba(0,0,0,.2);border-radius:48px;backdrop-filter:blur(4px);padding:8px}
.carousel-wrapper{flex:.9;min-width:240px;background:rgba(0,0,0,.25);border-radius:48px;backdrop-filter:blur(8px);padding:16px 12px;display:flex;flex-direction:column;align-items:center;justify-content:center;border:1px solid rgba(255,215,150,.3);box-shadow:0 8px 20px rgba(0,0,0,.3)}
.carousel-title{font-size:1rem;font-weight:600;color:#FFE3AA;margin-bottom:15px;letter-spacing:1px;background:rgba(0,0,0,.4);padding:4px 16px;border-radius:40px}
.image-frame{width:100%;aspect-ratio:4/3;border-radius:32px;overflow:hidden;box-shadow:0 12px 28px rgba(0,0,0,.5),0 0 0 2px rgba(255,200,100,.3);background:#00000055;position:relative}
.image-frame img{width:100%;height:100%;object-fit:cover;opacity:1;transition:opacity .45s ease,transform .6s ease;animation:kenburns 18s ease-in-out infinite alternate;cursor:zoom-in}
@keyframes kenburns{0%{transform:scale(1) translate(0,0)}100%{transform:scale(1.09) translate(-1.5%,-1.5%)}}
.img-nav{position:absolute;top:50%;transform:translateY(-50%);width:38px;height:38px;padding:0;border-radius:50%;border:1px solid rgba(255,215,150,.45);background:rgba(0,0,0,.5);color:#FFE3AA;font-size:1.4rem;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;opacity:0;transition:opacity .25s,background .25s;z-index:3}
.image-frame:hover .img-nav{opacity:1}
.img-nav:hover{background:rgba(255,180,70,.4)}
.img-nav.prev{left:10px}.img-nav.next{right:10px}
.img-idx{position:absolute;right:12px;bottom:10px;font-size:.7rem;color:#FFE3AA;background:rgba(0,0,0,.6);padding:3px 11px;border-radius:20px;letter-spacing:.5px;z-index:3}
.thumbs{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px;width:100%;justify-content:center}
.thumbs img{width:52px;height:38px;object-fit:cover;border-radius:10px;cursor:pointer;opacity:.5;border:2px solid transparent;transition:opacity .2s,border-color .2s,transform .2s;flex:0 0 auto;background:#0006}
.thumbs img:hover{opacity:.85;transform:translateY(-2px)}
/* ===== 评论净化区块 ===== */
.purify{margin-top:26px;background:linear-gradient(180deg,rgba(8,20,38,.86),rgba(6,14,28,.86));border:1px solid rgba(120,200,255,.28);border-radius:26px;padding:22px 24px}
.purify-head{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:16px}
.purify-title{font-size:1.06rem;font-weight:700;color:#BDEEFF;letter-spacing:.5px}
.purify-sub{font-size:.72rem;color:#7f9dc4}
.dot-live{width:8px;height:8px;border-radius:50%;background:#37d67a;box-shadow:0 0 8px #37d67a;display:inline-block}
.pgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.pcard{background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.10);border-radius:16px;padding:12px 14px}
.pcard .pk{font-size:.68rem;color:#8fb0d6;letter-spacing:.4px}
.pcard .pv{font-size:1.22rem;font-weight:800;color:#FFE0A6;margin-top:5px}
.pcard .pv small{font-size:.66rem;color:#8fb0d6;font-weight:400}
.pcard .pd{font-size:.64rem;color:#6f8db3;margin-top:4px}
.pcard.good .pv{color:#7ef2b0}
.pcard.warn .pv{color:#ffb4a2}
.delta{margin-top:14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:.78rem;color:#A9C6E8}
.delta b{color:#FFD966}
.chip{display:inline-flex;align-items:center;gap:5px;font-size:.68rem;padding:3px 10px;border-radius:20px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.13);color:#cfe3fa}
.chip.red{background:rgba(230,70,70,.16);border-color:rgba(255,120,120,.42);color:#ffc9c2}
.chip.amber{background:rgba(235,160,40,.16);border-color:rgba(255,190,90,.42);color:#ffe0ab}
.chip.blue{background:rgba(60,150,240,.16);border-color:rgba(110,190,255,.42);color:#c9e6ff}
.risk-list{margin-top:16px;border-top:1px dashed rgba(255,255,255,.14);padding-top:14px}
.risk-list h4{font-size:.82rem;color:#FFC9A8;margin-bottom:10px;font-weight:700}
.risk-item{background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.09);border-left:3px solid #E24B4A;border-radius:12px;padding:10px 13px;margin-bottom:9px}
.risk-item.watch{border-left-color:#EF9F27}
.risk-top{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:.7rem;color:#9db8dc;margin-bottom:6px}
.risk-score{font-weight:800;color:#ff9b8a}
.risk-item.watch .risk-score{color:#ffce7a}
.risk-body{font-size:.8rem;color:#dce9f7;line-height:1.6}
.risk-ev{margin-top:7px;display:flex;gap:6px;flex-wrap:wrap}
.ev-tag{font-size:.63rem;padding:2px 8px;border-radius:14px;background:rgba(255,120,90,.14);border:1px solid rgba(255,140,110,.34);color:#ffcfc0}
.risk-more{margin-top:8px;font-size:.7rem;color:#7f9dc4;text-align:center}
.metric .sub{font-size:.62rem;color:#7f9dc4;margin-top:3px}
.cthumb-badge{position:absolute;left:10px;top:10px;font-size:.62rem;padding:2px 8px;border-radius:12px;background:rgba(0,0,0,.55);border:1px solid rgba(255,255,255,.2);color:#ffe0ab}
.cmeta .up{color:#7ef2b0;font-weight:700}
.cmeta .down{color:#ff9b8a;font-weight:700}
.thumbs img:hover{opacity:.85;transform:translateY(-2px)}
.thumbs img.on{opacity:1;border-color:#FFD966;box-shadow:0 0 8px rgba(255,215,120,.6)}
.lightbox{position:fixed;inset:0;background:rgba(2,4,12,.94);display:none;align-items:center;justify-content:center;z-index:99;cursor:zoom-out;backdrop-filter:blur(6px)}
.lightbox.on{display:flex}
.lightbox img{max-width:92vw;max-height:88vh;border-radius:18px;box-shadow:0 0 40px rgba(255,180,80,.35)}
.lightbox .lb-cap{position:absolute;bottom:22px;color:#FFE3AA;font-size:.8rem;background:rgba(0,0,0,.5);padding:5px 16px;border-radius:30px}
.image-caption{margin-top:12px;font-size:.75rem;color:#CCDDFF;background:rgba(0,0,0,.5);padding:5px 14px;border-radius:60px;text-align:center}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;padding:6px 32px 4px}
.metric{background:rgba(0,0,0,.28);border:1px solid rgba(255,215,150,.18);border-radius:22px;padding:12px 16px}
.metric .k{font-size:.72rem;color:#9db8dc;letter-spacing:.5px}
.metric .v{font-size:1.25rem;font-weight:700;color:#FFD98A;margin-top:4px}
.metric .v small{font-size:.7rem;color:#8fb6e0;font-weight:400;margin-left:4px}
.review-summary{padding:16px 32px 24px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:15px;font-size:.85rem;border-top:1px solid rgba(255,215,140,.2);background:rgba(0,0,0,.2);margin-top:16px}
.quote{background:rgba(0,255,255,.08);padding:8px 20px;border-radius:40px;color:#C0FFEE;font-weight:500;border-left:3px solid #0ff}
.room-type{background:rgba(255,180,60,.12);padding:8px 20px;border-radius:40px;color:#FFDEAD;font-weight:500}
.tag-row{display:flex;flex-wrap:wrap;gap:10px;padding:0 32px}
.tag{font-size:.75rem;background:rgba(120,200,255,.12);border:1px solid rgba(120,200,255,.35);color:#BFE3FF;padding:5px 14px;border-radius:40px}
.footer-note{background:rgba(0,0,0,.4);padding:12px 28px 18px;font-size:.7rem;color:#8db3e0;text-align:center;border-top:1px solid rgba(255,200,100,.15);letter-spacing:.3px;line-height:1.9}
.footer-note b{color:#FFD98A}
.back-link{display:inline-block;margin-top:10px;color:#9fd8ff;text-decoration:none;border-bottom:1px dashed rgba(159,216,255,.5);font-size:.72rem}
@media(max-width:800px){.dashboard{flex-direction:column}.hotel-name{font-size:1.5rem}.price-highlight strong{font-size:1.3rem}.radar-wrapper,.carousel-wrapper{min-width:auto}.glass-card{border-radius:36px}.rank-ribbon{font-size:.8rem;padding:8px 18px 8px 26px}}
</style>
</head>
<body>
<div class="particle-bg"></div>
<div class="glass-card">
  <div class="rank-ribbon">__DIST__ 第 __RANK__ 名</div>
  <div class="hotel-header">
    <div class="hotel-name">__NAME__ <span class="star-badge">__STAR__</span></div>
    <div class="address-info">
      <span>📍 __ADDR__</span>
      <span>🏬 __BIZAREA__</span>
      <span>🏆 __COMMENTS__条点评 · __SCOREDESC__</span>
    </div>
    __PRICEBLOCK__
  </div>
  <div class="dashboard">
    <div class="radar-wrapper"><div id="radarChart" style="width:100%;height:420px"></div></div>
    <div class="carousel-wrapper">
      <div class="carousel-title">🏨 酒店影像 <span id="imgCount"></span></div>
      <div class="image-frame">
        <img id="hotelImage" src="__IMG__" alt="酒店实拍" referrerpolicy="no-referrer">
        <button class="img-nav prev" id="imgPrev" type="button" aria-label="上一张">‹</button>
        <button class="img-nav next" id="imgNext" type="button" aria-label="下一张">›</button>
        <div class="img-idx" id="imgIdx">1 / 1</div>
      </div>
      <div class="thumbs" id="thumbs"></div>
      <div class="image-caption">✨ __IMGCAP__</div>
    </div>
  </div>
  <div class="metrics">
    <div class="metric"><div class="k">综合口碑分</div><div class="v">__SCORE__<small>/5</small></div></div>
    <div class="metric"><div class="k">卫生 / 设施</div><div class="v">__HY__<small>/</small>__FA__</div></div>
    <div class="metric"><div class="k">环境 / 服务</div><div class="v">__EN__<small>/</small>__SE__</div></div>
    <div class="metric"><div class="k">评论数</div><div class="v">__COMMENTS__<small>条</small></div></div>
    <div class="metric"><div class="k">榜单得分</div><div class="v">__RANKSCORE__</div></div>
  </div>
  __PURIFYBLOCK__
  <div class="review-summary">
    <span class="quote">⭐ __QUOTE__</span>
    <span class="room-type">🛏️ 热销房型：__ROOM__</span>
  </div>
  <div class="tag-row">__TAGS__</div>
  <div class="footer-note">
    💎 榜单口径：<b>__RANKRULE__</b><br>
    📌 资助项目：云南大学大学生创新训练项目资助（校级，项目编号：20257073）· 滇评鉴真·智能评论净化系统<br>
    🗺️ 区域归属：按经纬度与昆明市行政区边界判定 · 生成于 __DATE__
    <br><a class="back-link" href="index.html">← 返回「春城金鉴榜」总榜</a>
  </div>
</div>
<script>
(function(){
  var R = __RADAR__;
  var dom = document.getElementById('radarChart');
  if(!dom) return;
  function boot(){
  var myChart = echarts.init(dom);
  var option = {
    title:{show:true,text:"✨ 多维实力 动态透视 ✨",left:"center",top:8,
      textStyle:{fontSize:16,fontWeight:'bold',color:'#FFE5B4',textShadow:'0 0 8px #ff8c00, 0 0 2px cyan'},
      subtext:"__SUBTEXT__",subtextStyle:{fontSize:10,color:'#aad0ff'}},
    tooltip:{trigger:'item',backgroundColor:'rgba(0,10,25,.85)',borderColor:'#ffaa55',borderWidth:1.5,
      textStyle:{color:'#FFECB3',fontSize:12},formatter:function(p){return p.value?('⚡ '+p.name+'<br/>▶ 得分: '+p.value+' / 5.0'):p.name;}},
    legend:{data:['__LEGEND__'],orient:'horizontal',left:'left',top:55,icon:'roundRect',
      textStyle:{color:'#E0F0FF',fontWeight:'bold',fontSize:12},backgroundColor:'rgba(0,0,0,.3)',borderRadius:20,padding:[4,12,4,12]},
    radar:{indicator:R.indicator,shape:'circle',center:['50%','54%'],radius:'62%',
      name:{textStyle:{fontSize:12,fontWeight:'600',color:'#FFE4B5',backgroundColor:'rgba(0,10,30,.6)',borderRadius:20,padding:[2,8,2,8],borderColor:'#ffaa66',borderWidth:.5}},
      splitArea:{areaStyle:{color:['rgba(0,200,255,.05)','rgba(0,120,210,.08)','rgba(0,70,150,.12)']}},
      axisLine:{lineStyle:{color:'#2f80ed',width:1,type:'dashed'}},
      splitLine:{lineStyle:{color:'#38bdf8',width:1,type:'dotted'}}},
    series:[{name:'综合评分 (满分5)',type:'radar',data:[{value:R.values,name:'__LEGEND__',
      areaStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,[{offset:0,color:'rgba(255,100,50,.6)'},{offset:1,color:'rgba(0,200,255,.25)'}])},
      lineStyle:{color:'#FFCC77',width:3,shadowBlur:12,shadowColor:'#FFAA33'},
      itemStyle:{color:'#FFD966',borderColor:'#fff',borderWidth:2,shadowBlur:12,shadowColor:'#ffaa44'},
      symbolSize:9,symbol:'diamond'}],animation:true,animationDuration:1800}],
    backgroundColor:'transparent'};
  myChart.setOption(option);
  window.addEventListener('resize',function(){myChart.resize();});
  }
  /* 本地 echarts 取不到时（如某些预览环境限制相对路径）自动回落 CDN */
  if(window.echarts){ boot(); return; }
  var _es=document.createElement('script');
  _es.src='https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js';
  _es.onload=boot;
  _es.onerror=function(){ if(dom) dom.innerHTML='<div style="color:#9db8dc;padding:40px 0;text-align:center">图表库未能加载</div>'; };
  document.head.appendChild(_es);
})();

/* ===== 酒店相册轮播（本地图片，多图淡入切换 + 缩略图 + 放大查看） ===== */
(function(){
  var IMAGES = __IMGLIST__;
  var img   = document.getElementById('hotelImage');
  var thumbs= document.getElementById('thumbs');
  var idxEl = document.getElementById('imgIdx');
  var cntEl = document.getElementById('imgCount');
  var lb    = document.getElementById('lightbox');
  var lbImg = document.getElementById('lbImg');
  var lbCap = document.getElementById('lbCap');
  if(!img) return;
  if(!IMAGES || !IMAGES.length){ if(cntEl) cntEl.textContent=''; return; }

  cntEl.textContent = '共 ' + IMAGES.length + ' 张';
  IMAGES.forEach(function(src,k){
    var t=document.createElement('img');
    t.src=src; t.alt='图 '+(k+1); t.loading='lazy';
    t.addEventListener('click',function(){ go(k); });
    thumbs.appendChild(t);
  });
  var ts = Array.prototype.slice.call(thumbs.children);
  var cur = 0, timer = null, DUR = 3800;

  function paint(i){
    cur = (i + IMAGES.length) % IMAGES.length;
    img.style.opacity = '0';
    img.style.animation = 'none';
    window.setTimeout(function(){
      img.src = IMAGES[cur];
      img.onload = function(){
        img.style.opacity = '1';
        img.style.animation = '';
        img.style.animationName = 'kenburns';
        img.style.animationDuration = '18s';
        img.style.animationIterationCount = 'infinite';
        img.style.animationDirection = 'alternate';
        img.style.animationTimingFunction = 'ease-in-out';
      };
    }, 180);
    ts.forEach(function(t,k){ t.classList.toggle('on', k === cur); });
    idxEl.textContent = (cur + 1) + ' / ' + IMAGES.length;
    if(ts[cur] && thumbs.scrollWidth > thumbs.clientWidth + 4){
      ts[cur].scrollIntoView({behavior:'smooth', block:'nearest', inline:'center'});
    }
  }
  function go(i){ paint(i); start(); }
  function start(){ stop(); timer = window.setInterval(function(){ paint(cur + 1); }, DUR); }
  function stop(){ if(timer){ window.clearInterval(timer); timer = null; } }

  document.getElementById('imgNext').addEventListener('click', function(e){ e.stopPropagation(); go(cur + 1); });
  document.getElementById('imgPrev').addEventListener('click', function(e){ e.stopPropagation(); go(cur - 1); });

  var wrap = document.querySelector('.carousel-wrapper');
  wrap.addEventListener('mouseenter', stop);
  wrap.addEventListener('mouseleave', start);
  var x0 = null;
  wrap.addEventListener('touchstart', function(e){ x0 = e.touches[0].clientX; }, {passive:true});
  wrap.addEventListener('touchend', function(e){
    if(x0 === null) return;
    var dx = e.changedTouches[0].clientX - x0;
    if(Math.abs(dx) > 40){ dx < 0 ? go(cur + 1) : go(cur - 1); }
    x0 = null;
  }, {passive:true});

  img.addEventListener('click', function(){
    if(!lb) return;
    lbImg.src = IMAGES[cur];
    lbCap.textContent = '图 ' + (cur + 1) + ' / ' + IMAGES.length + '　（点击任意处关闭）';
    lb.classList.add('on');
  });
  if(lb) lb.addEventListener('click', function(){ lb.classList.remove('on'); });
  document.addEventListener('keydown', function(e){
    if(e.key === 'Escape' && lb) lb.classList.remove('on');
    if(e.key === 'ArrowRight') go(cur + 1);
    if(e.key === 'ArrowLeft')  go(cur - 1);
  });

  ts[0].classList.add('on');
  idxEl.textContent = '1 / ' + IMAGES.length;
  start();
})();
</script>
<div class="lightbox" id="lightbox">
  <img id="lbImg" src="" alt="放大查看">
  <div class="lb-cap" id="lbCap"></div>
</div>
</body>
</html>
"""


def star_text(s):
    m = {0: "经济/民宿", 1: "舒适1星", 2: "舒适2星", 3: "高档3星",
         4: "豪华4星", 5: "奢华5星"}
    return "✦ " + m.get(s, f"{s}星") + " ✦"


def build_radar(h, price):
    """返回雷达图指标与数值。有价格→启用「价格优势」；无价格→替换为「口碑热度」"""
    ind = [{"name": "🧼 卫生", "max": 5}, {"name": "🛋️ 设施", "max": 5},
           {"name": "🌿 环境", "max": 5}, {"name": "🤝 服务", "max": 5}]
    val = [h["卫生"], h["设施"], h["环境"], h["服务"]]
    if price:
        # 价格优势：同区候选池内越低越有优势，映射到 3.0~5.0 区间，避免拉爆雷达
        scores = [c["价格"] for d in CAND.values() for c in d if c.get("价格")]
        if scores:
            lo, hi = min(scores), max(scores)
            pa = 5.0 if hi == lo else 5.0 - 2.0 * (price - lo) / (hi - lo)
        else:
            pa = 4.5
        ind.append({"name": "💰 价格优势", "max": 5})
        val.append(round(pa, 2))
    else:
        n = h["评论数"]
        hot = min(5.0, 3.0 + 2.0 * min(1.0, math.log10(max(n, 1)) / math.log10(8000)))
        ind.append({"name": "🔥 口碑热度", "max": 5})
        val.append(round(hot, 2))
    return json.dumps({"indicator": ind, "values": val}, ensure_ascii=False)


def render(h, dist, rank, date_str, img_src, img_cap, img_list=None):
    img_list = img_list or [img_src]
    price = h.get("价格")
    if price:
        pb = (f'<div class="price-highlight">💎 榜单参考价 <strong>¥{float(price):.0f}</strong> /晚起'
              f'&nbsp;<span style="font-size:.75rem;opacity:.8">（数据来源：携程，采集于 {date_str}）</span></div>')
    else:
        pb = ('<div class="price-highlight price-pending">💎 价格数据待接入 '
              '&nbsp;<span style="font-size:.75rem">（本版按口碑维度排序，价格到位后自动切换为性价比榜）</span></div>')

    tags = "".join(
        f'<span class="tag">{html.escape(t)}</span>'
        for t in [h["所属商圈"], h["位置描述"], h["床型描述"]]
        if t and str(t).strip())

    rule = ("性价比指数 =（评论质量 × 情感得分 × 设施得分）× 时间衰减 × 价格弹性 ÷ 价格；"
            "评论质量仅统计**净化后保留**的评论并按清洗权重加权，再经贝叶斯收缩；"
            "时间衰减 e^(−λΔt) 用真实评论日期计算，价格弹性 (P/P̄)^θ 以区内中位价为基准"
            ) if price else \
           "口碑综合分 = 总评分×40% + 卫生/设施/环境/服务×15%（AHP 权重），评论数经贝叶斯收缩加权"

    # 后端净化结果优先：名次与得分改用净化后的口径
    rd = R_HOTELS.get(str(h.get("酒店ID"))) or {}
    shown_rank = rd.get("排名") or rank
    shown_score = rd.get("性价比指数") if rd else h.get("性价比指数")
    if isinstance(shown_score, (int, float)):
        shown_score = f"{float(shown_score):.2f}"
    sub = (f"净化后性价比 {shown_score} · 评论 {h['评论数']} 条 · 携程参考价 ¥{float(price):.0f}"
           f" · 净化率 {rd.get('净化率', 0)*100:.1f}%" if (price and rd) else
           (f"榜单得分 {h['信赖质量分']} · 评论 {h['评论数']} 条 · 携程参考价 ¥{price}"
            if price else
            f"榜单得分 {h['信赖质量分']} · 评论 {h['评论数']} 条 · 情感极性 {h['情感得分']}"))

    rep = {
        "__NAME__": html.escape(h["酒店名称"]),
        "__DIST__": dist, "__RANK__": str(shown_rank),
        "__STAR__": star_text(h["星级"]),
        "__ADDR__": html.escape(str(h.get("详细地址") or "—")),
        "__BIZAREA__": html.escape(str(h.get("所属商圈") or "—")),
        "__COMMENTS__": str(h["评论数"]),
        "__SCOREDESC__": html.escape(str(h.get("评分描述") or "")),
        "__PRICEBLOCK__": pb,
        "__IMG__": img_src,
        "__IMGLIST__": json.dumps(img_list, ensure_ascii=False),
        "__IMGCAP__": img_cap,
        "__SCORE__": str(h["评分"]), "__HY__": str(h["卫生"]), "__FA__": str(h["设施"]),
        "__EN__": str(h["环境"]), "__SE__": str(h["服务"]),
        "__RANKSCORE__": str(shown_score if shown_score is not None else h["信赖质量分"]),
        "__ECHARTS__": ECHARTS_SRC if ECHARTS_SRC.startswith("http") else "../" + ECHARTS_SRC,
        "__QUOTE__": html.escape(str(h.get("一句话点评") or "—")),
        "__ROOM__": html.escape(str(h.get("入住房型") or "—")),
        "__TAGS__": tags,
        "__RANKRULE__": rule,
        "__RADAR__": build_radar(h, price),
        "__SUBTEXT__": sub,
        "__LEGEND__": html.escape(h["酒店名称"][:20]),
        "__DATE__": date_str,
        "__PURIFYBLOCK__": build_purify(h, h.get("酒店ID")),
    }
    out = TEMPLATE
    for k, v in rep.items():
        out = out.replace(k, v)
    return out


def main():
    global ECHARTS_SRC
    date_str = "2026-10-14"
    # 重建前保留已下载的相册图片（output/images/），其余清空
    if os.path.isdir(OUT):
        for name in os.listdir(OUT):
            if name == "images":
                continue
            p = os.path.join(OUT, name)
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
    os.makedirs(OUT, exist_ok=True)
    if DOWNLOAD_IMAGES:
        os.makedirs(IMG_DIR, exist_ok=True)
    # ECharts 本地化：离线可打开（结项提交更稳妥）
    if fetch_image(ECHARTS_CDN, os.path.join(OUT, "echarts.min.js")) or \
            (os.path.exists(os.path.join(OUT, "echarts.min.js"))
             and os.path.getsize(os.path.join(OUT, "echarts.min.js")) > 100000):
        ECHARTS_SRC = "echarts.min.js"
        print("ECharts 已本地化 → output/echarts.min.js")
    else:
        print("⚠ ECharts 本地化失败，回退 CDN（页面需联网）")

    index_rows = []
    total = 0
    for dist in DISTRICTS:
        cands = CAND.get(dist, [])[:TOP_N]
        old_order = {str(h["酒店ID"]): i for i, h in enumerate(cands, 1)}
        # 若后端已给出净化后名次，按净化后的性价比重排并回填分数
        rk = R_RANK.get(dist) or []
        if rk:
            order = {str(x["酒店ID"]): x for x in rk}
            ranked = [h for h in cands if str(h["酒店ID"]) in order]
            ranked.sort(key=lambda h: order[str(h["酒店ID"])]["排名"])
            if ranked:
                cands = ranked
                for h in cands:
                    x = order[str(h["酒店ID"])]
                    h["价格"] = x.get("价格") or h.get("价格")
                    h["性价比指数"] = x.get("性价比指数")
                    h["_基线性价比"] = x.get("基线性价比")
                    h["_净化率"] = x.get("净化率")
                    h["_高风险数"] = x.get("高风险数")
                    h["_名次变动"] = old_order.get(str(h["酒店ID"]), x["排名"]) - x["排名"]
        if not cands:
            continue
        d_dir = os.path.join(OUT, dist)
        os.makedirs(d_dir, exist_ok=True)
        cards = []
        for i, h in enumerate(cands, 1):
            fn = f"{dist}_{i:02d}_{h['酒店ID']}.html"
            hid = str(h["酒店ID"])
            # ① 优先用本地相册（每店多图）
            alb_dir = os.path.join(IMG_DIR, hid)
            list_src = []
            if os.path.isdir(alb_dir):
                files = [x for x in sorted(os.listdir(alb_dir))
                         if x.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
                if EMBED_IMAGES:
                    list_src = [u for u in (data_uri(os.path.join(alb_dir, x))
                                            for x in files) if u]
                else:
                    list_src = [f"../images/{hid}/{x}" for x in files]
            remote = h.get("首图URL") or ""
            local_name = f"{hid}.jpg"
            if list_src:
                img_src = list_src[0]
                img_cap = f"📸 酒店实景相册 · 共 {len(list_src)} 张 · 来源携程（本地内嵌）"
            else:
                # ② 退回单张首图
                img_src, img_cap = remote, "🏨 酒店首图 · 来源携程"
                if DOWNLOAD_IMAGES and remote:
                    dest = os.path.join(IMG_DIR, local_name)
                    if fetch_image(remote, dest):
                        img_src = (data_uri(dest, COVER_MAX_W, COVER_QUALITY)
                                   if EMBED_IMAGES else f"../images/{local_name}")
                        img_cap = "🏨 酒店首图 · 来源携程（已本地存档）"
                    else:
                        img_cap = "🏨 酒店首图 · 来源携程（远程加载）"
                if img_src:
                    list_src = [img_src]
                else:
                    img_cap = "暂无图片"

            if os.path.isdir(alb_dir):
                _cov = [x for x in sorted(os.listdir(alb_dir))
                        if x.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
                if _cov:
                    cover_uri = (data_uri(os.path.join(alb_dir, _cov[0]),
                                          COVER_MAX_W, COVER_QUALITY)
                                 if EMBED_IMAGES else f"images/{hid}/{_cov[0]}")
                else:
                    cover_uri = ""
            else:
                _single = os.path.join(IMG_DIR, local_name)
                cover_uri = (data_uri(_single, COVER_MAX_W, COVER_QUALITY)
                             if (EMBED_IMAGES and os.path.exists(_single))
                             else (f"images/{local_name}" if os.path.exists(_single) else ""))

            open(os.path.join(d_dir, fn), "w", encoding="utf-8").write(
                render(h, dist, i, date_str, img_src, img_cap, list_src))
            total += 1
            if h.get("价格"):
                edge = f'¥{float(h["价格"]):.0f} · 性价比 {float(h["性价比指数"]):.2f}'
            else:
                edge = f'口碑 {h["信赖质量分"]}'
            # 净化信息：徽标 + 名次变动
            badge = ""
            if h.get("_净化率") is not None:
                badge = (f'<span class="cthumb-badge">净化 {h["_净化率"]*100:.1f}%'
                         + (f' · 剔除{h["_高风险数"]}' if h.get("_高风险数") else "")
                         + '</span>')
            mv = h.get("_名次变动")
            if mv:
                arrow = "▲" if mv > 0 else "▼"
                cls = "up" if mv > 0 else "down"
                edge += f' <span class="{cls}">{arrow}{abs(mv)}</span>'
            cards.append(
                f'<a class="card" href="{dist}/{fn}">'
                f'<img class="cthumb" src="{cover_uri}" alt="" loading="lazy" '
                f'onerror="this.style.display=\'none\'">'
                f'{badge}'
                f'<div class="cbody">'
                f'<div class="crank">No.{i}</div>'
                f'<div class="cname">{html.escape(h["酒店名称"])}</div>'
                f'<div class="cmeta">{star_text(h["星级"])} · {h["评论数"]}条点评 · '
                f'{edge}</div>'
                f'</div>'
                f'<div class="cscore">🏆 {h["评分"]}<span>/5</span></div>'
                f'</a>')
        index_rows.append((dist, cards))

    cards_html = ""
    for dist, cards in index_rows:
        cards_html += (f'<section><h2>🏙️ {dist}'
                       f'<span class="cnt">TOP {len(cards)}</span></h2>'
                       f'<div class="grid">{"".join(cards)}</div></section>')

    has_price = any(h.get("价格") for d in CAND.values() for h in d[:TOP_N])
    index = (INDEX_TPL.replace("__CARDS__", cards_html)
             .replace("__DATE__", date_str)
             .replace("__MODE__", "完整性价比榜（含价格维度）" if has_price
                      else "口碑综合榜（价格待接入）")
             .replace("__RULE__",
                      "性价比指数 =（评论质量 × 情感得分 × 设施得分）× 时间衰减 × 价格弹性 ÷ 价格；"
                      "评论数经贝叶斯收缩加权；时间衰减与价格弹性因数据源无评论时间戳／区域均价，"
                      "本期取中性值 1（已在结项报告中如实说明）"
                      if has_price else
                      "口碑综合分 = 总评分×40% + 卫生/设施/环境/服务×15%（AHP 权重），"
                      "评论数经贝叶斯收缩加权（C=30）。<br>申请书中「动态性价比算法」所需的价格、"
                      "评论时间戳、区域均价等字段在本期数据源中缺失，价格接入后将切换为完整性价比榜单。"))
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(index)
    print(f"已生成 {total} 个单店页 + 1 个总榜页 → {OUT}")
    for dist, cards in index_rows:
        print(f"  {dist}: {len(cards)} 页")


INDEX_TPL = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>春城金鉴榜 · 昆明分区酒店榜单</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:radial-gradient(circle at 20% 10%,#0a0f2a,#030617 70%);min-height:100vh;font-family:'PingFang SC','Microsoft YaHei','Segoe UI',sans-serif;color:#dce9ff;padding:48px 28px 80px}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:2.6rem;font-weight:800;background:linear-gradient(135deg,#FFE6B0,#FFB347,#7DF9FF);-webkit-background-clip:text;background-clip:text;color:transparent;text-align:center;letter-spacing:2px}
.sub{text-align:center;color:#8fb6e0;margin-top:14px;font-size:.9rem;line-height:1.9}
h2{font-size:1.35rem;margin:44px 0 18px;color:#FFE3AA;display:flex;align-items:center;gap:12px;border-left:4px solid #FFB347;padding-left:14px}
.cnt{font-size:.72rem;background:rgba(255,180,70,.18);border:1px solid rgba(255,200,100,.5);color:#FFDD99;padding:3px 12px;border-radius:40px;font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:16px}
.card{display:flex;gap:15px;align-items:center;text-decoration:none;background:rgba(12,20,35,.7);border:1px solid rgba(255,255,255,.14);border-radius:26px;padding:16px 18px;transition:all .28s ease;position:relative;overflow:hidden}
.card:hover{transform:translateY(-4px);border-color:rgba(255,200,100,.55);box-shadow:0 18px 38px rgba(0,0,0,.5),0 0 22px rgba(0,200,255,.18)}
.cthumb{width:118px;height:92px;border-radius:18px;object-fit:cover;flex:0 0 auto;border:1px solid rgba(255,215,150,.28);box-shadow:0 8px 18px rgba(0,0,0,.5);background:#0a1424}
.cthumb-badge{position:absolute;left:12px;top:12px;z-index:2;font-size:.6rem;padding:2px 8px;border-radius:12px;background:rgba(0,0,0,.62);border:1px solid rgba(120,220,255,.4);color:#a8e8ff;letter-spacing:.2px}
.cmeta .up{color:#7ef2b0;font-weight:700}
.cmeta .down{color:#ff9b8a;font-weight:700}
.cbody{flex:1;min-width:0;padding-right:56px}
.crank{font-size:.72rem;color:#7DF9FF;font-weight:700;letter-spacing:1px}
.cname{font-size:1.02rem;font-weight:700;color:#FFE6B0;margin:6px 0 9px;line-height:1.4}
.cmeta{font-size:.74rem;color:#9db8dc;line-height:1.5}
.cscore{position:absolute;top:16px;right:18px;font-size:1.4rem;font-weight:800;color:#FFB347}
.cscore span{font-size:.68rem;color:#8fb6e0;font-weight:400}
.foot{margin-top:56px;text-align:center;font-size:.72rem;color:#7f9dc4;line-height:2}
.foot b{color:#FFD98A}
</style></head><body><div class="wrap">
<h1>🏮 春城金鉴榜</h1>
<div class="sub">昆明分区酒店榜单 · 滇评鉴真·智能评论净化系统<br>
区域归属按经纬度与昆明市行政区边界判定，每区取前 5 名 · <b>本版口径：__MODE__</b></div>
__CARDS__
<div class="foot">
📌 资助项目：云南大学大学生创新训练项目资助（校级，项目编号：20257073）· 滇评鉴真·智能评论净化系统<br>
📊 数据来源：携程公开酒店信息（评分、点评数、分项评分、地理位置）· 生成于 __DATE__<br>
<b>榜单口径：</b>__RULE__
</div>
</div></body></html>
"""

if __name__ == "__main__":
    main()
