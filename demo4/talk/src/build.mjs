#!/usr/bin/env node
/**
 * build.mjs — 合併 talk/src/section-*.md 為 slides.md,並以 marp-cli 輸出到 talk/dist/。
 *
 * 用法(在 talk/src/ 執行): node build.mjs [html|pdf|pptx ...]   (預設 html,可同時多個)
 *
 * 合併規則:deck-header.md(Marp 全域 frontmatter)+ 各 section 檔依檔名順序,
 * 剝除每檔開頭的 YAML frontmatter(那是 talk-flow 的 metadata,不是投影片內容),
 * 以 `---` 分隔頁接合。slides.md 與 dist/ 皆為產物,勿手改。
 */
import { readdirSync, readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { execSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = dirname(fileURLToPath(import.meta.url));
const DIST = join(SRC, "..", "dist");
const OUT_FLAGS = {
  html: [],
  pdf: ["--pdf", "--allow-local-files"],
  pptx: ["--pptx", "--allow-local-files"],
};

const targets = process.argv.slice(2).length ? process.argv.slice(2) : ["html"];
for (const t of targets) {
  if (!OUT_FLAGS[t]) {
    console.error(`不支援的輸出格式:${t}(可用:${Object.keys(OUT_FLAGS).join(" | ")})`);
    process.exit(1);
  }
}

const headerPath = join(SRC, "deck-header.md");
if (!existsSync(headerPath)) {
  console.error("找不到 deck-header.md(Marp 全域 frontmatter)— 請在 talk/src/ 執行");
  process.exit(1);
}

const stripFrontmatter = (text) => {
  const m = text.match(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/);
  return m ? text.slice(m[0].length) : text;
};

const files = readdirSync(SRC)
  .filter((f) => /^section-\d{2,}-.*\.md$/.test(f))
  .sort();
if (files.length === 0) {
  console.error("talk/src/ 沒有任何 section-*.md,先執行 /section-impl");
  process.exit(1);
}

const header = readFileSync(headerPath, "utf8").trimEnd();
const parts = files.map((f) => stripFrontmatter(readFileSync(join(SRC, f), "utf8")).trim());
const merged = `${header}\n\n${parts.join("\n\n---\n\n")}\n`;
writeFileSync(join(SRC, "slides.md"), merged);

const pages = merged.split(/\r?\n---\r?\n/).length - 1; // 第一塊是 frontmatter
console.log(`合併 ${files.length} 個 section、共 ${pages} 頁 → slides.md`);
for (const f of files) console.log(`  - ${f}`);

mkdirSync(DIST, { recursive: true });
for (const t of targets) {
  const out = join(DIST, `slides.${t === "html" ? "html" : t}`);
  const cmd = ["npx", "-y", "@marp-team/marp-cli", "slides.md", "--html", "--theme-set", ".", ...OUT_FLAGS[t], "-o", JSON.stringify(out)].join(" ");
  // PUPPETEER_TIMEOUT:pdf/pptx 走無頭瀏覽器,45 頁 + 內嵌截圖會超過 marp-cli 預設的 30 秒。
  execSync(cmd, {
    cwd: SRC,
    stdio: "inherit",
    env: { PUPPETEER_TIMEOUT: "300000", ...process.env },
  });
  console.log(`✓ 輸出 ${out}`);
}
