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
PROP_TOPIC = "分野"  # IELTSトピック分類: society/medical/culture/economy/environment/nature/history/technology/education/general


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


# ─── 分野(トピック)の番号→分野マッピング ─────────────────
# Notion DB に「分野」プロパティが無い場合のフォールバック。
# Notion 側に「分野」(select または text) を追加すれば、そちらが優先される。
TOPIC_RANGE_MAP = [
    (1, 25, "medical"), (26, 39, "society"), (40, 55, "medical"),
    (56, 75, "culture"), (76, 81, "economy"), (82, 94, "history"),
    (95, 103, "education"), (104, 116, "medical"), (117, 124, "education"),
    (125, 128, "nature"), (129, 134, "technology"), (135, 153, "general"),
    (154, 154, "education"), (155, 155, "society"), (156, 158, "education"),
    (159, 176, "medical"), (177, 199, "society"), (200, 220, "society"),
    (221, 223, "general"), (224, 226, "education"), (227, 229, "society"),
    (230, 230, "general"), (231, 245, "nature"), (246, 255, "general"),
    (256, 256, "technology"), (257, 262, "society"), (263, 280, "nature"),
    (281, 282, "society"), (283, 284, "general"), (285, 286, "society"),
    (287, 290, "history"), (291, 299, "society"), (301, 307, "technology"),
    (308, 312, "medical"), (313, 317, "environment"), (318, 322, "medical"),
    (323, 326, "environment"), (327, 332, "medical"), (333, 337, "medical"),
    (338, 342, "society"), (343, 352, "general"), (353, 357, "general"),
    (358, 362, "general"), (363, 367, "nature"), (368, 372, "general"),
    (373, 394, "society"), (395, 400, "medical"), (401, 402, "history"),
    (403, 416, "environment"), (417, 427, "culture"), (428, 436, "society"),
    (437, 441, "society"), (442, 451, "society"), (452, 456, "culture"),
    (457, 471, "environment"), (472, 472, "general"), (473, 480, "history"),
    (481, 497, "society"), (498, 510, "society"), (511, 530, "general"),
    (531, 545, "society"), (546, 561, "culture"), (562, 590, "environment"),
    (591, 600, "economy"), (601, 617, "technology"), (618, 625, "medical"),
    (626, 640, "society"), (641, 649, "general"), (650, 664, "society"),
    (665, 685, "history"), (686, 720, "society"), (721, 745, "environment"),
    (746, 749, "society"), (750, 761, "society"), (762, 770, "medical"),
    (771, 779, "society"), (780, 810, "economy"), (811, 819, "society"),
    (820, 830, "culture"), (831, 844, "general"), (845, 854, "general"),
    (855, 870, "culture"), (871, 879, "general"), (880, 945, "economy"),
    (946, 949, "society"), (950, 969, "nature"), (970, 985, "society"),
    (986, 989, "society"), (990, 999, "general"), (1000, 1059, "economy"),
    (1060, 1075, "economy"), (1076, 1129, "general"), (1130, 1145, "culture"),
    (1146, 1180, "culture"), (1181, 1189, "economy"), (1190, 1210, "general"),
    (1211, 1239, "general"), (1240, 1268, "culture"), (1269, 1295, "general"),
    (1296, 1300, "society"), (1301, 1340, "history"), (1341, 1395, "economy"),
    (1396, 1416, "culture"), (1417, 1423, "culture"), (1424, 1431, "society"),
]
TOPIC_OVERRIDES = {
    27: "economy", 73: "general", 74: "general", 181: "economy",
    187: "economy", 188: "economy", 189: "economy", 230: "general",
    285: "society", 287: "nature", 288: "nature", 289: "nature",
    290: "society", 405: "environment", 406: "economy", 407: "economy",
    408: "economy", 409: "economy", 410: "economy", 411: "economy",
    412: "environment", 414: "economy", 415: "economy", 416: "economy",
    449: "technology", 691: "environment", 701: "culture", 723: "society",
    736: "environment", 738: "environment", 741: "environment",
    876: "environment", 877: "environment", 902: "medical",
    1142: "nature", 1143: "nature", 1144: "general", 1145: "environment",
    1149: "nature", 1288: "environment", 1289: "environment",
    1290: "environment", 1292: "nature", 1293: "environment",
    1402: "society", 1403: "society", 1404: "society", 1405: "society",
}


def topic_for_number(num) -> str:
    """番号から分野を推定 (Notionに分野欄が無い場合のフォールバック)。"""
    if num is None:
        return "general"
    try:
        n = int(num)
    except (TypeError, ValueError):
        return "general"
    if n in TOPIC_OVERRIDES:
        return TOPIC_OVERRIDES[n]
    for start, end, cat in TOPIC_RANGE_MAP:
        if start <= n <= end:
            return cat
    return "general"


def page_to_word(page: dict) -> dict | None:
    """Notion ページを {番号, 単語, 意味, 例文, 品詞, 習熟度, skills, 分野} dict に変換。"""
    props = page.get("properties", {})
    word = extract_text(props.get(PROP_WORD)).strip()
    if not word:
        return None  # 単語が空のレコードはスキップ

    num = extract_number(props.get(PROP_NUMBER))
    # Notion に分野欄があればそれを優先、無ければ番号から自動判定
    topic_from_notion = extract_text(props.get(PROP_TOPIC)).strip()
    topic = topic_from_notion if topic_from_notion else topic_for_number(num)

    return {
        "番号": num,
        "単語": word,
        "意味": extract_text(props.get(PROP_MEANING)).strip(),
        "例文": extract_text(props.get(PROP_EXAMPLE)).strip(),
        "品詞": extract_text(props.get(PROP_POS)).strip() or "noun",
        "習熟度": extract_text(props.get(PROP_PROFICIENCY)).strip() or "苦手",
        "skills": extract_text(props.get(PROP_SKILLS)).strip() or "reading",
        "分野": topic,
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
            f"skills:{js_string(w['skills'])}, "
            f"分野:{js_string(w.get('分野', 'general'))} }},"
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
