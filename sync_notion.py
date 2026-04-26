#!/usr/bin/env python3
"""
Notion 単語帳DB → index.html 同期スクリプト

Notion DB の全レコードを取得し、index.html 内の
`const SAMPLE_WORDS = [ ... ];` ブロックを書き換える。

環境変数:
  NOTION_TOKEN       - Notion インテグレーションのシークレットトークン
  NOTION_DATABASE_ID - 単語帳DBのID（URLの32文字のハッシュ部分）

使い方:
  python sync_notion.py
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
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
HTML_PATH = Path(__file__).parent / "index.html"
NOTION_API_VERSION = "2022-06-28"

# プロパティ名（Notion DB側のカラム名と一致させる）
PROP_NUMBER = "番号"
PROP_WORD = "単語"
PROP_MEANING = "意味"
PROP_EXAMPLE = "例文"
PROP_POS = "品詞"
PROP_PROFICIENCY = "習熟度"
PROP_SKILLS = "skills"


def die(msg: str, code: int = 1) -> None:
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(code)


def fetch_all_pages() -> list[dict]:
    """Notion DBから全ページを取得（ページネーション対応）。"""
    if not NOTION_TOKEN:
        die("環境変数 NOTION_TOKEN が設定されていません")
    if not NOTION_DATABASE_ID:
        die("環境変数 NOTION_DATABASE_ID が設定されていません")

    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }

    pages: list[dict] = []
    payload: dict = {"page_size": 100}

    while True:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
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
    """Notion プロパティから文字列を抽出（title / rich_text / select / multi_select 等に対応）。"""
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
        return ",".join(x["name"] for x in prop.get("multi_select", []))
    if t == "number":
        n = prop.get("number")
        return "" if n is None else str(n)
    if t == "status":
        s = prop.get("status")
        return s["name"] if s else ""
    if t == "formula":
        f = prop.get("formula", {})
        return str(f.get(f.get("type"), "") or "")
    return ""


def extract_number(prop: dict | None) -> int | None:
    """number 型プロパティから整数を取り出す。"""
    if not prop:
        return None
    if prop.get("type") == "number":
        return prop.get("number")
    # number 以外でも数字に変換可能なら受け入れる
    txt = extract_text(prop)
    try:
        return int(float(txt)) if txt else None
    except ValueError:
        return None


def page_to_word(page: dict) -> dict | None:
    """Notion ページを {番号, 単語, 意味, 例文, 品詞, 習熟度, skills} dict に変換。"""
    props = page.get("properties", {})
    word = extract_text(props.get(PROP_WORD)).strip()
    if not word:
        return None  # 単語が空のレコードはスキップ

    return {
        "番号": extract_number(props.get(PROP_NUMBER)),
        "単語": word,
        "意味": extract_text(props.get(PROP_MEANING)).strip(),
        "例文": extract_text(props.get(PROP_EXAMPLE)).strip(),
        "品詞": extract_text(props.get(PROP_POS)).strip() or "noun",
        "習熟度": extract_text(props.get(PROP_PROFICIENCY)).strip() or "苦手",
        "skills": extract_text(props.get(PROP_SKILLS)).strip() or "reading",
    }


def js_string(s: str) -> str:
    """文字列をJavaScriptのダブルクォート文字列リテラルとしてエスケープ。"""
    # json.dumps はダブルクォートで囲み、\, ", 制御文字を適切にエスケープしてくれる
    return json.dumps(s, ensure_ascii=False)


def words_to_js_array(words: list[dict]) -> str:
    """単語リストを `const SAMPLE_WORDS = [ ... ];` ブロック全体の文字列に整形。"""
    jst = timezone(timedelta(hours=9))
    timestamp = datetime.now(jst).strftime("%Y-%m-%d %H:%M JST")

    lines = [
        f"// ─── Notionから取得した単語データ（最終同期: {timestamp}）────",
        "// このブロックは GitHub Actions により自動生成されます。手動で編集しないでください。",
        "const SAMPLE_WORDS = [",
    ]
    for w in words:
        num = w["番号"] if w["番号"] is not None else "null"
        lines.append(
            f"  {{ 番号:{num}, "
            f"単語:{js_string(w['単語'])}, "
            f"意味:{js_string(w['意味'])}, "
            f"例文:{js_string(w['例文'])}, "
            f"品詞:{js_string(w['品詞'])}, "
            f"習熟度:{js_string(w['習熟度'])}, "
            f"skills:{js_string(w['skills'])} }},"
        )
    lines.append("];")
    return "\n".join(lines)


def replace_block_in_html(html: str, new_block: str) -> str:
    """index.html の `const SAMPLE_WORDS = [ ... ];` ブロックを新しい内容で置換。"""
    # 直前のコメント2行（最終同期日時 / Claudeへの呼びかけ）も含めて置換する
    pattern = re.compile(
        r"// ─── Notionから取得した単語データ.*?\nconst SAMPLE_WORDS = \[.*?\n\];",
        re.DOTALL,
    )
    if not pattern.search(html):
        die("index.html 内に SAMPLE_WORDS ブロックが見つかりません。HTMLの構造を確認してください。")
    return pattern.sub(lambda _: new_block, html, count=1)


def main() -> None:
    if not HTML_PATH.exists():
        die(f"{HTML_PATH} が存在しません")

    pages = fetch_all_pages()
    words = [w for w in (page_to_word(p) for p in pages) if w]

    if not words:
        die("有効な単語が0件でした。Notion DB のプロパティ名を確認してください。")

    # 番号でソート（番号がないものは末尾）
    words.sort(key=lambda w: (w["番号"] is None, w["番号"] if w["番号"] is not None else 0))
    print(f"✅ 有効な単語: {len(words)} 件")

    new_block = words_to_js_array(words)
    html = HTML_PATH.read_text(encoding="utf-8")
    new_html = replace_block_in_html(html, new_block)

    if html == new_html:
        print("ℹ️ 変更なし（HTMLは既に最新）")
        return

    HTML_PATH.write_text(new_html, encoding="utf-8")
    print(f"✅ {HTML_PATH.name} を更新しました")


if __name__ == "__main__":
    main()
