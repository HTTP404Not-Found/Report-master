# 字體授權清單（LICENSES.md）

> 對應 SPEC.md §6.1 R6 + `fonts/README.md` §2-7
> 本檔彙整 report-master 依賴的所有字體授權條款、可再用範圍、版本。
> **本目錄不內含真字體檔**（見 README §8）。

---

## 1. 標楷體（DFKai-SB / KaiTi）

| 欄位 | 值 |
|------|----|
| 字體名 | 標楷體（DFKai-SB / KaiTi / KaiU） |
| 來源 | 教育部標準字體；國家發展委員會數位發展部 |
| 授權 | 政府釋出，免費供**公文、教學、學術研究**使用 |
| 商業出版 | 需另洽國家發展委員會 |
| 可否獨立散布 | ✅ 是（用於教學 / 學術 / 公文） |
| 變更 / 修改 | ❌ 禁止 |
| 來源連結 | https://www.cns11643.gov.tw/ （CNS11643 中文標準交換碼） |
| 取得方式 | macOS 內建 / Windows 內建 / Linux `apt install fonts-arphic-ukai` |
| 版本 | DFKai-SB（教育部 1990 年代定版，持續維護中） |

### 使用限制

- ✅ 公文（政府機關正式文件）
- ✅ 教學（學校教材、學習講義）
- ✅ 學術研究（論文、研究報告、學位論文）
- ⚠️ 商業出版（書籍、雜誌、商品包裝）需另洽授權
- ❌ 不得修改字體檔本身
- ❌ 不得宣稱為自有創作

### 替代字體（無法取得原版時）

| 替代 | 授權 | 安裝 |
|------|------|------|
| AR PL UKai（文鼎 PL 楷體） | Arphic Public License | `apt install fonts-arphic-ukai` |
| Droid Sans Fallback（內含楷體 fallback） | Apache 2.0 | `apt install fonts-droid-fallback` |
| Noto Serif CJK TC | SIL OFL 1.1 | Google Fonts / `apt install fonts-noto-cjk` |

---

## 2. Times New Roman

| 欄位 | 值 |
|------|----|
| 字體名 | Times New Roman |
| 來源 | Monotype（原始設計）／ Microsoft（系統內建版） |
| 授權 | **隨系統 / Office 內建即可合法使用**；不可獨立散布 |
| 商業使用 | ✅ 隨系統 / Office 內建 |
| 可否獨立散布 | ❌ 否（Monotype 商標字型） |
| 變更 / 修改 | ❌ 禁止 |
| 取得方式 | macOS 內建 / Windows 隨 Office / Linux 替代字體 |
| 版本 | Times New Roman PS MT（PostScript） |

### 使用限制

- ✅ 隨 macOS / Windows 系統內建使用（個人 / 商業皆可）
- ✅ 隨 Microsoft Office 安裝使用
- ❌ 不可將 .ttf 檔獨立散布、轉售、嵌入至獨立產品
- ❌ 不可在 web font 服務上提供 Times New Roman（需另洽 Monotype 授權）

### 替代字體（Linux / 跨平台散布）

| 替代 | 授權 | 特性 |
|------|------|------|
| Liberation Serif | SIL OFL 1.1（GPL-compatible） | metric-compatible，PDF 行數 / 表格寬度幾乎一致 |
| Tinos | Apache 2.0 | Google Fonts，metric-compatible |
| TeX Gyre Termes | GUST Font License | TeX Gyre 系列，metric-compatible |

**Report-master 推薦**：在 Linux 環境用 **Liberation Serif**（apt 安裝、metric-compatible）；跨平台 PDF 嵌入也可用此替代。

---

## 3. 授權決策流程

```
Q: 你能在 macOS / Windows 找到「標楷體.ttf」與「Times New Roman.ttf」嗎？
├─ 是 → 直接用
└─ 否（Linux / 容器環境）→
    Q: 是教學 / 學術 / 公文場景？
    ├─ 是 → AR PL UKai（apt install fonts-arphic-ukai）
    └─ 否（商業）→ 洽 Monotype / 教育部授權

Q: Linux 需要替代 Times New Roman？
├─ 是 → Liberation Serif 或 Tinos（metric-compatible）
└─ 否 → 跳過（不需英文場景）
```

---

## 4. 授權聲明範本（產出報告時引用）

在報告 `<head>` 或附錄加入：

```
本報告中文字體採用教育部標準字體（DFKai-SB / 標楷體），
授權來自國家發展委員會，供學術研究使用。
英文字體採用 Times New Roman（隨 Microsoft / macOS 系統內建）。
```

---

## 5. 版本紀錄

| 版本 | 日期 | 變更 |
|------|------|------|
| 1.0 | 2026-06-13 | 初版（Track A foundation） |

---

*fonts/LICENSES.md v1 — 對應 SPEC.md v0.3 §6.1 R6, 2026-06-13*
