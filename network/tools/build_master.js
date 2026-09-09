// master_src.js（手書きの割当表）と data/terms.json（Notion同期）から data/proposers.json を作る
//   cd network/tools && node build_master.js
//
// 用語はページIDで持つ。Notion側で名前を変えても、前回の proposers.json に残ったIDで対応づけを保てる。
// terms.json に無い語（Notionから消えた／改名された語）は、前回のIDが分かる場合だけ引き継ぐ。
const fs = require("fs");
const path = require("path");

const SRC = require("./master_src.js");           // { P, I, T }
// 追加分ファイル（master_add*.js）があればマージする。語を足すときはここに追記していけばよい。
for (const f of fs.readdirSync(__dirname).filter((n) => /^master_add.*\.js$/.test(n)).sort()) {
  const add = require("./" + f);
  Object.assign(SRC.P, add.P || {});
  Object.assign(SRC.I, add.I || {});
  Object.assign(SRC.T, add.T || {});
  console.log("+ " + f + " をマージ");
}
const DATA = path.join(__dirname, "..", "data");
const termsPath = path.join(DATA, "terms.json");
const outPath = path.join(DATA, "proposers.json");

if (!fs.existsSync(termsPath)) {
  console.error("❌ " + termsPath + " がありません。先に sync_network.py を実行してください。");
  process.exit(1);
}
const terms = JSON.parse(fs.readFileSync(termsPath, "utf8")).terms;
const prev = fs.existsSync(outPath) ? JSON.parse(fs.readFileSync(outPath, "utf8")) : { termIdByName: {} };

const norm = (x) => (Array.isArray(x) ? { id: x[0], role: x[1] } : { id: x, role: "提唱" });
const errs = [];

// 人物・機関
const people = {};
for (const [id, [name, latin, aliases, year, note]] of Object.entries(SRC.P)) {
  people[id] = { id, name, latin: latin || "", aliases: aliases || [], year: year == null ? null : year, note: note || "" };
}
const insts = {};
for (const [id, [name, kind, family]] of Object.entries(SRC.I)) insts[id] = { id, name, kind, family };

// 名前 → ページID（今回の terms.json が優先。無ければ前回の対応表）
const idByName = {};
terms.forEach((t) => { idByName[t.名前] = t.id; });
const termIdByName = { ...(prev.termIdByName || {}), ...idByName };

// 割当
const out = {};
const carried = [], dropped = [];
for (const [name, m] of Object.entries(SRC.T)) {
  const id = termIdByName[name];
  if (!id) { dropped.push(name); continue; }
  if (!idByName[name]) carried.push(name);
  const proposers = (m.p || []).map(norm);
  proposers.concat((m.related || []).map(norm)).forEach((x) => {
    if (!people[x.id] && !insts[x.id]) errs.push("未知のID " + x.id + "（" + name + "）");
  });
  out[id] = { name, proposers, none: !!m.none, src: m.src || [], note: m.note || "" };
}
if (errs.length) { console.error(errs.join("\n")); process.exit(1); }

const unmapped = terms.filter((t) => !out[t.id]).map((t) => t.名前);

const payload = {
  _meta: {
    title: "提唱者マスタ（下書き）",
    generated: new Date().toISOString().slice(0, 10),
    source: "network/tools/master_src.js × data/terms.json",
    status: "Claude作成の下書き。役割（提唱／代表／関連／整理／機関）・原綴り・年・人物と機関の区分は要レビュー。",
    schools: ["リアリズム", "リベラリズム", "コンストラクティビズム", "批判理論", "その他"],
    roles: ["提唱", "代表", "関連", "整理", "機関"],
  },
  people,
  institutions: insts,
  termIdByName,
  terms: out,
};
fs.writeFileSync(outPath, JSON.stringify(payload, null, 1));

console.log(`✅ ${outPath}`);
console.log(`   人物 ${Object.keys(people).length}／機関 ${Object.keys(insts).length}／割当済みの語 ${Object.keys(out).length}／terms.json ${terms.length}語`);
if (carried.length) console.log(`   前回のIDで引き継いだ語: ${carried.length} 件 → ${carried.slice(0, 5).join("、")}`);
if (dropped.length) console.log(`   ⚠️ IDが分からず出力できなかった語: ${dropped.length} 件 → ${dropped.slice(0, 5).join("、")}`);
if (unmapped.length) console.log(`   ⚠️ master_src.js に未登録の語: ${unmapped.length} 件 → ${unmapped.slice(0, 10).join("、")}`);
