# 香港議題雷達 · 自動化接手備忘

給下一個 Grok bot。當主對話用完額度，跟這份做。唔好改版面，唔好改 `engine/build.py`。

公開網站：https://allegrotto1.github.io/hk-issue-radar/
Repo：`allegrotto1/hk-issue-radar`
時區：`Asia/Hong_Kong`

## 你做咩

你只寫快報內容，每次只推一個檔：

`engine/data/reports/YYYY-MM-DD-HH.json`

推上去之後，已有的 GitHub Action（`.github/workflows/republish.yml`）自己重建首頁。你唔好自己建站。

## 自動化

系統唔支援「每 3 小時」一個排程，所以拆成每日固定時間。深夜雷達唔改。

| 名稱 | task_id | 幾時跑 | 寫邊個檔 |
|---|---|---|---|
| 香港議題雷達 09:00 | `2536d52b-af07-448e-a2d4-aabf98cd2b6e` | 每日 09:00 | `YYYY-MM-DD-09.json` |
| 香港議題雷達 12:00 | `9a78a220-95cb-4ec8-9093-cb9d2564118a` | 每日 12:00 | `YYYY-MM-DD-12.json` |
| 香港議題雷達 15:00 | `b67eea20-187d-45ab-950d-21fad5589d7e` | 每日 15:00 | `YYYY-MM-DD-15.json` |
| 香港議題雷達 18:00 | `65d67806-ea1a-489d-8c26-02b760e677ba` | 每日 18:00 | `YYYY-MM-DD-18.json` |
| 香港議題雷達 21:00 | `489d88da-3658-4498-b785-c9907c1f667d` | 每日 21:00 | `YYYY-MM-DD-21.json` |
| 香港議題雷達 00:00 | `7458c674-4d69-4316-b0e6-d4bced4411a9` | 每日 00:00 | `YYYY-MM-DD-00.json` |
| 香港議題雷達早上快報 | `6d0d110f-5857-40f2-bbbc-f27bd511f321` | 每日 08:00 一次 | `YYYY-MM-DD-08.json` |

只寫 09、12、15、18、21、00，共 6 次。08:00 只由早上快報寫。其他鐘唔寫。

如果而家唔係呢啲鐘，即刻停，唔好寫檔，唔好 push。

## 禁止

- `publish_pages.sh`、`republish.sh`、`rsync`、`tar`、整個資料夾上傳
- `git add -A`、`git add .`、`git add -u`
- 複製頁面去 `/workspace/public`
- 覆蓋或刪除其他檔
- 估 thread 編號、估個人頁數字、估分數、估回覆數
- 寫真名、相片、或其他身份資料
- 由用戶名判斷金主、操盤方、水軍、係咪普通人

push 之前用 `git diff --cached --name-only` 確認只有當期一個 JSON。多過一個就唔好 push。

## 步驟

1. `gh repo clone allegrotto1/hk-issue-radar /tmp/hk-issue-radar`。已有就 `git fetch` 並 `reset --hard origin/main`。
2. 打開 https://lihkg.com/category/1?order=hot。冇列表就改讀 https://lihkg.com/category/1，summary 寫明不是已確認熱門。只抄真的看見的標題。
3. 每一條都要有帖文連結 `https://lihkg.com/thread/數字/page/1`。今輪睇唔到，但同一條今日已有，就沿用。兩邊都唔見就留空。
4. 樓主花名寫入 `evidence.author`。個人頁必須寫入 `evidence.author_url`，格式 `https://lihkg.com/profile/數字`。卡上有就抄 href。卡上唔見，就開帖，或讀 `https://lihkg.com/api_v2/thread/數字/page/1` 入面 `response.user.user_id`。同一條今日已有就沿用。
5. 留言數同讚數一定要由熱門列表面抄，唔好留空。每張卡右上角有兩個數：言論泡泡旁邊係回覆數（例如 54、46、63），拇指旁邊係淨評分（例如 17、14、-9）。回覆數寫入 `issue.replies`，淨評分寫入 `data.value`。唔好寫「約 N 頁」。唔好因為 API 限流就留空。
   - 列表頁真係睇唔到呢兩個數，先用 API 的 `response.no_of_reply`。
   - API 也開唔到，就開帖拉去最後一頁，讀最後一則留言編號當總回覆數。
   - 最後都唔見，先寫 `null`，並在 `seen` 話明開唔到。唔好估。
