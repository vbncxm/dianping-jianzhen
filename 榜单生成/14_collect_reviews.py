# -*- coding: utf-8 -*-
"""
采集「春城金鉴榜」榜单酒店的携程点评全文。

接口：POST https://m.ctrip.com/restapi/soa2/34308/getHotelCommentInfo
  评论正文位于 data.groupList[0].commentList
  可翻页总量 = data.totalCountForPage（= totalCount - repeatCommentCount，重复点评被折叠）

采集范围：默认榜单 Top5×5 = 25 家（candidates_final.json）；--all 则扩到 75 家候选。

输出：
  reviews/<酒店ID>.json        单店原始评论
  reviews/all_reviews.jsonl    全量逐条（含所属区/榜名次/酒店名）
  reviews/summary.json         每店采集统计

用法：
  python 14_collect_reviews.py            # 25 家榜单
  python 14_collect_reviews.py --all      # 75 家
  python 14_collect_reviews.py --only 130240848,133273882
"""
import os, sys, json, glob, time, random, argparse

BASE = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(BASE, ".ctrip_profile")
OUT = os.path.join(BASE, "reviews")
EXE = ("/Users/tcj/Library/Caches/ms-playwright/chromium-1234/chrome-mac-arm64/"
       "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
SEED_HOTEL = "130240848"          # 只作页面载体，评论按 body 里的 hotelId 取
PAGE_SIZE = 50
CHECKIN, CHECKOUT = "2026-10-21", "2026-10-22"

JS = """
async (args) => {
  const [hotelId, pageIndex, pageSize, ci, co] = args;
  const body = {hotelId:Number(hotelId),
    commentFilterOptions:{pageIndex:pageIndex,pageSize:pageSize,repeatComment:1},
    sceneTypes:["CommentList"],
    head:{platform:"PC",cver:"0",bu:"HBU",group:"ctrip",locale:"zh-CN",region:"CN",
          timezone:"8",currency:"CNY",isSSR:false,
          extension:[{name:"cityId",value:""},{name:"checkIn",value:ci},{name:"checkOut",value:co}]}};
  const r = await fetch("https://m.ctrip.com/restapi/soa2/34308/getHotelCommentInfo",
    {method:"POST",headers:{"content-type":"application/json","accept":"application/json"},
     body:JSON.stringify(body),credentials:"include"});
  return await r.text();
}
"""


def load_targets(all_flag, only):
    cands = json.load(open(os.path.join(BASE, "candidates_final.json"), encoding="utf-8"))
    hits = {}
    for qu, rows in cands.items():
        for r in rows:
            hits[str(r["酒店ID"])] = {"区": qu, "榜名次": r.get("排名"),
                                      "酒店名称": r["酒店名称"], "价格": r.get("价格")}
    if all_flag:
        c15 = json.load(open(os.path.join(BASE, "candidates_top15.json"), encoding="utf-8"))
        for qu, rows in c15.items():
            for r in rows:
                hid = str(r["酒店ID"])
                if hid not in hits:
                    hits[hid] = {"区": qu, "榜名次": None, "酒店名称": r["酒店名称"],
                                 "价格": None}
    if only:
        keep = {s.strip() for s in only.split(",") if s.strip()}
        hits = {k: v for k, v in hits.items() if k in keep}
    return hits


def slim(c, meta):
    ri = c.get("ratingInfo") or {}
    fb = c.get("feedbackList") or []
    return {
        "评论ID": c.get("id"),
        "酒店ID": str(c.get("hotelId")),
        "酒店名称": meta.get("酒店名称"),
        "所属区": meta.get("区"),
        "榜名次": meta.get("榜名次"),
        "昵称": (c.get("userInfo") or {}).get("nickName"),
        "评论日期": c.get("createDate"),
        "入住日期": c.get("checkinDate"),
        "评分": c.get("rating"),
        "总分": ri.get("ratingAll"),
        "位置分": ri.get("ratingLocation"),
        "设施分": ri.get("ratingFacility"),
        "服务分": ri.get("ratingService"),
        "客房分": ri.get("ratingRoom"),
        "出行类型": c.get("travelTypeText"),
        "房型": c.get("roomName"),
        "IP归属": c.get("ipLocation"),
        "有用数": c.get("usefulCount"),
        "图片数": len(c.get("imageList") or []),
        "视频数": len(c.get("videoList") or []),
        "推荐": c.get("recommend"),
        "来源": c.get("sourceName"),
        "是否Trip": c.get("isTripComment"),
        "商家回复": (fb[0].get("content") if fb else ""),
        "评论内容": c.get("content"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="扩到 75 家候选")
    ap.add_argument("--only", default="", help="逗号分隔的酒店ID")
    ap.add_argument("--page-size", type=int, default=PAGE_SIZE)
    args = ap.parse_args()

    targets = load_targets(args.all, args.only)
    os.makedirs(OUT, exist_ok=True)
    print(f"目标 {len(targets)} 家酒店\n")

    for lk in glob.glob(os.path.join(PROFILE, "Singleton*")):
        try:
            os.remove(lk)
        except Exception:
            pass

    from playwright.sync_api import sync_playwright
    summary = {}
    allf = open(os.path.join(OUT, "all_reviews.jsonl"), "w", encoding="utf-8")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=True, executable_path=EXE, user_agent=UA,
            locale="zh-CN", viewport={"width": 1440, "height": 940},
            args=["--disable-blink-features=AutomationControlled",
                  "--no-first-run", "--no-default-browser-check"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"https://hotels.ctrip.com/hotels/detail/?hotelId={SEED_HOTEL}",
                  timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(7000)

        for idx, (hid, meta) in enumerate(targets.items(), 1):
            store = os.path.join(OUT, f"{hid}.json")
            if os.path.exists(store):
                done = json.load(open(store, encoding="utf-8"))
                print(f"[{idx}/{len(targets)}] {meta['酒店名称']} 已完成（{len(done['comments'])} 条），跳过")
                for c in done["comments"]:
                    allf.write(json.dumps(slim(c, meta), ensure_ascii=False) + "\n")
                summary[hid] = {"名称": meta["酒店名称"], "区": meta["区"],
                                "条数": len(done["comments"]), "状态": "cached"}
                continue

            got, seen, page_i, total = [], set(), 0, None
            while True:
                page_i += 1
                try:
                    raw = page.evaluate(JS, [hid, page_i, args.page_size, CHECKIN, CHECKOUT])
                    j = json.loads(raw)
                except Exception as e:
                    print(f"    page{page_i} 解析失败：{str(e)[:80]}")
                    break
                d = j.get("data") or {}
                if total is None:
                    total = d.get("totalCountForPage") or d.get("totalCount")
                g = (d.get("groupList") or [{}])
                lst = (g[0].get("commentList") or []) if g else []
                new = 0
                for c in lst:
                    cid = c.get("id")
                    if cid in seen:
                        continue
                    seen.add(cid)
                    got.append(c)
                    new += 1
                print(f"    page{page_i:>3}: +{new:<3} 累计 {len(got)}/{total}")
                if new == 0 or (total and len(got) >= total):
                    break
                time.sleep(random.uniform(0.5, 1.1))

            json.dump({"hotelId": hid, "meta": meta, "totalCountForPage": total,
                       "comments": got},
                      open(store, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            for c in got:
                allf.write(json.dumps(slim(c, meta), ensure_ascii=False) + "\n")
            allf.flush()
            summary[hid] = {"名称": meta["酒店名称"], "区": meta["区"],
                            "条数": len(got), "接口总数": total, "状态": "ok"}
            print(f"[{idx}/{len(targets)}] {meta['酒店名称']} → {len(got)} 条\n")
            time.sleep(random.uniform(0.8, 1.5))

        ctx.close()

    allf.close()
    json.dump(summary, open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    nn = sum(v["条数"] for v in summary.values())
    print(f"完成：{len(summary)} 家，共 {nn} 条评论")
    print(f"输出目录：{OUT}")


if __name__ == "__main__":
    main()
