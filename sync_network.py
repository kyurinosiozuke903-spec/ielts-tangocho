#!/usr/bin/env python3
"""
Notion 用語DB・新 → network/data/terms.json 同期スクリプト

用語・事例DB（yougo/）とは別系統。ネットワーク表示ページ network/ の元データだけを作る。

環境変数:
  NOTION_TOKEN         - Notion インテグレーションのシークレットトークン（必須）
  NOTION_YOUGO_NEW_DB  - 用語DB・新のID（省略時は下の DEFAULT_DB_ID を使用）

使い方:
  python sync_network.py

Notion 側のプロパティ:
  必須  名前（title）
  任意  定義（text）／事例（text）／提唱者（text）／理論学派（select）／事例系統（multi_select）
  任意プロパティは無くても動く。後から追加すれば自動で拾う。
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ─── 設定 ─────────────────────────────────────────────────
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DEFAULT_DB_ID = "3d5cebbea1f1801486bbfbf4b58db347"  # 用語DB・新
NOTION_DB_ID = os.environ.get("NOTION_YOUGO_NEW_DB") or DEFAULT_DB_ID
OUT_PATH = Path(__file__).parent / "network" / "data" / "terms.json"
MASTER_PATH = Path(__file__).parent / "network" / "data" / "proposers.json"
NOTION_API_VERSION = "2022-06-28"

PROP_NAME = "名前"
PROP_DEF = "定義"
PROP_CASE = "事例"
PROP_AUTHOR = "提唱者"
PROP_SCHOOL = "理論学派"
PROP_TAGS = "事例系統"

SCHOOL_ORDER = ["リアリズム", "リベラリズム", "コンストラクティビズム", "批判理論", "その他"]


def die(msg: str, code: int = 1) -> None:
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(code)


def fetch_all_pages() -> list[dict]:
    """Notion DBから全ページを取得（ページネーション対応）。"""
    if not NOTION_TOKEN:
        die("環境変数 NOTION_TOKEN が設定されていません")

    url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }

    pages: list[dict] = []
    payload: dict = {"page_size": 100}

    while True:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code == 404:
            die(
                f"DB {NOTION_DB_ID} が見つかりません。"
                "Notion側で『用語DB・新』をインテグレーションに接続（···→接続→対象のインテグレーション）してください。"
            )
        if resp.status_code != 200:
            die(f"Notion API エラー {resp.status_code}: {resp.text}")
        data = resp.json()
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]

    print(f"✅ Notion から {len(pages)} 件のレコードを取得")
    return pages


def extract_text(prop: dict | None) -> str:
    if not prop:
        return ""
    t = prop.get("type")
    if t == "title":
        return "".join(x.get("plain_text", "") for x in prop.get("title", []))
    if t == "rich_text":
        return "".join(x.get("plain_text", "") for x in prop.get("rich_text", []))
    if t == "select":
        sel = prop.get("select")
        return sel["name"] if sel else ""
    if t == "status":
        s = prop.get("status")
        return s["name"] if s else ""
    if t == "number":
        n = prop.get("number")
        return "" if n is None else str(n)
    if t == "formula":
        f = prop.get("formula", {})
        return str(f.get(f.get("type"), "") or "")
    return ""


def extract_multi(prop: dict | None) -> list[str]:
    if not prop or prop.get("type") != "multi_select":
        return []
    return [x["name"] for x in prop.get("multi_select", [])]


def normalize_id(page_id: str) -> str:
    return (page_id or "").replace("-", "")


def page_to_term(page: dict) -> dict | None:
    props = page.get("properties", {})
    name = extract_text(props.get(PROP_NAME)).strip()
    if not name:
        return None  # 名前が空のレコードはスキップ

    pid = normalize_id(page.get("id", ""))
    return {
        "id": pid,
        "名前": name,
        "理論学派": extract_text(props.get(PROP_SCHOOL)).strip(),
        "事例系統": extract_multi(props.get(PROP_TAGS)),
        "提唱者": extract_text(props.get(PROP_AUTHOR)).strip(),
        "定義": extract_text(props.get(PROP_DEF)).strip(),
        "事例": extract_text(props.get(PROP_CASE)).strip(),
        "url": f"https://app.notion.com/{pid}",
    }


def sort_key(t: dict):
    """理論学派→名前 の順。並びを安定させて差分を小さく保つ。"""
    order = SCHOOL_ORDER.index(t["理論学派"]) if t["理論学派"] in SCHOOL_ORDER else 9
    return (order, t["理論学派"], t["名前"])


def report_unmapped(terms: list[dict]) -> None:
    """提唱者マスタに未登録の語をログに出す（ページ側は文字列照合で仮表示する）。"""
    if not MASTER_PATH.exists():
        return
    try:
        master = json.loads(MASTER_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("⚠️ proposers.json を読めませんでした（未登録チェックをスキップ）")
        return
    known_ids = set(master.get("terms", {}))
    known_names = set(master.get("termIdByName", {}))
    missing = [t["名前"] for t in terms if t["id"] not in known_ids and t["名前"] not in known_names]
    if missing:
        print(f"⚠️ 提唱者マスタ未登録: {len(missing)} 件 → {'、'.join(missing[:10])}")
        print("   network/tools/master_src.js に追記して build_master.js を実行すると、役割つきで表示されます。")


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    pages = fetch_all_pages()
    terms = [t for t in (page_to_term(p) for p in pages) if t]
    if not terms:
        die("有効なレコードが0件でした。Notion DB のプロパティ名を確認してください。")

    no_author = [t["名前"] for t in terms if not t["提唱者"]]
    if no_author:
        print(f"⚠️ 提唱者が空: {len(no_author)} 件 → {'、'.join(no_author[:10])}")
    no_school = [t["名前"] for t in terms if not t["理論学派"]]
    if no_school:
        print(f"⚠️ 理論学派が空: {len(no_school)} 件 → {'、'.join(no_school[:10])}")

    terms.sort(key=sort_key)
    print(f"✅ 有効なレコード: {len(terms)} 件")
    report_unmapped(terms)

    jst = timezone(timedelta(hours=9))
    payload = {
        "syncedAt": datetime.now(jst).strftime("%Y-%m-%d %H:%M JST"),
        "source": "Notion 用語DB・新",
        "count": len(terms),
        "terms": terms,
    }

    # 中身が同じなら書き換えない（同期日時だけの差分でコミットを増やさない）
    if OUT_PATH.exists():
        try:
            current = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = None
        if current and current.get("terms") == terms:
            print("ℹ️ 変更なし（Notion側に更新がありません）")
            return

    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ {OUT_PATH} を更新しました")


if __name__ == "__main__":
    main()