6. 寫 `viewpoints`：邊一邊多、邊一邊少、有冇互相反駁。每個有 `label`、`summary`、`share`。唔好只寫「只有列表標題」。
7. `seen` 要形容帖文講乜、留言爭乜，唔好只寫標題同分數。
8. `data` 每個有 `metric`、`value`、`comparison`。`metric` 寫「連登熱門列表淨評分（讚減踩）」。正代表讚多過踩，負代表踩多過讚，要寫出呢句。
9. 分數起跌：對照同一條 `/thread/數字` 上一版的 `data.value`。變動大過 30，在 `comparison` 寫明係列表刷新（帖仍在、觀點未變）定留言轉向（由讚變踩或由踩變讚）。上一輪未見就寫「上一輪未見」。
10. 五類都要有：內地、香港政府官員、香港時事、香港經濟、青年。青年包括青年政策、教育、青年問題。只用仍在這一頁的標題。某類唔見就在 summary 寫明，唔好撰。why 寫明屬哪一類。`status` 只可以是 `new`、`tracking`、`shift`、`cooling`。
11. 每一條 `evidence` 必須有 `evidence_id`，例如 `L1`、`L2`。唔好留空。缺呢個，`build.py --strict` 會失敗，成日首頁都唔會更新。
12. 推送前自己查：每一個有 `author` 的 evidence 都要有 `author_url` 同 `evidence_id`；每一條都要有 `seen`、`viewpoints`、`data`、`replies`。有缺就先補。
13. 只寫入 `/tmp/hk-issue-radar/engine/data/reports/YYYY-MM-DD-HH.json`。
14. 只可以 `git add` 呢一個檔。commit，`push origin HEAD`。推唔上就再試一次。仍然失敗，回覆寫明失敗，唔好話已經上線。

做完用兩句話講五類各係邊一條，以及每一條有冇實際回覆數。

## JSON 格式

```json
{
  "schema_version": 1,
  "mode": "live",
  "window": { "start": "2026-10-16T09:00:00Z", "end": "2026-10-16T10:00:00Z" },
  "generated_at": "2026-10-16T09:05:00Z",
  "summary": "四類各係邊一條，有冇缺類。",
  "sources": { "url": "https://lihkg.com/category/1?order=hot", "failed": [] },
  "issues": [
    {
      "issue_id": "HK-...",
      "name": "標題",
      "status": "new",
      "seen": "樓主講乜、留言爭乜。回覆 191。",
      "replies": 191,
      "viewpoints": [
        { "label": "批評成效", "summary": "留言大概過半指反詐失敗。", "share": "留言大概過半", "evidence_ids": ["L1"] }
      ],
      "data": [
        {
          "metric": "連登熱門列表淨評分（讚減踩）",
          "value": "191",
          "comparison": "回覆 191；分數正代表讚多過踩；上一輪 97。",
          "evidence_ids": ["L1"]
        }
      ],
      "why": "青年。本頁仍見。",
      "verification": { "status": "unverified", "note": "未對官方原文。" },
      "evidence": [
        {
          "evidence_id": "L1",
          "url": "https://lihkg.com/thread/4167926/page/1",
          "platform": "連登",
          "author": "樓主花名",
          "author_url": "https://lihkg.com/profile/187437",
          "published_at": null,
          "observed_at": "2026-10-16T09:05:00Z",
          "read_level": "opened",
          "note": "熱門排序頁對上該標題。"
        }
      ],
      "limits": "不把標題當成事實。",
      "next_steps": "下一輪再睇呢帖仲在唔在熱門第 1 頁。"
    }
  ]
}
```

`window.start` 係該小時香港時間的 UTC。香港 = UTC+8。

## 已知情況

- 回覆數同淨評分由熱門列表頁右上角抄：泡泡係回覆，拇指係分數。API 限流唔影響呢兩個數。用手機 User-Agent：`Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15`。
- 每一條 `evidence` 必須有 `evidence_id`。缺呢個，重建會失敗，首頁唔會更新。
- 政策核實同 Threads 追蹤唔做。用戶已講明做唔到。
- 由 2026-10-16 起，每小時改為每 3 小時：09、12、15、18、21、00。深夜雷達 08:00 唔改。
- 由 2026-10-17 起加第五類「青年」：青年政策、教育、青年問題。熱門頁冇就在 summary 寫明，唔好撰。why 寫明屬哪一類。已確認全部 7 條自動化（09/12/15/18/21/00 + 08:00 早上快報）prompt 都已包含第五類。
- 最新一份截至 2026-10-16 21:00。下一份係 00:00。
