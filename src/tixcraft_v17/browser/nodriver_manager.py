from __future__ import annotations

import asyncio
import inspect
import json
import logging
import threading
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any, Coroutine

logger = logging.getLogger(__name__)


class KktixNodriverManager:
    """使用獨立 event loop 維持 KKTIX nodriver Chromium。

    V19.3 的 KKTIX 解析邏輯刻意比舊版單純：
    1. 活動頁只負責尋找 /registrations/new。
    2. 售票頁等待 #registrationsNewApp 與 .ticket-unit。
    3. 每個 .ticket-unit 直接讀取 textContent。
    4. 票種列含售完關鍵字才是售完，否則就是有票。
    5. 只有完全找不到票種列時才判斷登入或驗證頁。
    """

    engine = "nodriver"

    def __init__(
        self,
        *,
        headless: bool,
        profile_dir: str,
        page_timeout: int = 45,
    ) -> None:
        self.headless = headless
        self.profile_dir = Path(profile_dir)
        self.page_timeout = page_timeout
        self._browser: Any | None = None
        self._page: Any | None = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="kktix-nodriver",
            daemon=True,
        )
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(
        self,
        coro: Coroutine[Any, Any, Any],
        timeout: float | None = None,
        *,
        reset_on_timeout: bool = True,
    ) -> Any:
        """將 coroutine 安全送入 nodriver 專用 event loop。

        舊版只在呼叫端等待 Future，逾時後背景 coroutine 仍可能繼續卡住，
        造成後續所有 KKTIX 活動一起 Timeout。新版會取消逾時工作，並在
        同一個 event loop 中重設失效的 browser/page。
        """
        if not self._thread.is_alive():
            try:
                coro.close()
            except Exception:
                pass
            raise RuntimeError("KKTIX nodriver 背景執行緒未運作")

        effective_timeout = (
            float(timeout)
            if timeout is not None
            else float(self.page_timeout + 30)
        )
        future: Future[Any] = asyncio.run_coroutine_threadsafe(coro, self._loop)

        try:
            return future.result(timeout=effective_timeout)
        except FutureTimeoutError as exc:
            logger.error(
                "KKTIX nodriver 操作超時（%.1f 秒），取消目前工作",
                effective_timeout,
            )
            future.cancel()

            # 給 event loop 一點時間處理 CancelledError，避免舊 coroutine
            # 在背景持續操作已失效的分頁。
            try:
                future.result(timeout=2)
            except Exception:
                pass

            if reset_on_timeout and self._thread.is_alive():
                try:
                    reset_future: Future[Any] = asyncio.run_coroutine_threadsafe(
                        self._reset_after_timeout_async(),
                        self._loop,
                    )
                    reset_future.result(timeout=15)
                except Exception:
                    logger.exception("KKTIX nodriver 超時後重設失敗")
                    self._browser = None
                    self._page = None

            raise TimeoutError(
                f"KKTIX nodriver 操作超時（{effective_timeout:.1f} 秒）"
            ) from exc

    async def _reset_after_timeout_async(self) -> None:
        """丟棄可能已失去回應的 nodriver browser/page。"""
        logger.warning("準備重設 KKTIX nodriver 瀏覽器")
        browser = self._browser
        self._browser = None
        self._page = None

        if browser is None:
            return

        try:
            result = browser.stop()
            if inspect.isawaitable(result):
                await asyncio.wait_for(result, timeout=10)
        except asyncio.TimeoutError:
            logger.warning("停止 KKTIX nodriver 瀏覽器逾時，將直接重新建立")
        except Exception:
            logger.exception("停止 KKTIX nodriver 瀏覽器時發生錯誤")

    async def _start_async(self) -> Any:
        if self._browser is not None:
            try:
                if self._page is not None:
                    await asyncio.wait_for(
                        self._page.evaluate(
                            "document.readyState",
                            return_by_value=True,
                        ),
                        timeout=8,
                    )
                return self._browser
            except asyncio.TimeoutError:
                logger.warning("KKTIX 分頁健康檢查逾時，重新啟動瀏覽器")
                await self._reset_after_timeout_async()
            except Exception:
                logger.exception("KKTIX 分頁健康檢查失敗，重新啟動瀏覽器")
                await self._reset_after_timeout_async()

        try:
            import nodriver as uc
        except ImportError as exc:
            raise RuntimeError(
                "尚未安裝 nodriver，請執行 pip install -r requirements.txt"
            ) from exc

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._browser = await asyncio.wait_for(
                uc.start(
                    headless=self.headless,
                    user_data_dir=str(self.profile_dir.resolve()),
                    browser_args=[
                        "--lang=zh-TW",
                        "--disable-notifications",
                        "--disable-popup-blocking",
                        "--disable-dev-shm-usage",
                        "--start-maximized",
                    ],
                ),
                timeout=30,
            )
        except asyncio.TimeoutError as exc:
            self._browser = None
            self._page = None
            raise TimeoutError("KKTIX nodriver 啟動瀏覽器逾時") from exc

        logger.info("KKTIX nodriver 已啟動（profile=%s）", self.profile_dir)
        return self._browser

    def start(self) -> "KktixNodriverManager":
        self._submit(self._start_async())
        return self

    @staticmethod
    def _json_value(value: Any, default: Any) -> Any:
        """相容不同 nodriver 版本的 evaluate 回傳格式。"""
        if value is None:
            return default

        remote_value = getattr(value, "value", None)
        if remote_value is not None:
            value = remote_value
        elif isinstance(value, tuple) and value:
            value = getattr(value[0], "value", value[0])

        if isinstance(value, (dict, list, bool, int, float)):
            return value
        if not isinstance(value, str) or not value:
            return default
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return default
        return default if decoded is None else decoded

    async def _evaluate_json(self, page: Any, expression: str, default: Any) -> Any:
        value = await page.evaluate(expression, return_by_value=True)
        return self._json_value(value, default)

    async def _navigate(
        self,
        url: str,
        wait_seconds: int,
        delay_seconds: float,
    ) -> Any:
        browser = await self._start_async()
        self._page = await browser.get(url)

        deadline = asyncio.get_running_loop().time() + wait_seconds
        while asyncio.get_running_loop().time() < deadline:
            try:
                state = await self._page.evaluate(
                    "document.readyState",
                    return_by_value=True,
                )
                state = getattr(state, "value", state)
                if state in {"interactive", "complete"}:
                    break
            except Exception:
                pass
            await asyncio.sleep(0.25)

        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        return self._page

    async def _registration_links(self, page: Any) -> list[dict[str, str]]:
        data = await self._evaluate_json(
            page,
            r"""
            JSON.stringify((() => {
              const clean = value => (value || '').replace(/\s+/g, ' ').trim();
              const seen = new Set();
              const result = [];
              for (const anchor of document.querySelectorAll('a[href]')) {
                const href = new URL(anchor.getAttribute('href'), location.href).href;
                if (!/\/registrations\/new(?:[?#]|$)/.test(href)) continue;
                if (seen.has(href)) continue;
                seen.add(href);
                result.push({
                  url: href,
                  name: clean(anchor.textContent || anchor.getAttribute('aria-label')) || 'KKTIX 報名頁'
                });
              }
              result.sort((a, b) => {
                const ak = /kktix\.com\/events\//i.test(a.url) ? 0 : 1;
                const bk = /kktix\.com\/events\//i.test(b.url) ? 0 : 1;
                return ak - bk;
              });
              return result;
            })())
            """,
            [],
        )
        return data if isinstance(data, list) else []

    async def _wait_for_ticket_page(self, page: Any, wait_seconds: int) -> None:
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while asyncio.get_running_loop().time() < deadline:
            state = await self._evaluate_json(
                page,
                r"""
                JSON.stringify((() => ({
                  app: Boolean(document.querySelector('#registrationsNewApp')),
                  units: document.querySelectorAll('.ticket-unit').length,
                  bodyReady: Boolean(document.body)
                }))())
                """,
                {},
            )
            if isinstance(state, dict):
                if int(state.get("units") or 0) > 0:
                    return
                if state.get("app") and state.get("bodyReady"):
                    # Angular 可能還在渲染，繼續等待，但縮短輪詢週期。
                    await asyncio.sleep(0.4)
                    continue
            await asyncio.sleep(0.5)

    async def _close_guest_modal(self, page: Any) -> None:
        try:
            await page.evaluate(
                r"""
                (() => {
                  const selectors = [
                    '#guestModal button[data-dismiss="modal"]',
                    '#guestModal .modal-footer button.btn-default',
                    '.modal.in button[data-dismiss="modal"]',
                    '.modal.in .close'
                  ];
                  for (const selector of selectors) {
                    const button = document.querySelector(selector);
                    if (button) {
                      button.click();
                      return true;
                    }
                  }
                  return false;
                })()
                """,
                return_by_value=True,
            )
        except Exception:
            logger.debug("KKTIX 會員提示視窗關閉失敗", exc_info=True)

    async def _parse_ticket_page(self, page: Any) -> dict[str, Any]:
        """以使用者單獨測試成功的 Selenium 邏輯等價改寫。"""
        payload = await self._evaluate_json(
            page,
            r"""
            JSON.stringify((() => {
              const clean = value => (value || '').replace(/\s+/g, ' ').trim();
              const text = (parent, selector) => clean(parent.querySelector(selector)?.textContent);
              const soldWords = ['sold out', '售完', '已售完', '暫無票券', '額滿', '停止販售'];

              const units = [...document.querySelectorAll('.ticket-unit')].map((unit, index) => {
                const name = text(unit, '.ticket-name');
                const seat = text(unit, '.ticket-seat');
                const priceText = text(unit, '.ticket-price');
                const quantityText = text(unit, '.ticket-quantity');
                const rawText = clean(unit.textContent);
                const normalized = (quantityText + ' ' + rawText).toLowerCase();
                const sold = soldWords.some(word => normalized.includes(word.toLowerCase()));
                const displayTable = unit.querySelector('.display-table[id^="ticket_"]');

                return {
                  index: index + 1,
                  ticket_id: displayTable?.id || unit.id || '',
                  name,
                  seat,
                  price_text: priceText,
                  quantity_text: quantityText,
                  status: sold ? '售完' : '有票',
                  raw_text: rawText
                };
              }).filter(item => item.name || item.price_text || item.raw_text);

              // 重要：只有 units 為空時才判斷驗證或登入，避免票頁 script
              // 中出現 captcha/cloudflare 字樣造成誤判。
              const visibleText = clean(document.body?.innerText);
              const title = clean(document.title);
              const lower = (title + ' ' + visibleText).toLowerCase();
              const verification = units.length === 0 && [
                '驗證您是人類', '請完成驗證', '安全性驗證',
                'verify you are human', 'checking your browser',
                'security verification', 'challenge-platform'
              ].some(word => lower.includes(word.toLowerCase()));
              const loginRequired = units.length === 0 && (
                /請先登入|登入後才能|會員登入|sign\s*in/i.test(visibleText)
              );

              let pageStatus = 'OK';
              if (units.length > 0) {
                pageStatus = units.some(item => item.status === '有票')
                  ? 'IN_STOCK'
                  : 'OUT_OF_STOCK';
              } else if (verification) {
                pageStatus = 'VERIFICATION_REQUIRED';
              } else if (loginRequired) {
                pageStatus = 'LOGIN_REQUIRED';
              } else if (/尚未開賣|未開賣|coming\s*soon/i.test(visibleText)) {
                pageStatus = 'NOT_STARTED';
              } else if (/報名已結束|活動已結束|registration\s*closed/i.test(visibleText)) {
                pageStatus = 'REGISTRATION_CLOSED';
              } else {
                pageStatus = 'NO_TICKET_ROWS';
              }

              return {
                url: location.href,
                title,
                body: visibleText,
                page_status: pageStatus,
                verification,
                login_required: loginRequired,
                units
              };
            })())
            """,
            {},
        )
        if not isinstance(payload, dict):
            return {
                "url": "",
                "title": "",
                "body": "",
                "page_status": "NO_TICKET_ROWS",
                "verification": False,
                "login_required": False,
                "units": [],
            }
        return payload

    async def _extract_async(
        self,
        event_url: str,
        wait_seconds: int,
        delay_seconds: float,
    ) -> dict[str, Any]:
        event_page = await self._navigate(event_url, wait_seconds, delay_seconds)
        links = await self._registration_links(event_page)
        targets = links or [{"url": event_url, "name": "KKTIX 活動"}]

        sessions: list[dict[str, Any]] = []
        for target in targets:
            target_url = str(target.get("url") or event_url)
            page = await self._navigate(target_url, wait_seconds, delay_seconds)
            await self._wait_for_ticket_page(page, wait_seconds)
            await self._close_guest_modal(page)
            data = await self._parse_ticket_page(page)
            data["name"] = str(target.get("name") or "KKTIX 報名頁")
            if not data.get("url"):
                data["url"] = target_url
            sessions.append(data)

        return {"event_url": event_url, "sessions": sessions}

    def extract_event(
        self,
        event_url: str,
        wait_seconds: int,
        delay_seconds: float,
    ) -> dict[str, Any]:
        # 舊版會等到 90～132 秒，且逾時 coroutine 不會被取消。
        # 新版將一般檢查控制在約 45～60 秒，重設後自動重試一次。
        timeout = max(
            45.0,
            float(wait_seconds) + float(delay_seconds) + 25.0,
        )

        try:
            return self._submit(
                self._extract_async(event_url, wait_seconds, delay_seconds),
                timeout=timeout,
            )
        except TimeoutError:
            logger.warning(
                "KKTIX 第一次解析逾時，重建瀏覽器後重試一次：%s",
                event_url,
            )
            return self._submit(
                self._extract_async(event_url, wait_seconds, delay_seconds),
                timeout=timeout,
            )

    async def _screenshot_async(self, path: Path) -> None:
        await self._start_async()
        if self._page is None:
            self._page = await self._browser.get("about:blank")
        result = self._page.save_screenshot(str(path))
        if inspect.isawaitable(result):
            await result

    def screenshot(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        self._submit(self._screenshot_async(output))
        return output

    async def _stop_async(self) -> None:
        browser, self._browser, self._page = self._browser, None, None
        if browser is None:
            return
        try:
            result = browser.stop()
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception("KKTIX nodriver 關閉失敗")

    def stop(self) -> None:
        if self._thread.is_alive():
            try:
                self._submit(
                    self._stop_async(),
                    timeout=15,
                    reset_on_timeout=False,
                )
            except Exception:
                logger.exception("停止 KKTIX nodriver 失敗")

    def restart(self) -> "KktixNodriverManager":
        self.stop()
        self.start()
        return self

    def is_alive(self) -> bool:
        try:
            self._submit(self._start_async(), timeout=15)
            return True
        except Exception:
            return False

    def close_loop(self) -> None:
        self.stop()
        if self._thread.is_alive():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
