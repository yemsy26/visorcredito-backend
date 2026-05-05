"""
VisorCredito - Scraper ProUsuario
Playwright para consultar páginas públicas sin dejar rastro.
"""
import asyncio
import random
import re
from typing import Dict, Any
from playwright.async_api import async_playwright, Page

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

CONSULTAS = {
    "cuentas_inactivas": "https://prousuario.gob.do/consultas/cuentas-inactivas-y-abandonadas/",
    "productos_liquidacion": "https://prousuario.gob.do/consultas/productos-en-entidades-en-liquidacion/",
    "estatus_solicitudes": "https://prousuario.gob.do/consultas/estatus-de-solicitudes/",
}


class ProUsuarioScraper:

    async def consultar(self, cedula: str) -> Dict[str, Any]:
        resultados = {
            "cedula_formato": self._formatear_cedula(cedula),
            "cuentas_inactivas": None,
            "productos_liquidacion": None,
            "estatus_solicitudes": None,
            "errores": []
        }

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"]
            )
            try:
                context = await browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    viewport={"width": 1366, "height": 768},
                    locale="es-DO",
                    timezone_id="America/Santo_Domingo",
                )
                await context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
                )

                for key, url in CONSULTAS.items():
                    try:
                        resultado = await self._consultar_pagina(context, url, cedula)
                        resultados[key] = resultado
                    except Exception as e:
                        resultados["errores"].append(f"{key}: {str(e)}")
                    await asyncio.sleep(random.uniform(1.5, 3.0))

            finally:
                await browser.close()

        return resultados

    async def _consultar_pagina(self, context, url: str, cedula: str) -> dict:
        page = await context.new_page()
        resultado = {"encontrado": False, "mensaje": "Sin resultados"}

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(random.uniform(1.0, 2.0))

            # Buscar input de cedula
            selectores_input = [
                "input[name*='cedula']", "input[placeholder*='dula']",
                "input[id*='cedula']", "input[id*='Cedula']",
                "input[type='text']:first-of-type",
            ]
            input_el = None
            for sel in selectores_input:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        input_el = el
                        break
                except:
                    pass

            if input_el:
                await input_el.click()
                await asyncio.sleep(0.3)
                await input_el.fill(cedula)
                await asyncio.sleep(random.uniform(0.5, 1.0))

                # Buscar botón
                for sel in ["button[type='submit']", "button:has-text('Buscar')", "button:has-text('Consultar')"]:
                    try:
                        btn = page.locator(sel).first
                        if await btn.count() > 0:
                            await btn.click()
                            break
                    except:
                        pass
                else:
                    await page.keyboard.press("Enter")

                await asyncio.sleep(random.uniform(2.0, 3.5))

                # Extraer texto de resultados
                texto = await page.evaluate("""
                    () => {
                        const els = document.querySelectorAll('table, .resultado, [class*="result"], [class*="card"]');
                        let t = [];
                        els.forEach(e => { if(e.innerText && e.innerText.trim().length > 5) t.push(e.innerText.trim()); });
                        return t.slice(0, 10).join('\\n---\\n');
                    }
                """)

                if texto and len(texto) > 15:
                    resultado["encontrado"] = True
                    resultado["mensaje"] = texto[:800]
                else:
                    # fallback: contenido del main
                    main = await page.evaluate("() => { const m = document.querySelector('main, [role=\"main\"]'); return m ? m.innerText : ''; }")
                    resultado["mensaje"] = (main or "Sin datos")[:500]
            else:
                resultado["mensaje"] = "Formulario no encontrado en la página"

        except Exception as e:
            resultado["error"] = str(e)
        finally:
            await page.close()

        return resultado

    def _formatear_cedula(self, cedula: str) -> str:
        c = re.sub(r'\D', '', cedula)
        return f"{c[:3]}-{c[3:10]}-{c[10]}" if len(c) == 11 else cedula
