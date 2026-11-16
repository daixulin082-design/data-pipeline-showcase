#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
crawler_example.py —— 配置化采集骨架

特点：
1. 换站点只改 SITE_CONFIG，不用动逻辑
2. 接口优先（JSON 比 HTML 稳定）
3. 429/403 指数退避，不当成「到底了」
4. 已采 ID 落盘，支持断点续传
5. 每线程独立 keep-alive 连接

用法：
    python crawler_example.py --out output.jsonl
"""
import argparse
import http.client
import json
import os
import ssl
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

# ============ 只需改这里 ============
SITE_CONFIG = {
    "host": "example.com",
    "list_path": "/api/items?page={page}&size=20",   # 列表接口，{page} 占位
    "detail_path": "/api/item/{id}",                 # 详情接口，{id} 占位
    "id_field": "id",                                # 列表项里 id 的字段名
    "max_pages": 200,
    "page_interval": 0.75,                           # 每页间隔（秒），防限流
    "threads": 6,
    "stop_on_empty_pages": 3,                        # 连续 N 页无新数据视为到底
}
# ===================================

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

_tls = threading.local()
_lock = threading.Lock()


def _conn(host):
    """每个线程复用一个 keep-alive 连接"""
    c = getattr(_tls, "conn", None)
    if c is None:
        c = http.client.HTTPSConnection(host, 443, timeout=30, context=CTX)
        _tls.conn = c
    return c


def fetch_json(host, path, retries=3):
    """
    带指数退避的请求。
    关键：429/403 是「被限流」，不是「没有数据」，要重试。
    """
    for attempt in range(retries):
        try:
            c = _conn(host)
            c.request("GET", path, headers={
                "User-Agent": UA,
                "Accept": "application/json",
                "Connection": "keep-alive",
            })
            r = c.getresponse()
            body = r.read()

            if (r.getheader("Connection") or "").lower() == "close":
                c.close()
                _tls.conn = None

            if r.status in (429, 403):
                time.sleep(4 + attempt * 2)      # 指数退避
                continue

            if r.status != 200:
                return None

            return json.loads(body.decode("utf-8", "replace"))

        except Exception:
            try:
                c = getattr(_tls, "conn", None)
                if c:
                    c.close()
            except Exception:
                pass
            _tls.conn = None
            time.sleep(1 + attempt)

    return None


def crawl_list(host):
    """采集列表，返回 id 列表"""
    ids, empty_streak = [], 0

    for page in range(1, SITE_CONFIG["max_pages"] + 1):
        path = SITE_CONFIG["list_path"].format(page=page)
        data = fetch_json(host, path)

        items = (data or {}).get("items") or []
        if not items:
            empty_streak += 1
            if empty_streak >= SITE_CONFIG["stop_on_empty_pages"]:
                break
            time.sleep(1.2)
            continue

        empty_streak = 0
        before = len(ids)
        for it in items:
            i = str(it.get(SITE_CONFIG["id_field"]))
            if i not in ids:
                ids.append(i)

        # 这一页没带来任何新 id → 可能已到底
        if len(ids) == before:
            empty_streak += 1
            if empty_streak >= SITE_CONFIG["stop_on_empty_pages"]:
                break

        if page % 50 == 0:
            print(f"  列表第 {page} 页，累计 {len(ids)} 条", flush=True)

        time.sleep(SITE_CONFIG["page_interval"])

    return ids


def crawl_detail(host, item_id):
    path = SITE_CONFIG["detail_path"].format(id=item_id)
    data = fetch_json(host, path)
    if not data:
        return None
    data["_id"] = item_id
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output.jsonl")
    ap.add_argument("--threads", type=int, default=SITE_CONFIG["threads"])
    ap.add_argument("--limit", type=int, default=0, help="只采前 N 条（调试用）")
    args = ap.parse_args()

    host = SITE_CONFIG["host"]

    # 断点续传：加载已采 ID
    done = set()
    if os.path.exists(args.out):
        for line in open(args.out, encoding="utf-8"):
            if line.strip():
                try:
                    done.add(json.loads(line)["_id"])
                except Exception:
                    pass
        print(f"已有 {len(done)} 条，继续采集")

    print("开始扫描列表…", flush=True)
    ids = crawl_list(host)
    todo = [i for i in ids if i not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"列表共 {len(ids)} 条，待采详情 {len(todo)} 条", flush=True)

    # 立即落盘，避免中途失败全丢
    fh = open(args.out, "a", encoding="utf-8")
    n = 0
    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        futures = [ex.submit(crawl_detail, host, i) for i in todo]
        for f in futures:
            row = f.result()
            if row:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                n += 1
                if n % 200 == 0:
                    print(f"  详情 {n}/{len(todo)}", flush=True)
    fh.close()

    print(f"完成：新增 {n} 条 → {args.out}")


if __name__ == "__main__":
    main()
