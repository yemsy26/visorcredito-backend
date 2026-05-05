"""
VisorCredito - Analizador de Riesgo
Clasificador por reglas basado en datos de ProUsuario.
Si GEMINI_API_KEY está disponible, enriquece el reporte con IA.
Sin dependencia obligatoria de APIs externas.
"""
import os
import json
import asyncio
import logging
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("visorcredito")


class AIAnalyzer:

    async def analizar(self, datos: Dict[str, Any], cedula: str) -> Dict[str, str]:
        """
        Clasifica el riesgo comercial basándose en datos de ProUsuario.
        Prioriza el clasificador por reglas; enriquece con Gemini si está disponible.
        """
        # 1. Clasificación por reglas (siempre funciona)
        resultado = self._clasificar_por_reglas(datos)
        logger.info(f"Clasificación por reglas: {resultado['clasificacion']}")

        # 2. Intentar enriquecer con Gemini (opcional)
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            resultado = await self._enriquecer_con_gemini(api_key, datos, resultado)

        return resultado

    def _clasificar_por_reglas(self, datos: Dict[str, Any]) -> Dict[str, str]:
        ci  = datos.get("cuentas_inactivas") or {}
        pl  = datos.get("productos_liquidacion") or {}
        es  = datos.get("estatus_solicitudes") or {}
        hc  = datos.get("historial_crediticio") or {}
        da  = datos.get("deudas_activas") or {}
        errores = datos.get("errores", [])

        tiene_cuentas_inactivas    = ci.get("encontrado", False)
        tiene_productos_liquidacion = pl.get("encontrado", False)
        tiene_solicitudes          = es.get("encontrado", False)
        tiene_historial_negativo   = hc.get("encontrado", False)
        tiene_deudas_activas       = da.get("encontrado", False)
        num_errores = len(errores)

        # ─── Clasificación ───────────────────────────────────────────────────
        if tiene_cuentas_inactivas or tiene_productos_liquidacion or tiene_deudas_activas:
            clasificacion = "RIESGO"
            emoji = "🔴"
            hallazgos = []
            if tiene_cuentas_inactivas:
                hallazgos.append("cuentas inactivas o abandonadas")
            if tiene_productos_liquidacion:
                hallazgos.append("productos en entidades liquidadas")
            if tiene_deudas_activas:
                hallazgos.append(f"deudas activas registradas: {da.get('mensaje','')[:150]}")
            reporte = (
                f"⚠️ Se detectaron alertas críticas: {'; '.join(hallazgos)}. "
                "Este perfil presenta riesgos financieros que requieren atención inmediata."
            )
            recomendacion = (
                "NO se recomienda otorgar crédito. Solicitar documentación explicativa "
                "y verificar estado actual de las deudas reportadas."
            )

        elif tiene_historial_negativo or tiene_solicitudes:
            clasificacion = "REGULAR"
            emoji = "🟡"
            detalle = []
            if tiene_historial_negativo:
                detalle.append(f"historial crediticio con atrasos: {hc.get('mensaje','')[:150]}")
            if tiene_solicitudes:
                detalle.append("reclamaciones o solicitudes activas")
            reporte = (
                f"El cliente presenta irregularidades menores: {'; '.join(detalle)}. "
                "Se recomienda evaluar con cuidado antes de proceder."
            )
            recomendacion = (
                "Proceder con precaución. Puede otorgar crédito limitado con garantías adicionales. "
                "Verificar si el historial negativo ha sido resuelto."
            )

        elif num_errores >= 4:
            clasificacion = "REGULAR"
            emoji = "🟡"
            reporte = (
                "No fue posible completar todas las consultas a ProUsuario. "
                "Los sistemas externos pueden estar temporalmente no disponibles."
            )
            recomendacion = "Reintentar la consulta más tarde o verificar manualmente en prousuario.gob.do."

        else:
            clasificacion = "BUENO"
            emoji = "🟢"
            fuentes_ok = sum([not ci.get("error"), not pl.get("error"),
                              not es.get("error"), not hc.get("error"), not da.get("error")])
            reporte = (
                f"✅ No se encontraron alertas en {fuentes_ok} fuentes consultadas. "
                "Sin cuentas abandonadas, sin deudas activas registradas, sin atrasos "
                "en historial crediticio y sin reclamaciones pendientes."
            )
            recomendacion = (
                "Perfil financiero favorable. Puede proceder con normalidad. "
                "Se recomienda mantener controles de crédito estándar."
            )

        return {
            "clasificacion": clasificacion,
            "emoji": emoji,
            "reporte": reporte,
            "recomendacion": recomendacion
        }


    async def _enriquecer_con_gemini(
        self, api_key: str, datos: Dict[str, Any], resultado_base: Dict[str, str]
    ) -> Dict[str, str]:
        """
        Intenta mejorar el reporte con Gemini. Si falla, retorna el resultado base.
        """
        try:
            import google.generativeai as genai

            genai.configure(api_key=api_key)

            # Probar modelos disponibles en orden de preferencia
            modelos = ["gemini-1.5-flash", "gemini-pro", "gemini-1.0-pro"]
            model = None
            for nombre in modelos:
                try:
                    model = genai.GenerativeModel(
                        model_name=nombre,
                        generation_config={
                            "temperature": 0.3,
                            "max_output_tokens": 500,
                        }
                    )
                    break
                except Exception:
                    continue

            if not model:
                logger.warning("Ningún modelo Gemini disponible, usando clasificador por reglas")
                return resultado_base

            resumen = self._preparar_resumen(datos)
            clasificacion = resultado_base["clasificacion"]

            prompt = f"""Eres un analista de riesgo comercial en República Dominicana.
La clasificación ya fue determinada como: {clasificacion}

Datos de ProUsuario:
{resumen}

Escribe un párrafo profesional (2-3 oraciones) que explique esta clasificación
de forma clara para un dueño de negocio. No uses jerga técnica.
Responde SOLO el texto del análisis, sin JSON, sin títulos."""

            response = await asyncio.to_thread(model.generate_content, prompt)

            if response and response.text and len(response.text) > 20:
                resultado_base["reporte"] = response.text.strip()
                logger.info("Reporte enriquecido con Gemini exitosamente")

        except Exception as e:
            logger.warning(f"Gemini no disponible, usando análisis por reglas: {str(e)[:100]}")

        return resultado_base

    def _preparar_resumen(self, datos: Dict[str, Any]) -> str:
        partes = []
        ci = datos.get("cuentas_inactivas") or {}
        pl = datos.get("productos_liquidacion") or {}
        es = datos.get("estatus_solicitudes") or {}

        partes.append(f"Cuentas inactivas: {'HALLAZGO: ' + ci.get('mensaje','')[:200] if ci.get('encontrado') else 'Sin hallazgos'}")
        partes.append(f"Productos liquidación: {'HALLAZGO: ' + pl.get('mensaje','')[:200] if pl.get('encontrado') else 'Sin hallazgos'}")
        partes.append(f"Solicitudes/quejas: {'HALLAZGO: ' + es.get('mensaje','')[:200] if es.get('encontrado') else 'Sin hallazgos'}")

        return "\n".join(partes)
