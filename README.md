# 📝 IELTS単語帳 ─ Notion 自動同期セットアップ

毎日 **JST 10:00 / 18:00** に Notion 単語帳DBから単語を取得して `index.html` を自動更新し、
GitHub Pages 経由でスマホ・PCのどちらからでも閲覧できるようにします。

仕組み:
```
Notion DB
   │
   ▼ (毎日 10:00 / 18:00 JST)
GitHub Actions が sync_notion.py を実行
   │
   ▼
index.html 内の SAMPLE_WORDS 配列を書き換えてコミット
   │
   ▼
GitHub Pages が更新後の index.html を配信
   │
   ▼
スマホ / PC からURLで閲覧
```

---

## 📦 含まれているファイル

| ファイル | 役割 |
|---|---|
| `index.html` | 単語帳アプリ本体 |
| `sync_notion.py` | Notion DB → `index.html` の同期スクリプト |
| `.github/workflows/sync.yml` | 毎日 10:00 / 18:00 JST に実行する GitHub Actions 設定 |
| `.nojekyll` | GitHub Pages が Jekyll 処理をスキップするための空ファイル |

---

## 🚀 セットアップ（初回のみ・所要 10 分程度）

### 1. GitHub リポジトリを作る

1. https://github.com/new を開く
2. リポジトリ名を入力（例: `ielts-tangocho`）
3. **Public** を選択
4. "Create repository" をクリック

### 2. ファイルを4つアップロード

ローカルでこのフォルダ全体を git push してもよいですし、慣れていなければブラウザからドラッグ&ドロップでもOKです（"Add file" → "Upload files"）。

アップロードする中身:
```
ielts-tangocho/
├── index.html
├── sync_notion.py
├── .nojekyll
└── .github/
    └── workflows/
        └── sync.yml
```

> ⚠️ `.github/` フォルダはブラウザのドラッグ&ドロップだとうまく作れないことがあります。その場合はファイル名欄に直接 `.github/workflows/sync.yml` と入力すれば自動でフォルダが作成されます。

### 3. Notion インテグレーションを作って、DB を共有する

#### 3-1. インテグレーションを作成

1. https://www.notion.so/my-integrations を開く
2. **"+ New integration"** をクリック
3. 名前を入力（例: `IELTS Tangocho Sync`）
4. Associated workspace は単語帳DBがあるワークスペースを選択
5. Type は **"Internal"** のままでOK
6. "Save" をクリック
7. 表示された **"Internal Integration Secret"**（`secret_xxxx...` または `ntn_xxxx...` で始まる文字列）をコピーしておく ← **後で使います**

#### 3-2. 単語帳DBにインテグレーションを接続

1. Notion で単語帳DBのページを開く
2. 右上の `•••`（メニュー）→ **"Connections"** → **"Connect to"** → 先ほど作ったインテグレーション名を選択
3. ポップアップで "Confirm" をクリック

> これをやらないと API は「DBが見つかりません」エラーを返します。最頻出の落とし穴なので必ずやってください。

#### 3-3. DBのIDを取得

1. 単語帳DBをブラウザで開いた時のURLを見る
2. URL の形式は `https://www.notion.so/<workspace>/<DB_ID>?v=...` または `https://www.notion.so/<DB_ID>?v=...`
3. `<DB_ID>` 部分（ハイフンを含む32文字のハッシュ、または連続した32文字）をコピー ← **後で使います**

例:
```
https://www.notion.so/myws/abcdef0123456789abcdef0123456789?v=xxxxx
                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                           この部分が DB ID
```

### 4. GitHub に Secrets を登録

1. 作ったリポジトリのページを開く
2. **Settings** → 左メニュー **Secrets and variables** → **Actions**
3. **"New repository secret"** をクリックして、以下の2つを登録：

