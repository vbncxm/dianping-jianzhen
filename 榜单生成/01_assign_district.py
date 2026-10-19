# -*- coding: utf-8 -*-
"""
第一步：酒店区域归属 + 去重
- 合并 5 个区 JSON，按 酒店ID 去重（同 ID 取字段最完整/评论数最大的一条）
- 用昆明 5 区真实行政边界（GeoJSON）做点在多边形内判定，为每家酒店指派唯一所属区
输出：hotels_clean.csv / hotels_clean.json
"""
import json, csv, os, collections

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
GEO = "/tmp/km_530100.json"

DISTRICT_FILES = {
    "五华区": "五华区.json",
    "盘龙区": "盘龙区.json",
    "官渡区": "官渡区.json",
    "西山区": "西山区.json",
    "呈贡区": "呈贡区.json",
}
ADCODE = {"五华区": "530102", "盘龙区": "530103", "官渡区": "530111",
          "西山区": "530112", "呈贡区": "530114"}


def num(x):
    if x is None:
        return None
    s = str(x).strip().replace("条点评", "").replace(",", "").replace("分", "")
    try:
        return float(s)
    except Exception:
        return None


def rings(geometry):
    """把 Polygon / MultiPolygon 统一成 [[外环, 洞...], ...]"""
    t, c = geometry["type"], geometry["coordinates"]
    if t == "Polygon":
        return [c]
    if t == "MultiPolygon":
        return c
    return []


def in_ring(x, y, ring):
    """射线法：点是否在单个环内"""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if ((y1 > y) != (y2 > y)):
            xin = (x2 - x1) * (y - y1) / (y2 - y1 + 1e-15) + x1
            if x < xin:
                inside = not inside
    return inside


def in_polygon(x, y, poly):
    """poly = [外环, 洞1, 洞2...]"""
    if not in_ring(x, y, poly[0]):
        return False
    for hole in poly[1:]:
        if in_ring(x, y, hole):
            return False
    return True


def load_boundaries():
    geo = json.load(open(GEO, encoding="utf-8"))
    bounds = {}
    for f in geo["features"]:
        name = f["properties"]["name"]
        if name in ADCODE:
            bounds[name] = rings(f["geometry"])
    return bounds


def main():
    bounds = load_boundaries()

    # 1) 合并去重
    best = {}
    for dist, fn in DISTRICT_FILES.items():
        for r in json.load(open(os.path.join(ROOT, fn), encoding="utf-8")):
            hid = str(r["酒店ID"])
            score = num(r.get("评论数量")) or 0
            if hid not in best or score > (num(best[hid].get("评论数量")) or 0):
                best[hid] = r

    print(f"原始 {sum(len(json.load(open(os.path.join(ROOT, f), encoding='utf-8'))) for f in DISTRICT_FILES.values())} 条 → 去重后 {len(best)} 家")

    # 2) 归属
    out, outside, badgeo = [], [], 0
    for hid, r in best.items():
        try:
            x, y = float(r["经度"]), float(r["纬度"])
        except Exception:
            badgeo += 1
            continue
        hit = None
        for dname, polys in bounds.items():
            if any(in_polygon(x, y, p) for p in polys):
                hit = dname
                break
        rec = dict(r)
        rec["唯一酒店ID"] = hid
        rec["所属区"] = hit
        if hit:
            out.append(rec)
        else:
            outside.append(rec)

    print(f"归属成功 {len(out)} 家；落在 5 区边界外 {len(outside)} 家；坐标异常 {badgeo} 家")
    c = collections.Counter(r["所属区"] for r in out)
    print("各区（经纬度归属）：", dict(c))

    if outside:
        cc = collections.Counter((r.get("所属商圈") or "未知") for r in outside)
        print("边界外记录 TOP10 商圈：", cc.most_common(10))

    # 3) 输出
    cols = ["唯一酒店ID", "所属区", "酒店名称", "星级", "评分", "评分描述", "评论数量",
            "卫生评分", "设施评分", "环境评分", "服务评分", "所属商圈", "位置描述",
            "详细地址", "经度", "纬度", "首图URL", "入住房型", "床型描述",
            "一句话点评", "英文名称"]
    with open(os.path.join(BASE, "hotels_clean.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in out:
            row = dict(r)
            row["房型标签"] = "|".join(r.get("房型标签") or [])
            w.writerow(row)

    json.dump(out, open(os.path.join(BASE, "hotels_clean.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(outside, open(os.path.join(BASE, "hotels_outside.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("已输出 hotels_clean.csv / hotels_clean.json / hotels_outside.json")


if __name__ == "__main__":
    main()
