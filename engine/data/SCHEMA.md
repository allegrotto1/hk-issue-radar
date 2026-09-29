# Hourly report JSON schema (`schema_version: 1`)

## ⚠️ 編輯優先次序：新議題、熱度優先（用戶 2026-09-29 10:52 HKT 指示，凌駕其他排序習慣）

每一期快報嘅主要任務係**搵新嘅議題，按熱度排先後**，唔係重複報道已追蹤嘅舊議題。

1. **先搵新**：每期都要主動搵上一期未出現過嘅議題（連登熱門／時事台／吹水台、Threads 搜尋、新聞、政府新聞公報）。唔好因為冇「重大」新議題就只寫舊議題；但亦唔好為咗有新議題而硬塞（冇就寫明今期冇新發現）。
2. **按熱度排**：`issues` 陣列次序就係網頁顯示次序（`build.py` 唔會重新排序），「重點」亦取頭 1–3 個。由熱到冷排列，新發現而熱度高嘅放最前。
3. **熱度只可以用實際見到嘅訊號**：連登淨讚分數同回覆活躍程度、Threads 顯示嘅瀏覽／讚／回覆、同一窗口內出現喺幾多個獨立來源或傳媒。唔可以估數或者作數；每個議題要寫明熱度根據（例如「連登熱門第 1 位，淨分 733」）。
4. **舊議題讓位**：持續追蹤但本小時冇明顯新發展嘅議題，壓縮成一兩句或者放後面；降溫中嘅議題放最尾，唔好霸住前面位置。仍然最多 5 個議題 + 2 條線索。
5. 其他規則照舊（證據連結、唔寫用戶名、唔寫抵制清單商戶名、免責聲明、檔案上載後核對 md5）。


One file per hourly report: `data/reports/YYYY-MM-DD-HH.json`.

* The **filename is the report ID** and means the *HKT* date + hour of the observation window
  start (e.g. `2026-09-28-11.json` = window starting 11:00 HKT = 03:00 UTC). If it disagrees
  with `window.start`, the build warns and the filename wins.
* **All timestamps are ISO 8601 with a zone, stored in UTC** (`2026-09-28T03:00:00Z`).
  Naive timestamps are rejected. Everything is displayed in Asia/Hong_Kong (HKT).
* **All strings are untrusted**: they are HTML-escaped on output; no HTML/Markdown is interpreted.
  Links are only rendered for absolute `http(s)` URLs; anything else is shown as disabled text.
* "Text" below means **a string or an array of strings** (each array item / blank-line-separated
  block becomes a paragraph).
* Unknown fields are ignored. Invalid files are skipped with an error (exit code 2), or abort
  the build with `--strict`.

## Top level

| field | type | req. | notes |
|---|---|---|---|
| `schema_version` | int | ✔ | must be `1` |
| `mode` | `"fixture"` \| `"live"` | ✔ | `fixture` = synthetic preview data: page gets a banner + `noindex`, excluded from sitemap |
| `window.start`, `window.end` | UTC ISO | ✔ | observation window, half-open `[start, end)` |
| `generated_at` | UTC ISO | ✔ | 生成時間 |
| `summary` | text | | optional 本輪摘要 shown in the info panel |
| `sources` | object | | see below (實際可讀來源 / 來源失敗／缺口) |
| `issues` | array of Issue | | main issues, **max 5** rendered (extra ones dropped with a warning) |
| `early_leads` | array of Issue | | early leads, **max 2** rendered; status defaults to 早期線索 |
| `tracking` | array of Tracking | | 持續追蹤與更正 |
| `usage` | object | | 用量, see below |

### `sources`

```json
{
  "readable": [ { "name": "…", "platform": "…", "items": 42, "note": "…" } ],   // or plain strings
  "failed":   [ { "name": "…", "reason": "…" } ],                               // or plain strings
  "gaps":     [ "known coverage gap …" ]                                        // text
}
```

### Issue (used by `issues[]` and `early_leads[]`)

| field | type | req. | card section |
|---|---|---|---|
| `issue_id` | string | ✔ | 議題 ID (stable across hours so an issue can be tracked) |
| `name` | string | ✔ | 議題名稱 (card heading) |
| `status` | `new` \| `tracking` \| `shift` \| `cooling` \| `lead` (or the Chinese label) | | 狀態 → 新發現 / 持續追蹤 / 觀點變化 / 降溫 / 早期線索. Other strings shown as-is |
| `observed.start`, `observed.end` | UTC ISO | | 觀察時段; defaults to the report window |
| `seen` | text | | 今輪看到甚麼 |
| `viewpoints` | array | | 觀點分布: `{ "label", "share" (free text e.g. "約 40%"), "summary", "evidence_ids": ["E1"] }` or strings |
| `data` | array | | 數據與比較: `{ "metric", "value", "comparison", "evidence_ids" }` or strings |
| `why` | text | | 為甚麼列入 |
| `verification` | object | | `{ "status": "verified" \| "partially_verified" \| "unverified" \| "disputed", "note": "…" }` → 已核實 / 部分核實 / 未核實 / 存在矛盾 |
| `evidence` | array of Evidence | | 證據與核實狀態 list |
| `limits` | text | | 限制 |
| `next_steps` | text | | 下一步 |

### Evidence

| field | type | req. | notes |
|---|---|---|---|
| `evidence_id` | string | ✔ | e.g. `E1` (referenced by `evidence_ids`) |
| `url` | string | | real, absolute http(s) URL of the source actually read. Never invent URLs |
| `platform` | string | | source/platform name |
| `published_at` | UTC ISO \| null | | 發布時間 (null → 時間不詳) |
| `observed_at` | UTC ISO \| null | | 觀測時間 (when the collector saw it) |
| `read_level` | `full` \| `partial` \| `snippet` \| `title_only` \| `metadata` \| `failed` | | 讀取完整程度 → 完整讀取 / 部分讀取 / 只讀摘要／片段 / 只有標題 / 只有元數據 / 讀取失敗 |
| `note` | string | | optional remark |

### Tracking

`{ "issue_id", "name", "kind": "follow_up" | "correction" | "shift" | "cooling" | "resolved", "text": text, "related_report": "YYYY-MM-DD-HH" }`
→ 持續追蹤 / 更正 / 觀點變化 / 降溫 / 已完結. `related_report` links to that report if it exists on the site.

### `usage`

Known keys (all optional, numbers): `sources_attempted`, `sources_ok`, `items_collected`,
`items_read_full`, `llm_calls`, `tokens_in`, `tokens_out`, `cost_usd`, `runtime_seconds`;
plus `notes` (text) and `extra` (object of label → value, rendered as extra rows).

## Fixed text

The mandatory disclaimer is hard-coded in `build.py` (not overridable from data):
「本報反映指定範圍內可取得的公開討論，不代表香港整體民意；未收集到不等於沒有相關討論。」

## Minimal example

```json
{
  "schema_version": 1,
  "mode": "live",
  "window": { "start": "2026-09-28T03:00:00Z", "end": "2026-09-28T04:00:00Z" },
  "generated_at": "2026-09-28T04:05:00Z",
  "issues": [
    { "issue_id": "HK-0001", "name": "…", "status": "new",
      "evidence": [ { "evidence_id": "E1", "url": "https://…", "observed_at": "2026-09-28T03:40:00Z", "read_level": "full" } ] }
  ]
}
```

See `data/reports/2026-09-28-11.json` for a complete (synthetic, `mode: "fixture"`) example.