| Name | Secret |
|---|---|
| `NOTION_TOKEN` | 手順 3-1 でコピーしたシークレット |
| `NOTION_DATABASE_ID` | 手順 3-3 でコピーしたDB ID |

> 一度保存すると中身は二度と表示されません（編集時はUpdateで上書き）。これは正常な動作です。

### 5. 動作テスト

1. リポジトリの **Actions** タブを開く
2. 左メニュー **"Sync Notion to index.html"** を選択
3. 右上 **"Run workflow"** → **"Run workflow"** をクリック
4. 1〜2分待つと、緑のチェック ✅ が付きます

#### うまくいかなかった場合

実行ログ（赤い × の行をクリック）を見ると原因が出ます。よくあるパターン:

| エラー | 原因 | 対処 |
|---|---|---|
| `object_not_found` | 手順 3-2 を忘れている | DBにインテグレーションを接続 |
| `unauthorized` | NOTION_TOKEN が間違っている | Secrets を再登録 |
| `有効な単語が0件でした` | DB のプロパティ名が違う | 下記の **プロパティ名** セクション参照 |
| `Permission denied to push` | リポジトリの権限設定 | Settings → Actions → General → Workflow permissions で **"Read and write permissions"** に変更 |

### 6. GitHub Pages を有効化

1. リポジトリの **Settings** → 左メニュー **Pages**
2. **Source** を **"Deploy from a branch"** にする
3. **Branch** を `main` / `/(root)` にして **Save**
4. 1〜2分後、上部に `Your site is live at https://<ユーザー名>.github.io/<リポジトリ名>/` と表示される
5. そのURLをスマホでブックマーク／ホーム画面に追加すれば完了 🎉

---

## 📋 Notion DB のプロパティ名

スクリプトは以下のプロパティ名を期待します（**完全一致が必要**、大文字小文字も区別）：

| プロパティ名 | 推奨タイプ | 必須 |
|---|---|---|
| `番号` | Number | 任意（無くても動作） |
| `単語` | Title | **必須** |
| `意味` | Text | 任意 |
| `例文` | Text | 任意 |
| `品詞` | Select または Text | 任意（既定値: `noun`） |
| `習熟度` | Select または Text | 任意（既定値: `苦手`） |
| `skills` | Select または Text | 任意（既定値: `reading`） |

`単語` プロパティが空のレコードは自動でスキップされます。

> プロパティ名を変えたい場合は `sync_notion.py` の冒頭にある `PROP_*` 定数を書き換えてください。

---

## 🛠 運用のヒント

- **手動で同期したい時**: Actions タブから "Run workflow" を押すだけ
- **同期スケジュールを変更したい時**: `.github/workflows/sync.yml` の `cron` 行を編集（UTC 表記、JST から 9 時間引く）
- **同期されない日があった場合**: GitHub Actions の cron は数分〜十数分遅れることがあります（仕様）。心配な時は手動実行で確認
- **Notion DB に変更がない時**: スクリプトは「変更なし」を検知してコミットをスキップするので、リポジトリの履歴が無駄に汚れません

---

## ❓ よくある質問

**Q. 個人の Notion DB の中身がパブリックリポジトリで公開されてしまわない？**
A. はい、`index.html` 内の単語データはリポジトリで誰でも見られる状態になります。気になる場合はプライベートリポジトリ + GitHub Pages（要 GitHub Pro）にしてください。あるいは、機密性のある単語をDBに入れない運用で十分かもしれません。

**Q. ローカルで先にテストしたい**
A. ターミナルで以下を実行：
```bash
export NOTION_TOKEN="secret_xxxxx"
export NOTION_DATABASE_ID="abcdef0123456789..."
pip install requests
python sync_notion.py
```

**Q. 月の Actions 実行時間は足りる？**
A. パブリックリポジトリは Actions が無制限です。プライベートでも月 2,000 分の無料枠があり、この同期処理は1回 30秒程度なので、毎日2回 × 30日 = 30分しか使いません。
