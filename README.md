# Ticket Monitor Enterprise

使用 Python 建立的多平台票券監控系統，目前支援：

- Tixcraft 拓元
- KKTIX
- Discord Slash Commands
- 票況變動通知
- Selenium 與 nodriver 雙瀏覽器架構
- 瀏覽器 Profile 分離
- 狀態保存與歷史紀錄
- 健康檢查與備份

## 系統架構

- Tixcraft：Selenium
- KKTIX：nodriver
- 通知：Discord Bot
- 設定：JSON + `.env`
- Python：建議使用 Python 3.12

## 安裝

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt