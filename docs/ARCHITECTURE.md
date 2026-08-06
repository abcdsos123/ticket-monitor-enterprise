# Architecture

## Monitor Process

BrowserManager → MonitorService → Parser → State/History → NotificationQueue → Runtime

## Discord Process

Discord Gateway → Slash Commands → Runtime/History/Queue

QueueSender 每兩秒讀取通知佇列，成功發送後刪除該筆通知。
