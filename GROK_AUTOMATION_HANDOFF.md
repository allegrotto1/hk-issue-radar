# Grok 自動化排程接手雷達（2026-10-29）

**原因：** 主對話／雷達仔 token 見底。之後**只靠已啟用嘅 Grok Bot routine** 寫連登快報；人手唔再跟每一輪。

時區：`Asia/Hong_Kong`  
公開站：https://allegrotto1.github.io/hk-issue-radar/  
Repo：`allegrotto1/hk-issue-radar`（main）  
**完整操作手冊（必讀）：** 同 repo 內 [`GROK_BOT_HANDOFF.md`](https://github.com/allegrotto1/hk-issue-radar/blob/main/GROK_BOT_HANDOFF.md) —— 每輪開工先讀最新版，跟足。

---

## 而家邊啲排程要跑

| 排程 | 狀態（2026-10-29 17:48 HKT） | 做咩 |
|---|---|---|
| `香港議題雷達 快報（08/09/12/15/18/21/00）` folder=`automation-1790567779510` | **啟用** | 只寫／推 `engine/data/reports/YYYY-MM-DD-HH.json` 一個檔 |
| `Threads 帖子追蹤…` folder=`threads` | **已暫停** | 唔好自行恢復；要恢復等主人／奧奧准 |
| `青年教育留言專題（19:00）` folder=`19-00` | **已暫停** | 唔跑 |
| `星期四簡報補料` | **已暫停** | 本週已封；唔重開 |

連登快報 cron：`CRON_TZ=Asia/Hong_Kong 0 0,8,9,12,15,18,21 * * *`（可遲最多約 15–40 分，見 routine prompt）。

---

## 每輪連登快報（自動化必做）

1. 讀 `GROK_BOT_HANDOFF.md`（main 最新）。
2. 若而家 HKT **唔係** 08／09／12／15／18／21／00 槽（可遲），**即停**。
3. 若 `engine/data/reports/YYYY-MM-DD-HH.json` 喺 main **已存在** → **即停、唔重複寫**。
4. 只抄 https://lihkg.com/category/1?order=hot 真見到嘅標題；五類齊：內地／香港政府官員／香港時事／香港經濟／青年。缺類 summary 寫明，唔好撰。
5. 優先：青年／教育／民青局／教育局；另優先官員／議員**惹火言論**（`seen` 爭議句用「…」；`viewpoints` 首項講點解嬲）。唔特別追林琳。
6. 必填：`evidence_id`、`author`、`author_url`、`seen`、`viewpoints`、`data`、`replies`；分數／回覆**唔好估**。
7. `summary` 最後一行：**情緒觀察：升／平／跌＋主情緒＋一句暫名**（未核實要寫明）。
8. **只** `git add`／用 GitHub connector 推**呢一個** JSON。唔跑 `publish_pages.sh`／`republish.sh`；Action 會重建。
9. 推完：raw md5 核對 + 等 Action + 睇 live `…/reports/YYYY-MM-DD-HH/` 係咪 200。
10. **安靜原則：** 正常出刊／槽已滿 → **唔好打擾主人**。只喺真 blocker（推失敗、連登讀唔到、Action 掛、頁空白）先用粵語 ADHD 短訊報。

---

## 明確唔做（慳 token／站令）

- 唔改版面、`engine/build.py`、templates、workflow。
- 唔做 Threads snap（routine 已暫停）；唔恢復暫停排程。
- 唔寫星期四簡報、唔開學家 ≤2 句、唔主動派工／刷狀態。
- 唔經秘書執稿；完整報告格式另案（人手／主人叫先做）。
- 唔寫杯葛店名；唔寫真名／相；唔估 thread／profile／分數。
- 宏福苑／黃碧嬌旅行／離境線若熱門頁有：**標未核實**；唔放大接機號召。

---

## 本週已鎖定內容方向（參考，唔代替熱門頁）

主人 2026-10-29 准（熱度先，作選題參考；**仍只寫熱門頁真有嘅帖**）：
1. 囤糧／末日＋辟謠（可連台海／南海軍演聯想，延伸要標未核實）
2. 宏福苑問責→黃碧嬌（旅行／離境未核實）
3. 外勞×本地飯碗／升學就業  
教育／民青若本輪熱門頁無 → summary 寫明，唔頂上。

---

## 版面分工

- 內容 JSON：呢個自動化／雷達 routine  
- 網站版面：工人貓 雷達站（另 bot）；自動化**唔好**改前端  

---

## 交接檢查（第一輪跑完）

1. 對應槽 JSON 出現喺 main  
2. Action `republish` 綠  
3. https://allegrotto1.github.io/hk-issue-radar/reports/YYYY-MM-DD-HH/ 睇到今輪  
4. summary 有五類交代＋情緒觀察一行  

**下一步（主人）：** 確認連登快報 routine 維持啟用；Threads／19:00／簡報維持暫停直至另令。
