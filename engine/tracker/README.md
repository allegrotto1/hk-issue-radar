# Threads 帖文互動追蹤（tracker/）

追蹤時間：同每小時快報一齊，每日 **09:00–19:00** 每個整點，以及 **00:05 HKT**。
10:00 那一輪讀完之後，如果瀏覽數比對上一次快照增長**少於 10%**，`fetch_counts.py --snap` 會自動跑 `track.py stop`，寫入 `stopped_at`。之後唔再讀，頁面顯示「已停止追蹤」。

```bash
python3 track.py stop <url> [--at ISO]
```

Live: https://allegrotto1.github.io/hk-issue-radar/tracker/
Repo: `allegrotto1/hk-issue-radar`（branch `main`，root）。**只可以新增／更新 `tracker/` 入面嘅檔案**；
其他檔案（每小時快報等）由另一個助手管理，唔好改、刪或覆寫。

## 檔案
| 檔案 | 用途 | 需要 push？ |
|---|---|---|
| `data.json` | 追蹤帖文 + 每小時快照（由 `track.py` 寫） | 每小時 |
| `index.html` | 靜態頁，讀 `data.json` 顯示 | 只喺改動時 |
| `tracker.css` | 由 `../public/assets/site.css` 抄出嘅樣式 + 追蹤頁樣式 | 只喺改動時 |
| `track.py` / `README.md` | 本地工具／說明 | 唔使（只留喺本機） |

## 每小時流程
1. 用**無痕／未登入**視窗打開每個追蹤帖文，照抄 Threads 顯示嘅數字（原樣，例如 `2.2K`、`106K`、`3.4萬`）。
   冇顯示嘅數字就唔好填（記錄為 null）。Threads 冇引用（quote）數，唔使記。
2. 每個帖文跑一次 snap（`--at` 用實際讀數時間；唔填就用而家 HKT）：
   ```
   cd /workspace/hk-issue-digest/tracker
   python3 track.py snap <url> --likes 2.2K --replies 302 --reposts 78 --shares 193 --views 106K --at 2026-09-28T15:25+08:00
   ```
3. `python3 track.py report` 睇純文字表（可以直接貼落 chat）。
4. Push **只係 `tracker/data.json`**（`index.html`／`tracker.css` 有改先 push）。用 GitHub MCP connector
   `user-GitHub-xai` → `push_files`：
   ```
   owner: allegrotto1   repo: hk-issue-radar   branch: main
   message: "tracker: hourly snapshot 2026-09-28 15:25 HKT"
   files: [{ "path": "tracker/data.json", "content": <data.json 全文> }]
   ```
   push 之前先確認檔案路徑全部以 `tracker/` 開頭。之後用 `get_commit` 睇 commit 檔案清單，確認冇掂到其他檔案。
   Pages 約 1–3 分鐘更新：`curl -s https://allegrotto1.github.io/hk-issue-radar/tracker/data.json | python3 -m json.tool`
5. 檔案大小：connector 大約 34KB 以上會失敗，保持每個檔案 < 20KB。每個快照約 320 bytes，
   兩個帖文一日約 15KB。`track.py` 超過 16KB 會提示；到時跑
   `python3 track.py thin`（保留首個快照、最近 24 個，之前每 6 小時留一個）。

## 自動讀數：`fetch_counts.py`（headless、未登入）
桌面瀏覽器無痕視窗有時會出「Say more with Threads」硬登入牆；用 shell 嘅 headless Chrome
（`--incognito` + 每個帖文一個全新暫存 profile，冇 cookie、冇登入）通常仲讀到數字。
```
cd /workspace/hk-issue-digest/tracker
python3 fetch_counts.py                  # 只讀，JSON 輸出到 stdout（進度／錯誤去 stderr）
python3 fetch_counts.py --snap           # 讀完逐個帖文跑 track.py snap（--at = 實際讀數時間 HKT）
python3 fetch_counts.py --only DdyCsmTkt3H --snap   # 只讀指定帖文（id 或網址，可重複）
```
- 只讀首個快照 ≤ 7 日嘅帖文（`--max-age-days`）；截圖存 `/workspace/tracker-shots/<時間>-<id>.png`。
- 數字照 Threads 顯示（預設 `--lang en-US`，即 `2.3K`、`406K`；英文介面 1,000 以上會縮寫，
  所以由 `2,351` 變 `2.3K` 唔係跌）。冇顯示嘅數字記 `-`（null）；全部冇就唔 snap 並報告，同時存 HTML。
- 同對上一次快照比：有數字明顯下跌（縮寫數 >12%、精確數 >3%）或者消失，會自動重讀一次；仍然可疑就唔 snap
  （確認冇問題先加 `--force`）。其他選項：`--wait 25`、`--retries 1`、`--save-html`、`--shots DIR`。
- 只會關彈出視窗（Escape／彈窗嘅關閉掣），**永遠唔登入、唔撳讚／回覆／轉發／分享／追蹤**。
- 只用 Python 標準庫 + Chrome DevTools protocol（唔使 Playwright）。
- 跑完照舊 `python3 track.py report` 檢查，然後按上面第 4 步 push `tracker/data.json`。

## 加新帖文
```
python3 track.py add <url> --summary "中性摘要（唔寫回覆者帳戶）" [--tag 外勞入侵] [--posted-rel 23h] [--at ISO]
```
`--posted-rel` 係 Threads 顯示嘅相對時間，會推算 `estimated_posted_at`（標明屬估算）。

## 內容守則
- 摘要要中性；唔好寫回覆者帳戶名；作者 handle 只會因為喺網址入面出現。
- **任何地方都唔好寫杯葛／點名清單上嘅公司或商戶名稱。**
- 頁面已列明：未登入每小時讀數、縮寫數字令百分比只屬約數、冇引用數、樣本由編輯揀選唔具代表性，以及網站免責聲明。
