"""
VisorCredito - Analizador IA con Gemini
Analiza datos en RAM — NUNCA almacena datos crudos.
"""
import os
import json
from typing import Dict, Any
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))


class AIAnalyzer:

    def __init__(self):
        self.model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config={
                "temperature": 0.3,
                "max_output_tokens": 600,
                "response_mime_type": "application/json",
            }
        )

    async def analizar(self, datos: Dict[str, Any], cedula: str) -> Dict[str, str]:
        """
        Analiza los datos de ProUsuario y genera un reporte de riesgo.
        Los datos crudos solo pasan por esta función en memoria.
        """
        resumen = self._preparar_resumen(datos)
        prompt = self._construir_prompt(resumen)

        try:
            response = self.model.generate_content(prompt)
            resultado = json.loads(response.text)

            clasificacion = resultado.get("clasificacion", "REGULAR").upper()
            emoji_map = {"BUENO": "🟢", "REGULAR": "🟡", "RIESGO": "🔴"}

            return {
                "clasificacion": clasificacion,
                "emoji": emoji_map.get(clasificacion, "🟡"),
                "reporte": resultado.get("reporte", "Análisis no disponible."),
                "recomendacion": resultado.get("recomendacion", "Se recomienda precaución.")
            }

        except Exception as e:
            return {
                "clasificacion": "REGULAR",
                "emoji": "🟡",
                "reporte": f"No se pudo completar el análisis automático. Error: {str(e)}",
                "recomendacion": "Se recomienda verificación manual antes de proceder."
            }

    def _preparar_resumen(self, datos: Dict[str, Any]) -> str:
        partes = []

        ci = datos.get("cuentas_inactivas", {})
        if ci and ci.get("encontrado"):
            partes.append(f"CUENTAS INACTIVAS/ABANDONADAS: {ci.get('mensaje', '')[:300]}")
        else:
            partes.append("CUENTAS INACTIVAS: Sin hallazgos registrados.")

        pl = datos.get("productos_liquidacion", {})
        if pl and pl.get("encontrado"):
            partes.append(f"PRODUCTOS EN ENTIDADES LIQUIDADAS: {pl.get('mensaje', '')[:300]}")
        else:
            partes.append("PRODUCTOS EN LIQUIDACIÓN: Sin hallazgos registrados.")

        es = datos.get("estatus_solicitudes", {})
        if es and es.get("encontrado"):
            partes.append(f"SOLICITUDES/QUEJAS ACTIVAS: {es.get('mensaje', '')[:300]}")
        else:
            partes.append("SOLICITUDES: Sin quejas o reclamaciones activas.")

        errores = datos.get("errores", [])
        if errores:
            partes.append(f"NOTA: Algunas consultas no pudieron completarse ({len(errores)} errores).")

        return "\n".join(partes)

    def _construir_prompt(self, resumen: str) -> str:
        return f"""Eres un sistema de análisis de riesgo comercial para negocios en República Dominicana.
Basándote en datos públicos de ProUsuario (Superintendencia de Bancos), clasifica al cliente consultado.

DATOS CONSULTADOS:
{resumen}

INSTRUCCIONES:
- Clasifica como BUENO, REGULAR o RIESGO según los hallazgos
- BUENO: Sin deudas, sin cuentas abandonadas, sin quejas activas → cliente confiable
- REGULAR: Algunas inconsistencias menores o datos incompletos → verificar antes de proceder
- RIESGO: Cuentas abandonadas, productos en entidades liquidadas, múltiples quejas → no recomendado
- NO incluyas datos personales identificables en el reporte
- El reporte debe ser útil para un negocio que evalúa otorgar crédito o servicios

Responde EXACTAMENTE en este formato JSON:
{{
  "clasificacion": "BUENO" | "REGULAR" | "RIESGO",
  "reporte": "Análisis detallado en 2-3 oraciones para el negocio...",
  "recomendacion": "Acción recomendada en 1 oración..."
}}"""
