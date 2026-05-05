"""
VisorCredito - Scraper ProUsuario
Playwright para consultar páginas públicas sin dejar rastro.
"""
import asyncio
import random
import re
import logging
from typing import Dict, Any
from playwright.async_api import async_playwright, Page

logger = logging.getLogger("visorcredito")

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

# Flags optimizados para contenedores Docker (Railway)
CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",       # Evita crashes por /dev/shm limitado
    "--disable-gpu",                  # No hay GPU en Railway
    "--disable-blink-features=AutomationControlled",
    "--disable-extensions",
    "--disable-background-networking",
    "--single-process",               # Reduce uso de memoria en Railway
    "--no-zygote",
]


class ProUsuarioScraper:

    async def consultar(self, cedula: str) -> Dict[str, Any]:
        resultados = {
            "cedula_formato": self._formatear_cedula(cedula),
            "cuentas_inactivas": None,
            "productos_liquidacion": None,
            "estatus_solicitudes": None,
            "errores": []
        }

        logger.info("Iniciando Playwright Chromium...")
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=CHROMIUM_ARGS
            )
            logger.info("Browser lanzado correctamente")
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
                    logger.info(f"Consultando: {key} -> {url}")
                    try:
                        resultado = await self._consultar_pagina(context, url, cedula)
                        resultados[key] = resultado
                        logger.info(f"OK {key}: encontrado={resultado.get('encontrado')}")
                    except Exception as e:
                        logger.error(f"Error en {key}: {str(e)}")
                        resultados["errores"].append(f"{key}: {str(e)}")
                    await asyncio.sleep(random.uniform(1.0, 2.0))

            finally:
                await browser.close()
                logger.info("Browser cerrado")

        return resultados

    async def _consultar_pagina(self, context, url: str, cedula: str) -> dict:
        page = await context.new_page()
        resultado = {"encontrado": False, "mensaje": "Sin resultados"}

        try:
            # domcontentloaded es mucho más rápido que networkidle
            logger.info(f"Navegando a {url}...")
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(random.uniform(1.5, 2.5))

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
                        logger.info(f"Input encontrado con selector: {sel}")
                        break
                except:
                    pass

            if input_el:
                await input_el.click()
                await asyncio.sleep(0.3)
                await input_el.fill(cedula)
                await asyncio.sleep(random.uniform(0.5, 1.0))

                # Buscar botón submit
                submitted = False
                for sel in ["button[type='submit']", "button:has-text('Buscar')", "button:has-text('Consultar')", "input[type='submit']"]:
                    try:
                        btn = page.locator(sel).first
                        if await btn.count() > 0:
                            await btn.click()
                            submitted = True
                            logger.info(f"Botón clickeado: {sel}")
                            break
                    except:
                        pass

                if not submitted:
                    await page.keyboard.press("Enter")
                    logger.info("Submit via Enter")

                # Esperar resultados (domcontentloaded approach)
                await asyncio.sleep(random.uniform(3.0, 4.0))

                # Extraer texto de resultados
                texto = await page.evaluate("""
                    () => {
                        const els = document.querySelectorAll('table, .resultado, [class*="result"], [class*="card"], .alert, .message');
                        let t = [];
                        els.forEach(e => { if(e.innerText && e.innerText.trim().length > 5) t.push(e.innerText.trim()); });
                        return t.slice(0, 10).join('\n---\n');
                    }
                """)

                if texto and len(texto) > 15:
                    resultado["encontrado"] = True
                    resultado["mensaje"] = texto[:800]
                else:
                    # fallback: contenido del main
                    main = await page.evaluate("() => { const m = document.querySelector('main, [role=\"main\"], #content, .content'); return m ? m.innerText : document.body.innerText; }")
                    resultado["mensaje"] = (main or "Sin datos")[:500]
            else:
                resultado["mensaje"] = "Formulario no encontrado en la pagina"
                logger.warning(f"No se encontro input en {url}")

        except Exception as e:
            resultado["error"] = str(e)
            logger.error(f"Exception en _consultar_pagina({url}): {str(e)}")
        finally:
            await page.close()

        return resultado

    def _formatear_cedula(self, cedula: str) -> str:
        c = re.sub(r'\D', '', cedula)
        return f"{c[:3]}-{c[3:10]}-{c[10]}" if len(c) == 11 else cedula
