# -*- coding: utf-8 -*-
"""
采集榜单酒店的相册图片（携程 ctgethotelalbum），下载到本地。

接口：POST https://m.ctrip.com/restapi/soa2/28820/ctgethotelalbum
  data.hotelImagePop.hotelProvide.imgTabs[]  每类图片：categoryName + imgUrlList[].subImgUrlList[].link
  data.hotelTopImage.imgUrlList[]            顶部首图

输出：
  output/images/<酒店ID>/01.jpg ... NN.jpg   本地图片（默认每店 15 张）
  albums/<酒店ID>.json                       相册元数据（图片URL/分类）

用法：
  python 17_collect_album.py                 # 25 家榜单
  python 17_collect_album.py --n 20          # 每店取 20 张
  python 17_collect_album.py --all           # 75 家候选
"""
import os, sys, json, glob, time, random, argparse, subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(BASE, ".ctrip_profile")
OUT_IMG = os.path.join(BASE, "output", "images")
ALBUM_DIR = os.path.join(BASE, "albums")
EXE = ("/Users/tcj/Library/Caches/ms-playwright/chromium-1234/chrome-mac-arm64/"
       "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
SEED = "130240848"
DEFAULT_N = 15

# 分类优先级（越靠前越优先入选）
CAT_ORDER = ["精选", "房间", "外观", "公共区域", "休闲", "餐饮",
             "商务", "家庭亲子", "周边", "其他"]

JS = """
(hotelId) => new Promise((resolve) => {
  const body = {hotelId:Number(hotelId),
    versionControl:[{key:"EnableVideo",value:"F"},{key:"NewLogoTripOnlineFirstImageAlbum",value:"F"}],
    head:{platform:"PC",cver:"0",bu:"HBU",group:"ctrip",locale:"zh-CN",region:"CN",
          pageId:"10650171194",timezone:"8",currency:"CNY",isSSR:false,
          extension:[{name:"cityId",value:""},{name:"checkIn",value:""},{name:"checkOut",value:""}]}};
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "https://m.ctrip.com/restapi/soa2/28820/ctgethotelalbum", true);
  xhr.setRequestHeader("content-type", "application/json");
  xhr.setRequestHeader("accept", "application/json");
  xhr.onload = () => resolve(xhr.responseText);
  xhr.onerror = () => resolve("XHRERR");
  xhr.send(JSON.stringify(body));
})
"""


def targets(all_flag):
    f = "candidates_final.json" if not all_flag else "candidates_top15.json"
    cands = json.load(open(os.path.join(BASE, f), encoding="utf-8"))
    out = {}
    for qu, rows in cands.items():
        for r in rows:
            out[str(r["酒店ID"])] = {"区": qu, "酒店名称": r["酒店名称"],
                                     "名次": r.get("排名")}
    return out


def parse_album(j):
    """→ (ordered image dicts, tabs 摘要)"""
    d = j.get("data") or {}
    hp = ((d.get("hotelImagePop") or {}).get("hotelProvide")) or {}
    tabs = hp.get("imgTabs") or []
    picked, seen = [], set()

    def add(link, pic_id, cat):
        if not link or pic_id in seen:
            return
        seen.add(pic_id)
        picked.append({"url": link, "pictureId": pic_id, "category": cat})

    # 先按分类优先级
    tabs_sorted = sorted(
        tabs, key=lambda t: CAT_ORDER.index(t.get("categoryName"))
        if t.get("categoryName") in CAT_ORDER else 99)
    for t in tabs_sorted:
        cat = t.get("categoryName")
        for wrap in (t.get("imgUrlList") or []):
            for it in (wrap.get("subImgUrlList") or []):
                if it.get("videoUrl"):
                    continue
                add(it.get("link"), it.get("pictureId"), cat)

    tops = ((d.get("hotelTopImage") or {}).get("imgUrlList")) or []
    for it in tops:
        if it.get("videoUrl"):
            continue
        add(it.get("imgUrl"), it.get("pictureId"), "首图")

    # 首图排最前
    picked.sort(key=lambda x: 0 if x["category"] == "首图" else 1)
    summary = [(t.get("categoryName"), t.get("total")) for t in tabs]
    return picked, summary


def download(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 3000:
        return True
    try:
        r = subprocess.run(
            ["curl", "-s", "-L", "--max-time", "30",
             "-A", UA, "-e", "https://hotels.ctrip.com/",
             "-o", dest, "-w", "%{http_code}", url],
            capture_output=True, text=True, timeout=45)
        ok = r.stdout.strip() == "200" and os.path.exists(dest) and os.path.getsize(dest) > 3000
        if not ok and os.path.exists(dest):
            os.remove(dest)
        return ok
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=DEFAULT_N, help="每店图片数")
    ap.add_argument("--all", action="store_true", help="75 家")
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    tg = targets(args.all)
    if args.only:
        keep = {s.strip() for s in args.only.split(",") if s.strip()}
        tg = {k: v for k, v in tg.items() if k in keep}
    os.makedirs(OUT_IMG, exist_ok=True)
    os.makedirs(ALBUM_DIR, exist_ok=True)
    print(f"目标 {len(tg)} 家 · 每店取 {args.n} 张\n")

    for lk in glob.glob(os.path.join(PROFILE, "Singleton*")):
        try:
            os.remove(lk)
        except Exception:
            pass

    from playwright.sync_api import sync_playwright
    stat = {}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=True, executable_path=EXE, user_agent=UA,
            locale="zh-CN", viewport={"width": 1440, "height": 940},
            args=["--disable-blink-features=AutomationControlled",
                  "--no-first-run", "--no-default-browser-check"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"https://hotels.ctrip.com/hotels/detail/?hotelId={SEED}",
                  timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(7000)

        for i, (hid, meta) in enumerate(tg.items(), 1):
            try:
                raw = page.evaluate(JS, hid)
                j = json.loads(raw)
            except Exception as e:
                print(f"[{i}/{len(tg)}] {meta['酒店名称']} 相册接口失败：{str(e)[:90]}")
                stat[hid] = {"名称": meta["酒店名称"], "图片数": 0, "状态": "接口失败"}
                continue

            picked, summary = parse_album(j)
            d = os.path.join(OUT_IMG, hid)
            os.makedirs(d, exist_ok=True)
            ok_n = 0
            used = []
            for it in picked:
                if ok_n >= args.n:
                    break
                fn = f"{ok_n+1:02d}.jpg"
                dest = os.path.join(d, fn)
                if download(it["url"], dest):
                    ok_n += 1
                    used.append({"file": fn, "category": it["category"],
                                 "url": it["url"], "pictureId": it["pictureId"]})
            json.dump({"hotelId": hid, "meta": meta, "tabs": summary,
                       "downloaded": used},
                      open(os.path.join(ALBUM_DIR, f"{hid}.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            stat[hid] = {"名称": meta["酒店名称"], "区": meta["区"],
                         "图片数": ok_n, "相册可选": len(picked), "状态": "ok" if ok_n else "无图"}
            print(f"[{i}/{len(tg)}] {meta['酒店名称'][:26]:<28} 下载 {ok_n}/{args.n} 张"
                  f"（相册共 {len(picked)} 张可选）")
            time.sleep(random.uniform(0.4, 0.9))

        ctx.close()

    json.dump(stat, open(os.path.join(BASE, "albums", "_summary.json"), "w",
                         encoding="utf-8"), ensure_ascii=False, indent=1)
    tot = sum(v["图片数"] for v in stat.values())
    print(f"\n完成：{len(stat)} 家 · 共 {tot} 张图片")
    bad = [v["名称"] for v in stat.values() if v["图片数"] == 0]
    if bad:
        print("无图酒店：", "、".join(bad))


if __name__ == "__main__":
    main()
