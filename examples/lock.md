---
# report_lock.md — Report-master 範例 (academic demo)
# 對應 docs/report_lock_schema.md §5 OK 範例
# 17 個 required 欄位齊備

schema_version: 1

fonts:
  cjk: 標楷體
  latin: Times New Roman

formatting:
  cover: {font_size: 22, bold: true, align: center}
  toc: {font_size: 20}
  title: {font_size: 22, bold: true, align: center}
  h1: {font_size: 18, bold: true}
  h2: {font_size: 16, bold: true}
  h3: {font_size: 14, bold: true}
  body: {font_size: 12, line_spacing: 1.5}
  table: {font_size: 12}
  caption: {font_size: 10, align: center}

page_size: A4
margins: {top: 2.5cm, bottom: 2.5cm, left: 3cm, right: 2cm}
line_spacing: 1.5
language_variant: zh-TW
citation_style: APA

output:
  docx_engine: pandoc
  embed_fonts: true

metadata:
  title: Report-master 範例報告
  author: Zero
  date: 2026-06-13

sections:
  - path: examples/section_1.html
    title: 第一章 緒論
---

# report_lock.md

> Report-master 範例 lock（academic, zh-TW）
> 產生時間：2026-06-13

執行合同：見上方 YAML frontmatter。Stage 2 / Stage 3 將以本檔為 single source of truth。