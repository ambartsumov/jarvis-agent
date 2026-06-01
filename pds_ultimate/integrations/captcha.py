"""CAPTCHA solving via 2Captcha API (reCAPTCHA v2/v3, hCaptcha, Turnstile, image)."""

from __future__ import annotations

import asyncio
import base64
from typing import Any

import httpx

from pds_ultimate.config import logger


class CaptchaSolver:
    """Async 2Captcha client. Set CAPTCHA_API_KEY in .env."""

    API_IN = "https://2captcha.com/in.php"
    API_RES = "https://2captcha.com/res.php"

    def __init__(self, api_key: str, *, poll_interval: float = 5.0, max_wait: float = 180.0) -> None:
        self.api_key = api_key.strip()
        self.poll_interval = poll_interval
        self.max_wait = max_wait

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def _submit(self, params: dict[str, Any]) -> str:
        payload = {"key": self.api_key, "json": 1, **params}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.API_IN, data=payload)
            data = resp.json()
        if data.get("status") != 1:
            raise RuntimeError(f"2captcha submit: {data.get('request', data)}")
        return str(data["request"])

    async def _poll(self, task_id: str) -> str:
        deadline = asyncio.get_event_loop().time() + self.max_wait
        async with httpx.AsyncClient(timeout=30) as client:
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(self.poll_interval)
                resp = await client.get(
                    self.API_RES,
                    params={"key": self.api_key, "action": "get", "id": task_id, "json": 1},
                )
                data = resp.json()
                if data.get("status") == 1:
                    return str(data["request"])
                req = data.get("request", "")
                if req != "CAPCHA_NOT_READY":
                    raise RuntimeError(f"2captcha poll: {req}")
        raise TimeoutError("2captcha: timeout waiting for solution")

    async def solve_recaptcha_v2(self, sitekey: str, pageurl: str) -> str:
        task_id = await self._submit({
            "method": "userrecaptcha",
            "googlekey": sitekey,
            "pageurl": pageurl,
        })
        return await self._poll(task_id)

    async def solve_recaptcha_v3(self, sitekey: str, pageurl: str, action: str = "verify") -> str:
        task_id = await self._submit({
            "method": "userrecaptcha",
            "version": "v3",
            "googlekey": sitekey,
            "pageurl": pageurl,
            "action": action,
            "min_score": 0.3,
        })
        return await self._poll(task_id)

    async def solve_hcaptcha(self, sitekey: str, pageurl: str) -> str:
        task_id = await self._submit({
            "method": "hcaptcha",
            "sitekey": sitekey,
            "pageurl": pageurl,
        })
        return await self._poll(task_id)

    async def solve_turnstile(self, sitekey: str, pageurl: str) -> str:
        task_id = await self._submit({
            "method": "turnstile",
            "sitekey": sitekey,
            "pageurl": pageurl,
        })
        return await self._poll(task_id)

    async def solve_image(self, image_bytes: bytes) -> str:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        task_id = await self._submit({"method": "base64", "body": b64})
        return await self._poll(task_id)


async def inject_recaptcha_token(page, token: str) -> None:
    """Inject reCAPTCHA token into page and trigger callbacks."""
    await page.evaluate(
        """(token) => {
            const areas = document.querySelectorAll('[name="g-recaptcha-response"], #g-recaptcha-response');
            areas.forEach(el => { el.innerHTML = token; el.value = token; });
            if (typeof window.___grecaptcha_cfg !== 'undefined') {
                const clients = window.___grecaptcha_cfg.clients || {};
                for (const id of Object.keys(clients)) {
                    const client = clients[id];
                    for (const key of Object.keys(client)) {
                        const obj = client[key];
                        if (obj && typeof obj.callback === 'function') {
                            obj.callback(token);
                            return;
                        }
                    }
                }
            }
            if (typeof window.grecaptcha !== 'undefined' && window.grecaptcha.getResponse) {
                try { window.grecaptcha.getResponse = () => token; } catch(e) {}
            }
        }""",
        token,
    )


async def inject_hcaptcha_token(page, token: str) -> None:
    await page.evaluate(
        """(token) => {
            document.querySelectorAll('[name="h-captcha-response"], [name="g-recaptcha-response"]')
                .forEach(el => { el.innerHTML = token; el.value = token; });
        }""",
        token,
    )


async def detect_captcha(page) -> dict[str, str] | None:
    """Detect captcha type and sitekey on current page."""
    return await page.evaluate(
        """() => {
            const rec = document.querySelector('.g-recaptcha, [data-sitekey]');
            if (rec) {
                const key = rec.getAttribute('data-sitekey');
                if (key) return {type: 'recaptcha_v2', sitekey: key};
            }
            const iframe = document.querySelector('iframe[src*="recaptcha"]');
            if (iframe) {
                const m = iframe.src.match(/[?&]k=([^&]+)/);
                if (m) return {type: 'recaptcha_v2', sitekey: decodeURIComponent(m[1])};
            }
            const hc = document.querySelector('.h-captcha, [data-hcaptcha-sitekey]');
            if (hc) {
                const key = hc.getAttribute('data-sitekey') || hc.getAttribute('data-hcaptcha-sitekey');
                if (key) return {type: 'hcaptcha', sitekey: key};
            }
            const cf = document.querySelector('.cf-turnstile, [data-turnstile-sitekey]');
            if (cf) {
                const key = cf.getAttribute('data-sitekey') || cf.getAttribute('data-turnstile-sitekey');
                if (key) return {type: 'turnstile', sitekey: key};
            }
            const body = document.body?.innerText || '';
            if (/captcha|robot|recaptcha|hcaptcha/i.test(body)) {
                return {type: 'unknown', sitekey: ''};
            }
            return null;
        }"""
    )


async def solve_page_captcha(page, solver: CaptchaSolver) -> str:
    """Detect and solve captcha on Playwright page. Returns status message."""
    if not solver.available:
        return "CAPTCHA_API_KEY не задан — добавь ключ 2captcha в .env"

    info = await detect_captcha(page)
    if not info:
        return "Капча на странице не обнаружена"

    pageurl = page.url
    ctype = info.get("type", "")
    sitekey = info.get("sitekey", "")

    if ctype == "unknown" or not sitekey:
        # fallback: screenshot region and image captcha
        shot = await page.screenshot(type="png")
        text = await solver.solve_image(shot)
        logger.info(f"Image captcha solved: {text[:20]}...")
        return f"Решена image-капча: {text}"

    logger.info(f"Solving {ctype} sitekey={sitekey[:12]}... url={pageurl}")

    if ctype == "recaptcha_v2":
        token = await solver.solve_recaptcha_v2(sitekey, pageurl)
        await inject_recaptcha_token(page, token)
    elif ctype == "hcaptcha":
        token = await solver.solve_hcaptcha(sitekey, pageurl)
        await inject_hcaptcha_token(page, token)
    elif ctype == "turnstile":
        token = await solver.solve_turnstile(sitekey, pageurl)
        await inject_hcaptcha_token(page, token)
    else:
        return f"Неизвестный тип капчи: {ctype}"

    await page.wait_for_timeout(800)
    return f"Капча {ctype} решена, токен вставлен"
