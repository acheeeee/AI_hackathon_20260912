# Repository guidance

本專案規則統一維護於 [AGENTS.md](AGENTS.md)，現況與驗證結果在 [sysdoc/README.md](sysdoc/README.md)。請先閱讀兩者，避免沿用舊 demo 架構說明。

需求／設計入口為 [docs/README.md](docs/README.md)。`docs/協作設計/` 同時記錄目標與逐階段實作狀態；以 [05 驗收](docs/協作設計/05-實作順序與驗收.md) 和 [06 交接](docs/協作設計/06-交接與下一步.md) 判斷哪些能力真的存在。

2026-09-12 使用者已依序授權：run／事件、Evidence 工具 adapter、固定假模型端到端、線上模型、BM25 gold 評估，以及僅在證據顯示不足時才加向量。每完成一階段必須：先 RED 後 GREEN、建立 focused commit、更新 05／06 與相關文件，並留下可由 Claude Code 重跑的命令與下一階段邊界。

目前已完成 Stage A、r3/BM25 證據底座、B1 run 持久化、B2 Evidence 工具 adapter、B3 固定假模型端到端，以及線上 AWS Bedrock AgentCore provider（見 [docs/協作設計/07](docs/協作設計/07-AgentCore部署與線上模型.md)，已用真實請求驗證）。下一階段補前端能上場的四個後端缺口（上傳建案、案件列表、程序審查、草稿生成），細節見 [docs/協作設計/06 §5.2](docs/協作設計/06-交接與下一步.md)。不要覆寫 r1/r2/r3、舊 KB 或原 PDF；前處理實驗使用新 release ID。不要碰未追蹤的 `.claude/launch.json`。憑證只能從環境讀取，不得寫入 DB、Git、文件或 log。
