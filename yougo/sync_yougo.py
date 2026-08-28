#!/usr/bin/env python3
"""
Notion 用語・事例DB → yougo/index.html 同期スクリプト

Notion DB の全レコードを取得し、yougo/index.html 内の
`const TERMS = [ ... ];` ブロックを書き換える。

環境変数:
  NOTION_TOKEN     - Notion インテグレーションのシークレットトークン（必須）
  NOTION_YOUGO_DB  - 用語・事例DBのID（省略時は下の DEFAULT_DB_ID を使用）

使い方:
  python sync_yougo.py

Notion 側のプロパティ:
  必須  名前（title）／説明（text）／選択（select: 用語 / 事例）／出自（select）
  任意  提唱者・起源（text）／年代（text）／クラスタ（select）
        事例（relation または text）／既出（checkbox）
  任意プロパティは無くても動く。後から追加すれば自動で拾う。
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ─── 設定 ─────────────────────────────────────────────────
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DEFAULT_DB_ID = "3c9cebbea1f1802f878bc0614092ec2b"  # 用語・事例DB
NOTION_DB_ID = os.environ.get("NOTION_YOUGO_DB") or DEFAULT_DB_ID
HTML_PATH = Path(__file__).parent / "yougo" / "index.html"
NOTION_API_VERSION = "2022-06-28"

# プロパティ名（Notion DB側のカラム名と一致させる）
PROP_NAME = "名前"
PROP_DESC = "説明"
PROP_KIND = "選択"      # 用語 / 事例
PROP_SOURCE = "出自"    # 26 / 25 / 24 / 模試1〜6
PROP_CLUSTER = "クラスタ"       # 任意
PROP_AUTHOR = "提唱者・起源"     # 任意（旧名「提唱者」も拾う）
PROP_AUTHOR_ALT = "提唱者"
PROP_ERA = "年代"               # 任意
PROP_CASE = "事例"              # 任意（relation または text）
PROP_ASKED = "既出"             # 任意（checkbox）

# 過去問由来＝再出題の見込みが薄い出自。既出フラグが無い場合のフォールバック。
PAST_EXAM_SOURCES = {"24", "25", "26"}

# クラスタ別の目標枚数（一覧画面の進捗表示に使う）
CLUSTER_TARGETS = {"安保": 30, "IPE": 30, "規範・理論": 20}


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
                "Notion側でこのDBをインテグレーションに接続（···→接続→対象のインテグレーション）してください。"
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
    """Notion プロパティから文字列を抽出。"""
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
    if t == "multi_select":
        return "、".join(x["name"] for x in prop.get("multi_select", []))
    if t == "status":
        s = prop.get("status")
        return s["name"] if s else ""
    if t == "number":
        n = prop.get("number")
        return "" if n is None else str(n)
    if t == "checkbox":
        return "1" if prop.get("checkbox") else ""
    if t == "formula":
        f = prop.get("formula", {})
        return str(f.get(f.get("type"), "") or "")
    return ""


def relation_ids(prop: dict | None) -> list[str]:
    """relation プロパティから関連ページIDの一覧を取り出す。"""
    if not prop or prop.get("type") != "relation":
        return []
    return [r.get("id", "").replace("-", "") for r in prop.get("relation", [])]


def normalize_id(page_id: str) -> str:
    return (page_id or "").replace("-", "")


def build_title_map(pages: list[dict]) -> dict[str, str]:
    """ページID → 名前 の対応表。用語↔事例が同一DB内リレーションの場合に使う。"""
    out = {}
    for p in pages:
        title = extract_text(p.get("properties", {}).get(PROP_NAME)).strip()
        if title:
            out[normalize_id(p.get("id", ""))] = title
    return out


def page_to_term(page: dict, title_map: dict[str, str]) -> dict | None:
    props = page.get("properties", {})
    name = extract_text(props.get(PROP_NAME)).strip()
    if not name:
        return None  # 名前が空のレコードはスキップ

    source = extract_text(props.get(PROP_SOURCE)).strip()

    # 事例: relation なら関連ページの名前を、text ならそのまま
    case_prop = props.get(PROP_CASE)
    if case_prop and case_prop.get("type") == "relation":
        names = [title_map.get(i, "") for i in relation_ids(case_prop)]
        case = "、".join(n for n in names if n)
    else:
        case = extract_text(case_prop).strip()

    # 既出: checkbox があればそれを優先、無ければ出自から推定
    asked_prop = props.get(PROP_ASKED)
    if asked_prop and asked_prop.get("type") == "checkbox":
        asked = bool(asked_prop.get("checkbox"))
    else:
        asked = source in PAST_EXAM_SOURCES

    author = extract_text(props.get(PROP_AUTHOR)).strip()
    if not author:
        author = extract_text(props.get(PROP_AUTHOR_ALT)).strip()

    return {
        "名前": name,
        "説明": extract_text(props.get(PROP_DESC)).strip(),
        "種別": extract_text(props.get(PROP_KIND)).strip() or "用語",
        "出自": source,
        "クラスタ": extract_text(props.get(PROP_CLUSTER)).strip(),
        "提唱者": author,
        "年代": extract_text(props.get(PROP_ERA)).strip(),
        "事例": case,
        "既出": asked,
    }


def js_string(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def terms_to_js_array(terms: list[dict]) -> str:
    jst = timezone(timedelta(hours=9))
    timestamp = datetime.now(jst).strftime("%Y-%m-%d %H:%M JST")
    n_term = sum(1 for t in terms if t["種別"] == "用語")
    n_case = len(terms) - n_term

    lines = [
        f"// ─── Notion 用語・事例DB から取得（最終同期: {timestamp} / 用語{n_term}・事例{n_case}）────",
        "// このブロックは GitHub Actions により自動生成されます。手動で編集しないでください。",
        f"const SYNCED_AT = {js_string(timestamp)};",
        f"const CLUSTER_TARGETS = {json.dumps(CLUSTER_TARGETS, ensure_ascii=False)};",
        "const TERMS = [",
    ]
    for t in terms:
        lines.append(
            "  { "
            f"名前:{js_string(t['名前'])}, "
            f"説明:{js_string(t['説明'])}, "
            f"種別:{js_string(t['種別'])}, "
            f"出自:{js_string(t['出自'])}, "
            f"クラスタ:{js_string(t['クラスタ'])}, "
            f"提唱者:{js_string(t['提唱者'])}, "
            f"年代:{js_string(t['年代'])}, "
            f"事例:{js_string(t['事例'])}, "
            f"既出:{'true' if t['既出'] else 'false'}"
            " },"
        )
    lines.append("];")
    return "\n".join(lines)


def data_rows(block: str) -> list[str]:
    """ブロックから TERMS の行だけを取り出す（同期日時の行は除く）。"""
    return [ln for ln in block.split("\n") if ln.lstrip().startswith("{ 名前:")]


def replace_block_in_html(html: str, new_block: str) -> str:
    pattern = re.compile(
        r"// ─── Notion 用語・事例DB から取得.*?\nconst TERMS = \[.*?\n\];",
        re.DOTALL,
    )
    if not pattern.search(html):
        die("yougo/index.html 内に TERMS ブロックが見つかりません。HTMLの構造を確認してください。")
    return pattern.sub(lambda _: new_block, html, count=1)


def sort_key(t: dict):
    """クラスタ→種別→名前 の順。並びを安定させて差分を小さく保つ。"""
    cluster_order = {"安保": 0, "IPE": 1, "規範・理論": 2}
    return (
        cluster_order.get(t["クラスタ"], 9),
        t["クラスタ"],
        0 if t["種別"] == "用語" else 1,
        t["名前"],
    )


def main() -> None:
    if not HTML_PATH.exists():
        die(f"{HTML_PATH} が存在しません")

    pages = fetch_all_pages()
    title_map = build_title_map(pages)
    terms = [t for t in (page_to_term(p, title_map) for p in pages) if t]

    if not terms:
        die("有効なレコードが0件でした。Notion DB のプロパティ名を確認してください。")

    empty_desc = [t["名前"] for t in terms if not t["説明"]]
    if empty_desc:
        print(f"⚠️ 説明が空: {len(empty_desc)} 件 → {'、'.join(empty_desc[:10])}")

    no_author = [t["名前"] for t in terms if t["種別"] == "用語" and not t["提唱者"]]
    if no_author:
        print(f"⚠️ 提唱者・起源が空の用語: {len(no_author)} 件 → {'、'.join(no_author[:10])}")

    terms.sort(key=sort_key)
    print(f"✅ 有効なレコード: {len(terms)} 件")

    new_block = terms_to_js_array(terms)
    html = HTML_PATH.read_text(encoding="utf-8")

    # 中身が同じなら書き換えない（同期日時だけの差分でコミットを増やさない）
    current = re.search(
        r"// ─── Notion 用語・事例DB から取得.*?\nconst TERMS = \[.*?\n\];", html, re.DOTALL
    )
    if current and data_rows(current.group(0)) == data_rows(new_block):
        print("ℹ️ 変更なし（Notion側に更新がありません）")
        return

    new_html = replace_block_in_html(html, new_block)

    HTML_PATH.write_text(new_html, encoding="utf-8")
    print(f"✅ {HTML_PATH} を更新しました")


if __name__ == "__main__":
    main()
