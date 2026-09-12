# 前處理工具現況

依據：[資料前處理與切分交接規格](../../docs/資料前處理與切分交接規格.md)。目前工具已能抽文、切段與產出 release，但驗證器未完整落實規格；不能以 `validated` 自動允許正式索引。

## 模組

`run.py` 清冊／流程／有限 QA → `extract.py` 逐頁文字與座標 → `segment.py` 結構單元 → `chunk.py` 檢索段 → `annotate.py` 欄位及引用候選；`common.py` 管版本、ID、條號與正規化。

## 已驗證的環境

- r1 重現：現有 `.venv_pre/bin/python`，Python 3.9.6、PyMuPDF 1.26.5。依賴版本記於 [requirements.txt](requirements.txt)。
- 舊 API：`backend/.venv/bin/python`，Python 3.12.14、PyMuPDF 1.24.9。不能替代 r1 抽取環境；實測會改變產物。
- 本次沒有安裝／升級任何套件；乾淨環境安裝與其他 Python 版本未驗證。

## 只讀回歸檢查

從 repo 根目錄執行：

```bash
.venv_pre/bin/python -m tests.preprocess.test_regression
```

這是 19 個自訂檢查，僅抽查前 500 個 section 的 quote，不涵蓋完整交接驗收。也能在現有 backend Python 跑通，因為此 runner 不重新抽取 PDF。

## 不要直接覆寫 release

`all`／`process` 直接寫入 `data/processed/releases/<release>`；`validate` 也會改 manifest 和 QA。程式雖在說明中提到 staging，實作尚未採用原子發布。預設 release 是 `r1`，所以不要把預設 CLI 當成無副作用檢查。

目前原件在 `data/raw/`，分類判定仍要求 `data/<分類>/`；來源布局修正、141 份基準與 12 份進件隔離、精確 chunk spans、完整 schema／hash、驗收 gate 都是待辦。本次只在 `/tmp` 複製程式並用來源雜湊確認的 symlink 重建舊布局，沒有把暫存結果發布到 repo。

重現結果與失敗明細見 [驗證報告](../../sysdoc/驗證報告.md)；修復工具與新 release 等使用者允許後再做。
