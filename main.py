"""
VisorCredito - Backend API
Consulta ProUsuario + Análisis IA con Gemini
"""
import os
import json
import hashlib
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth, firestore

from scraper import ProUsuarioScraper
from ai_analyzer import AIAnalyzer

load_dotenv()

# ─── Firebase Init ──────────────────────────────────────────────────────────
if not firebase_admin._apps:
    # Opción 1: JSON completo en variable de entorno (Railway)
    firebase_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if firebase_json:
        service_account_info = json.loads(firebase_json)
        cred = credentials.Certificate(service_account_info)
    else:
        # Opción 2: Archivo local (desarrollo)
        service_account_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "./firebase-service-account.json")
        cred = credentials.Certificate(service_account_path)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ─── App Setup ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="VisorCredito API",
    description="API de verificación de riesgo comercial - ProUsuario DR",
    version="1.0.0",
    docs_url=None,  # Ocultar docs en producción
    redoc_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

scraper = ProUsuarioScraper()
analyzer = AIAnalyzer()


# ─── Models ──────────────────────────────────────────────────────────────────
class ConsultaRequest(BaseModel):
    cedula: str
    nombre_referencia: Optional[str] = None  # Nombre interno del negocio para referencia


class ReporteResponse(BaseModel):
    clasificacion: str        # BUENO | REGULAR | RIESGO
    emoji: str                # 🟢 | 🟡 | 🔴
    reporte: str              # Texto del análisis IA
    recomendacion: str        # Recomendación para el negocio
    cedula_hash: str          # Hash SHA-256 de la cédula
    fecha: str                # Fecha de consulta
    nombre_referencia: Optional[str] = None


# ─── Auth Middleware ──────────────────────────────────────────────────────────
async def verificar_token(authorization: str = Header(...)) -> dict:
    """Verifica el Firebase ID Token del usuario."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token inválido")
    
    id_token = authorization.replace("Bearer ", "")
    
    try:
        decoded = firebase_auth.verify_id_token(id_token)
        uid = decoded["uid"]
        
        # Verificar que el usuario está aprobado
        user_ref = db.collection("usuarios").document(uid)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            raise HTTPException(status_code=403, detail="Usuario no registrado")
        
        user_data = user_doc.to_dict()
        if not user_data.get("aprobado", False):
            raise HTTPException(status_code=403, detail="Cuenta pendiente de aprobación")
        
        return {"uid": uid, "email": decoded.get("email")}
    
    except firebase_auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Token expirado o inválido")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Error de autenticación: {str(e)}")


# ─── Endpoints ───────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "app": "VisorCredito", "version": "1.0.0"}


@app.post("/consultar", response_model=ReporteResponse)
async def consultar_cedula(
    request: ConsultaRequest,
    usuario: dict = Depends(verificar_token)
):
    """
    Consulta ProUsuario por cédula y genera reporte de riesgo con IA.
    Los datos crudos NUNCA se almacenan — solo el reporte final.
    """
    cedula = request.cedula.strip().replace("-", "").replace(" ", "")
    
    if len(cedula) < 9 or len(cedula) > 11:
        raise HTTPException(status_code=400, detail="Cédula inválida. Usa formato: 001-0000000-0")
    
    # Hash de la cédula para privacidad
    cedula_hash = hashlib.sha256(cedula.encode()).hexdigest()[:16]
    
    try:
        # 1. Scraping en memoria — datos NUNCA se persisten
        datos_crudos = await scraper.consultar(cedula)
        
        # 2. Análisis IA en RAM
        resultado = await analyzer.analizar(datos_crudos, cedula)
        
        # 3. Limpiar datos crudos de memoria
        del datos_crudos
        
        # 4. Solo guardar el reporte (sin datos sensibles)
        reporte_doc = {
            "uid": usuario["uid"],
            "cedula_hash": cedula_hash,
            "nombre_referencia": request.nombre_referencia,
            "clasificacion": resultado["clasificacion"],
            "emoji": resultado["emoji"],
            "reporte": resultado["reporte"],
            "recomendacion": resultado["recomendacion"],
            "fecha": datetime.utcnow().isoformat(),
        }
        
        db.collection("reportes").add(reporte_doc)
        
        return ReporteResponse(
            clasificacion=resultado["clasificacion"],
            emoji=resultado["emoji"],
            reporte=resultado["reporte"],
            recomendacion=resultado["recomendacion"],
            cedula_hash=cedula_hash,
            fecha=reporte_doc["fecha"],
            nombre_referencia=request.nombre_referencia
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en consulta: {str(e)}")


@app.get("/historial")
async def obtener_historial(usuario: dict = Depends(verificar_token)):
    """Retorna el historial de consultas del negocio (solo reportes, sin datos crudos)."""
    try:
        reportes_ref = (
            db.collection("reportes")
            .where("uid", "==", usuario["uid"])
            .order_by("fecha", direction=firestore.Query.DESCENDING)
            .limit(100)
        )
        
        docs = reportes_ref.stream()
        historial = []
        
        for doc in docs:
            data = doc.to_dict()
            historial.append({
                "id": doc.id,
                "cedula_hash": data.get("cedula_hash"),
                "nombre_referencia": data.get("nombre_referencia"),
                "clasificacion": data.get("clasificacion"),
                "emoji": data.get("emoji"),
                "recomendacion": data.get("recomendacion"),
                "fecha": data.get("fecha"),
            })
        
        return {"historial": historial, "total": len(historial)}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Admin: Aprobar Usuario ───────────────────────────────────────────────────
@app.post("/admin/aprobar/{uid}")
async def aprobar_usuario(
    uid: str,
    admin: dict = Depends(verificar_token)
):
    """Aprueba un usuario para usar la app. Solo admins pueden hacer esto."""
    # Verificar que el solicitante es admin
    admin_ref = db.collection("usuarios").document(admin["uid"])
    admin_doc = admin_ref.get()
    
    if not admin_doc.exists or not admin_doc.to_dict().get("es_admin", False):
        raise HTTPException(status_code=403, detail="No tienes permisos de administrador")
    
    db.collection("usuarios").document(uid).set(
        {"aprobado": True, "fecha_aprobacion": datetime.utcnow().isoformat()},
        merge=True
    )
    
    return {"mensaje": f"Usuario {uid} aprobado correctamente"}


@app.get("/admin/usuarios-pendientes")
async def usuarios_pendientes(admin: dict = Depends(verificar_token)):
    """Lista usuarios pendientes de aprobación."""
    admin_ref = db.collection("usuarios").document(admin["uid"])
    admin_doc = admin_ref.get()
    
    if not admin_doc.exists or not admin_doc.to_dict().get("es_admin", False):
        raise HTTPException(status_code=403, detail="No tienes permisos de administrador")
    
    pendientes_ref = db.collection("usuarios").where("aprobado", "==", False)
    docs = pendientes_ref.stream()
    
    usuarios = []
    for doc in docs:
        data = doc.to_dict()
        usuarios.append({
            "uid": doc.id,
            "email": data.get("email"),
            "nombre_negocio": data.get("nombre_negocio"),
            "fecha_registro": data.get("fecha_registro"),
        })
    
    return {"pendientes": usuarios}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
