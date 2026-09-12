# 現役前端

Vue 3＋TypeScript＋Vite＋Pinia＋Element Plus。唯一 route `/` 顯示五步驟 wizard；步驟狀態由 Pinia 管理。

## 依據與狀態

- 視覺／原始流程：[docs/design](../docs/design/README.md)。
- 下一階段互動與 API：[docs/協作設計](../docs/協作設計/README.md)，尚未實作。
- 實際已完成程度：[sysdoc](../sysdoc/README.md) 與 [驗證報告](../sysdoc/驗證報告.md)。

五個頁面在 `src/views/steps/`：Upload、Extract、Gate、Select、Draft。API client 在 `src/api/client.ts`，型別在 `src/types/appeal.ts`，跨步驟狀態在 `src/stores/case.ts`。

## 指令

```bash
npm ci                 # 新環境依 package-lock 安裝；本次驗證復用既有套件，沒有重裝
npm run dev            # :5173，/api 代理至 localhost:8000
npm run build          # 型別檢查＋正式打包
npm run test:unit -- --run  # 目前沒有測試檔，會 exit 1
./node_modules/.bin/oxlint .
./node_modules/.bin/eslint .
```

`npm run lint` 帶 `--fix`，會改動程式；只盤點時使用上述兩個無修正指令。Node 版本限制以 `package.json` 為準，本次使用 Node 26.5.0、npm 11.17.0。

## 執行邊界

前端必須連到 [backend/api.py](../backend/api.py) 才能分析、生成草稿與匯出。API 未啟動時，畫面載入不代表功能可用。正式部署需要另外配置 `/api` 反向代理，Vite 開發代理不會被打包進正式網站。

目前沒有案件持久化；重新整理會回到上傳頁。程序檢核狀態只在 Gate 元件記憶體中；引用勾選只在前端，生成草稿不會送出勾選項目。這些是待修缺口，不能依畫面文字宣稱已完成。
