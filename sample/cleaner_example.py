#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cleaner_example.py —— 数据清洗流水线

三层：
1. 去重     按业务指纹（而非文本相似度）
2. 过滤     广告加权评分（而非黑名单）
3. 抽取     正则优先级匹配

用法：
    python cleaner_example.py --in output.jsonl --out clean.csv
"""
import argparse
import csv
import json
import re

# ============ 广告信号 ============
AD_STRONG = ["招聘", "加盟", "日结", "包吃住", "高薪", "代理", "分销"]
AD_WEAK = ["会所", "工作室", "团队", "桑拿", "足浴", "养生", "连锁", "可分店"]
AD_THRESHOLD = 4
# ==================================


def ad_score(text):
    """加权评分：强信号 +3，弱信号 +1"""
    s = 0
    t = text or ""
    for k in AD_STRONG:
        if k in t:
            s += 3
    for k in AD_WEAK:
        if k in t:
            s += 1
    return s


def dedupe(rows):
    """
    按业务指纹去重。

    为什么不用文本相似度？
      - 同一实体重复发布时标题不同、正文不同，但联系方式一致
      - Jaccard / SimHash 在短文本上误判高
      - 联系方式组合唯一性更强
    """
    seen, out = set(), []
    for r in rows:
        contact = r.get("contact") or {}
        if not contact:
            continue
        sig = (r.get("city"),) + tuple(sorted(contact.items()))
        if sig in seen:
            continue
        seen.add(sig)
        out.append(r)
    return out


def filter_ads(rows):
    kept = []
    for r in rows:
        blob = str(r.get("title", "")) + " " + str(r.get("text", ""))
        if ad_score(blob) < AD_THRESHOLD:
            kept.append(r)
    return kept


# ============ 字段抽取规则 ============
PRICE_RULES = [
    (r"消费价格[：:]\s*(\d{2,5})", 1),
    (r"价格[：:]\s*(\d{2,5})", 1),
    (r"水费[：:]\s*(\d{2,5})", 1),
    (r"(\d{1,2})\s*米", 100),        # 3米 → 300
    (r"(\d{1,2})\s*[pP](?:元|，|,|$)", 100),   # 6P → 600
    (r"(\d{1,2})\s*张(?:元)?", 100),  # 3张 → 300
    (r"(?<!\d)([1-9]\d{2,4})\s*(?:元|块|/次|一次)", 1),
]

AGE_RULES = [
    (r"年龄[：:]\s*(\d{1,2})", None),
    (r"(\d{2})\s*(?:岁|y)", None),
]

CONTACT_RULES = {
    "电话": r"(?<!\d)(1[3-9]\d{9})(?!\d)",
    "QQ": r"(?:QQ|[Qq]{2})\s*[:：]?\s*(\d{5,11})",
    "微信": r"微信\s*[:：]?\s*([A-Za-z0-9_\-]{5,20})",
}


def extract_price(text):
    for pattern, mult in PRICE_RULES:
        m = re.search(pattern, text or "")
        if m:
            v = int(m.group(1)) * mult
            if 50 <= v <= 20000:      # 过滤明显异常值
                return v
    return None


def age_band(n):
    if n < 20:
        return "18-20"
    if n < 25:
        return "20-25"
    if n < 30:
        return "25-30"
    if n < 40:
        return "30-40"
    return "40+"


def extract_age(text):
    for pattern, _ in AGE_RULES:
        m = re.search(pattern, text or "")
        if m:
            return age_band(int(m.group(1)))
    return ""


def extract_contacts(text):
    out = {}
    for name, pattern in CONTACT_RULES.items():
        found = list(dict.fromkeys(re.findall(pattern, text or "")))
        if found:
            out[name] = " ".join(found[:2])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="output.jsonl")
    ap.add_argument("--out", dest="dst", default="clean.csv")
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.src, encoding="utf-8") if l.strip()]
    print(f"原始          : {len(rows)}")

    rows = [r for r in rows if r.get("contact") or extract_contacts(r.get("text", ""))]
    print(f"有联系方式    : {len(rows)}")

    rows = dedupe(rows)
    print(f"去重后        : {len(rows)}")

    rows = filter_ads(rows)
    print(f"过滤广告后    : {len(rows)}")

    fields = ["id", "date", "city", "area", "title", "price", "age", "电话", "QQ", "微信", "text"]
    with open(args.dst, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            c = r.get("contact") or extract_contacts(r.get("text", ""))
            w.writerow({
                "id": r.get("_id", ""),
                "date": r.get("date", ""),
                "city": r.get("city", ""),
                "area": r.get("area", ""),
                "title": str(r.get("title", ""))[:40].replace("\n", " "),
                "price": extract_price(r.get("text", "")) or "",
                "age": extract_age(r.get("text", "")),
                "电话": c.get("电话", ""),
                "QQ": c.get("QQ", ""),
                "微信": c.get("微信", ""),
                "text": str(r.get("text", ""))[:200].replace("\n", " "),
            })

    print(f"输出          : {args.dst}")


if __name__ == "__main__":
    main()
