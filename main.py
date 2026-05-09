import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

from afip import AFIPClient, AFIPError
from excel_parser import parse_invoice_excel
from invoice_pdf import generate_invoice_pdf
from pdf_parser import parse_santander_pdf

CUIT = os.getenv("CUIT", "27299517476")
PTO_VTA = int(os.getenv("PTO_VTA", "1"))
CERT_PATH = os.getenv("CERT_PATH", str(BASE_DIR / "certs/cert.crt"))
KEY_PATH  = os.getenv("KEY_PATH",  str(BASE_DIR / "certs/private.key"))
TESTING = os.getenv("TESTING", "true").lower() == "true"

afip = AFIPClient(CUIT, CERT_PATH, KEY_PATH, testing=TESTING)

PDF_CONFIG = {
    "cuit":                CUIT,
    "razon_social":        os.getenv("RAZON_SOCIAL", "FLORENCIA DE LOS SANTOS"),
    "domicilio":           os.getenv("DOMICILIO", "Camargo 111, CABA"),
    "ing_brutos":          os.getenv("ING_BRUTOS", "exenta"),
    "inicio_actividades":  os.getenv("INICIO_ACTIVIDADES", "01/07/2014"),
    "pto_vta":             PTO_VTA,
}

app = FastAPI(title="Facturadora AFIP", docs_url=None, redoc_url=None)


# ── Models ────────────────────────────────────────────────────────────────────

class InvoiceItem(BaseModel):
    date: str
    description: str
    amount: float
    receptor_cuit: str
    receptor_nombre: str = ""
    receptor_domicilio: str = ""
    concepto: int = 2
    use_month_period: bool = True


class InvoiceRequest(BaseModel):
    items: list[InvoiceItem]


class InvoiceResult(BaseModel):
    cbte_nro: int
    cae: str
    cae_vto: str
    fecha: str
    importe: float
    receptor_cuit: str
    receptor_nombre: str = ""
    receptor_domicilio: str = ""
    concepto: int = 2
    fch_serv_desde: str | None = None
    fch_serv_hasta: str | None = None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/config")
def get_config():
    return {
        "cuit": CUIT,
        "testing": TESTING,
        "certs_available": afip.certs_available(),
        "pto_vta": PTO_VTA,
        "env": "Homologación (testing)" if TESTING else "Producción",
    }


@app.get("/api/receptor-info/{cuit}")
def receptor_info(cuit: str):
    try:
        return afip.get_receptor_info(cuit)
    except Exception:
        return {"nombre": "", "domicilio": ""}


@app.post("/api/parse-excel")
async def parse_excel(file: UploadFile):
    if not (file.filename or "").lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Solo se aceptan archivos Excel (.xlsx).")
    content = await file.read()
    try:
        items = parse_invoice_excel(content)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(422, f"No se pudo procesar el Excel: {e}")
    return {"items": items, "total": len(items)}


@app.post("/api/parse-pdf")
async def parse_pdf(file: UploadFile):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Solo se aceptan archivos PDF.")
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(400, "El archivo no puede superar 20 MB.")
    try:
        transfers = parse_santander_pdf(content)
    except Exception as e:
        raise HTTPException(422, f"No se pudo procesar el PDF: {e}")
    return {"transfers": transfers, "total": len(transfers)}


@app.post("/api/facturar")
def facturar(req: InvoiceRequest):
    if not afip.certs_available():
        raise HTTPException(
            503,
            "Certificado digital no configurado. "
            "Copiá cert.crt y private.key en la carpeta certs/ y reiniciá el servidor.",
        )
    results = []
    for item in req.items:
        try:
            invoice = afip.create_invoice(
                pto_vta=PTO_VTA,
                receptor_cuit=item.receptor_cuit,
                importe=item.amount,
                concepto=item.concepto,
                fecha=item.date,
                use_month_period=item.use_month_period,
            )
            invoice["receptor_nombre"]    = item.receptor_nombre
            invoice["receptor_domicilio"] = item.receptor_domicilio
            results.append({"success": True, **invoice})
        except AFIPError as e:
            results.append({"success": False, "error": str(e)})
        except Exception as e:
            results.append({"success": False, "error": f"Error inesperado: {e}"})
    return {"results": results}


@app.post("/api/preview-pdf")
def preview_pdf(data: InvoiceResult):
    pdf_bytes = generate_invoice_pdf(data.model_dump(), PDF_CONFIG)
    pto = str(PTO_VTA).zfill(5)
    nro = str(data.cbte_nro).zfill(8)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="FactC_{pto}_{nro}.pdf"'},
    )


@app.post("/api/facturar-pdf")
def facturar_pdf(item: InvoiceItem):
    if not afip.certs_available():
        raise HTTPException(503, "Certificado digital no configurado.")
    try:
        invoice = afip.create_invoice(
            pto_vta=PTO_VTA,
            receptor_cuit=item.receptor_cuit,
            importe=item.amount,
            concepto=item.concepto,
            fecha=item.date,
            use_month_period=item.use_month_period,
        )
    except AFIPError as e:
        raise HTTPException(400, str(e))

    pdf_bytes = generate_invoice_pdf(invoice, PDF_CONFIG)
    pto  = str(PTO_VTA).zfill(5)
    nro  = str(invoice["cbte_nro"]).zfill(8)
    filename = f"FactC_{pto}_{nro}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Static (must be last) ─────────────────────────────────────────────────────
app.mount("/", StaticFiles(directory=str(BASE_DIR / "static"), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
