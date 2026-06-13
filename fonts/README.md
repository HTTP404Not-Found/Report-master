# fonts/ — 字體 Bundle

> 對應 SPEC.md §6.1 R6（無 CJK/字體策略）+ §3.4.1（字體鎖死規則）
> 本目錄**不內含真字體檔**（授權 + 體積考量）；改放字體授權 metadata + 下載/安裝指引。
> `scripts/config.py` 在 `init` 時做 fail-fast 檢查，缺字體立刻 raise。

---

## 1. 字體策略（硬性規則）

| 用途 | 字體 | 固定？ |
|------|------|--------|
| 中文（CJK） | **標楷體** | ✅ 不可覆寫 |
| 英文（Latin） | **Times New Roman** | ✅ 不可覆寫 |

**混排範例**（HTML/CSS）：
```css
font-family: '標楷體', 'Times New Roman', serif;
```

瀏覽器 / weasyprint / pandoc 會自動依字元範圍 fallback（中文用前者、英文用後者）。

---

## 2. 字體取得方式

### 2.1 標楷體（DFKai-SB / KaiTi）

| 來源 | 授權 | 取得方式 |
|------|------|----------|
| **教育部標準字體**（DFKai-SB / bkai00mp.ttf） | 國家發展委員會 / 教育部免費商用 | 從 [教育部國語字典](https://www.edu.tw/) 或 [台灣 CNS11643 字體下載](https://www.cns11643.gov.tw/) 下載 |
| macOS 系統內建 | 已授權 | `/System/Library/Fonts/Kaiti.ttc` 或 `/Library/Fonts/標楷體.ttf` |
| Windows 系統內建 | Microsoft 授權 | `C:\Windows\Fonts\kaiu.ttf` |
| Linux（文鼎 PL 楷體） | Arphic Public License | `apt install fonts-arphic-ukai` 或 `fonts-droid-kaiti` |

**授權備註**：教育部標準字體供公文 / 教學 / 學術研究**免費商用**；商業出版品需另洽國家發展委員會。

### 2.2 Times New Roman

| 來源 | 授權 | 取得方式 |
|------|------|----------|
| Microsoft Office | Microsoft 授權（隨 Office 安裝） | 從 Office 安裝目錄抽 `times.ttf`、`timesbd.ttf`、`timesi.ttf`、`timesbi.ttf` |
| macOS / iOS | Apple 授權 | `/System/Library/Fonts/Times New Roman.ttf` |
| Linux | 替代：Liberation Serif（metric-compatible） | `apt install fonts-liberation` |
| Google Fonts | Apache 2.0 | [Tinos](https://fonts.google.com/specimen/Tinos)（metric-compatible 替代） |

**授權備註**：Times New Roman 為 Monotype 商標字型，**隨 Microsoft Office / macOS 內建**即可合法使用；不可獨立散布。如無授權，使用 Liberation Serif 或 Tinos（metric-compatible）替代。

---

## 3. Linux 安裝指令（推薦）

```bash
# Ubuntu / Debian
sudo apt install fonts-arphic-ukai fonts-liberation

# 或單獨安裝
sudo apt install fonts-droid-kaiti       # 近似標楷體
sudo apt install fonts-liberation         # 替代 Times New Roman
```

安裝後驗證：

```bash
fc-list | grep -i "kai\|times\|liberation serif"
```

預期輸出（節錄）：

```
/usr/share/fonts/truetype/arphic/ukai.ttc: AR PL UKai CN:style=Book
/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf: Liberation Serif:style=Regular
```

---

## 4. macOS / Windows

macOS 預設已內建「標楷體.ttf」與「Times New Roman.ttf」，無需額外安裝。

Windows 預設已內建「標楷體」（KaiU / DFKai-SB）與「Times New Roman」（隨 Office 安裝）。

---

## 5. 找不到字體時的 fallback

`scripts/config.py` 在缺字體時 `raise FontNotFoundError`，**不會 fallback**。理由：

- 替換字體會破壞排版一致性（行距、字寬不同）
- 靜默 fallback 會讓報告在不同機器上看起來不同
- **強制明確失敗** 比「看起來能用但其實怪怪的」更專業

例外（環境變數開啟時可暫時關閉檢查）：

```bash
REPORT_MASTER_SKIP_FONT_CHECK=1   # 僅限 CI / 測試環境使用
```

---

## 6. 字體檢查指令

```bash
# 透過 project_manager 檢查
python scripts/config.py check

# 直接用 fc-list 驗證
fc-list :lang=zh-tw | grep -i "kai\|ming\|hei"   # 標楷體 / 細明體 / 黑體
fc-list :lang=en | grep -i "times\|serif"        # Times / Serif 系列
```

---

## 7. 字體授權（License）

完整授權條款見 `LICENSES.md`。重點：

- **標楷體（教育部標準字體）**：政府釋出，免費供公文 / 教學 / 學術研究使用；商業出版需另洽
- **Times New Roman（Microsoft / Apple）**：隨系統 / Office 安裝；不可獨立散布
- **替代字體（Liberation Serif / Tinos）**：允許獨立散布，無授權問題

---

## 8. 不要做的事

- ❌ 不要把 .ttf / .otf / .ttc 檔 commit 進本目錄
- ❌ 不要繞過 `config.py` 的字體檢查（除非在 CI 環境明確設定環境變數）
- ❌ 不要在 `report_lock.md` 覆寫 `fonts.cjk` 或 `fonts.latin` 為其他字體（schema 強制）

---

*fonts/README.md v1 — 對應 SPEC.md v0.3 §3.4.1 + §6.1 R6, 2026-06-13*
