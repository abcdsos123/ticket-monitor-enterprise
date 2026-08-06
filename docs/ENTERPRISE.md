# Enterprise 階段

Enterprise 只負責可靠性與遠端維運，不包含自動購票。

## 主要能力

1. Heartbeat：主循環每次更新 `runtime.json`。
2. Auto Restart：連續錯誤達門檻後重啟 Chrome。
3. Hot Reload：偵測 `config.json` 修改並重新載入。
4. Backup：定期將 `data/` 壓縮至 `backups/`。
5. Stats：記錄成功、失敗、手動檢查與重啟次數。
6. Discord Ops：可查健康狀態、Log、截圖、備份與重新載入設定。
