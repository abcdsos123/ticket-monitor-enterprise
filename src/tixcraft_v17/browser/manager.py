from __future__ import annotations
import logging
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webdriver import WebDriver
logger=logging.getLogger(__name__)
class BrowserManager:
    def __init__(self,*,headless:bool,profile_dir:str)->None:
        self.headless=headless; self.profile_dir=Path(profile_dir); self._driver:WebDriver|None=None
    def start(self)->WebDriver:
        if self.is_alive(): return self._driver  # type: ignore[return-value]
        # A dead session must be cleaned before a new Chrome uses the same profile.
        self.stop()
        self.profile_dir.mkdir(parents=True,exist_ok=True)
        o=Options(); o.page_load_strategy="eager"; o.add_argument(f"--user-data-dir={self.profile_dir.resolve()}")
        o.add_argument("--disable-notifications"); o.add_argument("--disable-popup-blocking"); o.add_argument("--start-maximized")
        o.add_argument("--lang=zh-TW")
        o.add_experimental_option("prefs", {"intl.accept_languages": "zh-TW,zh,en-US,en"})
        o.add_argument("--disable-dev-shm-usage"); o.add_argument("--no-sandbox")
        if self.headless:o.add_argument("--headless=new"); o.add_argument("--window-size=1920,1080")
        self._driver=webdriver.Chrome(options=o); self._driver.set_page_load_timeout(45); logger.info("Chrome 已啟動")
        return self._driver
    def get(self)->WebDriver:return self.start()
    def is_alive(self)->bool:
        if not self._driver:return False
        try:_=self._driver.current_url; return True
        except Exception:return False
    def restart(self)->WebDriver:self.stop(); return self.start()
    def screenshot(self,path:str|Path)->Path:
        p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); self.get().save_screenshot(str(p)); return p
    def stop(self)->None:
        driver=self._driver
        self._driver=None
        if driver:
            try:driver.quit()
            except Exception:logger.exception("Chrome 關閉失敗")
