# 香港議題雷達（HK Issue Radar）

每小時整理指定範圍內嘅香港公開討論，**按議題**而唔係按平台。頁面語言係 zh-Hant-HK。

預覽入面打開網站就係首頁（重點、最新快報、按日存檔）。快報頁、當日存檔同 Threads 互動追蹤都可以由導覽進入。

產生器（純 Python 標準庫）：

```bash
python3 build.py --strict
mkdir -p public/tracker
cp tracker/index.html tracker/tracker.css tracker/data.json public/tracker/
```

網站路徑係 `/hk-issue-radar`（`config.json` 嘅 `base_path`）。唔好再拆 chunk／loader。

## ⚠️ 編輯優先次序：新議題、熱度優先（用戶 2026-09-29 10:52 HKT 指示，凌駕其他排序習慣）

每一期快報嘅主要任務係**搵新嘅議題，按熱度排先後**，唔係重複報道已追蹤嘅舊議題。

1. **先搵新**：每期都要主動搵上一期未出現過嘅議題（連登熱門／時事台／吹水台、Threads 搜尋、新聞、政府新聞公報）。唔好因為冇「重大」新議題就只寫舊議題；但亦唔好為咗有新議題而硬塞（冇就寫明今期冇新發現）。
2. **按熱度排**：`issues` 陣列次序就係網頁顯示次序（`build.py` 唔會重新排序），「重點」亦取頭 1–3 個。由熱到冷排列，新發現而熱度高嘅放最前。
3. **熱度只可以用實際見到嘅訊號**：連登淨讚分數同回覆活躍程度、Threads 顯示嘅瀏覽／讚／回覆、同一窗口內出現喺幾多個獨立來源或傳媒。唔可以估數或者作數；每個議題要寫明熱度根據（例如「連登熱門第 1 位，淨分 733」）。
4. **舊議題讓位**：持續追蹤但本小時冇明顯新發展嘅議題，壓縮成一兩句或者放後面；降溫中嘅議題放最尾，唔好霸住前面位置。仍然最多 5 個議題 + 2 條線索。
5. 其他規則照舊（證據連結、唔寫用戶名、唔寫抵制清單商戶名、免責聲明、檔案上載後核對 md5）。


Hourly "Hong Kong cross-platform issue tracker" digest (每小時議題快報), organised by issue.
Visual design cloned from the reference digest (Vercel-style, Geist fonts, light/dark).

```
python3 build.py                 # data/reports/*.json -> public/   (stdlib only, idempotent)
python3 build.py --strict        # abort on any invalid report file
python3 build.py --data DIR --out DIR --config FILE
python3 -m http.server -d public 8000   # preview at http://localhost:8000/
.venv-shots/bin/python shoot.py [--dark]  # full-page 1280px screenshots -> shots/ (playwright + system Chrome)
```

* Site title / subtitle / hero text / footer / `base_url` (canonical, sitemap) / `base_path`
  (sub-path hosting) live in `config.json`.
* Report schema: `data/SCHEMA.md`. Design CSS: `assets/base.css` (verbatim from reference) +
  `assets/extra.css` (issue-card extensions); both are inlined into every page.
* Output: `index.html`, `reports/YYYY-MM-DD-HH/index.html`, `days/YYYY-MM-DD/index.html`,
  `sitemap.xml`, `robots.txt`, `favicon.svg`, `404.html`. Built in a temp dir and swapped in.
* Exit codes: 0 ok · 1 fatal / `--strict` failure · 2 built but some files skipped.
