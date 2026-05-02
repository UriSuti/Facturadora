import base64
import io
import json

import segno
from fpdf import FPDF

# ── Paleta ────────────────────────────────────────────────────────────────────
_PRIMARY   = (26,  58,  92)
_WHITE     = (255, 255, 255)
_BLACK     = (30,  41,  59)
_GRAY_BG   = (248, 250, 252)
_GRAY_TEXT = (100, 116, 139)
_BORDER    = (226, 232, 240)

CONCEPTO_LABEL = {1: "Productos", 2: "Servicios", 3: "Productos y Servicios"}


# ── Formatters ────────────────────────────────────────────────────────────────

def _fmt_cuit(c: str) -> str:
    c = c.replace("-", "")
    return f"{c[:2]}-{c[2:10]}-{c[10]}" if len(c) == 11 else c


def _fmt_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[6:8]}/{yyyymmdd[4:6]}/{yyyymmdd[:4]}"


def _fmt_amount(n: float) -> str:
    # Argentine format: 1.234,56
    s = f"{n:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"$ {s}"


# ── QR AFIP ───────────────────────────────────────────────────────────────────

def _qr_url(invoice: dict, config: dict) -> str:
    fecha = invoice["fecha"]  # YYYYMMDD
    data = {
        "ver": 1,
        "fecha": f"{fecha[:4]}-{fecha[4:6]}-{fecha[6:8]}",
        "cuit": int(config["cuit"].replace("-", "")),
        "ptoVta": config["pto_vta"],
        "tipoCmp": 11,
        "nroCmp": invoice["cbte_nro"],
        "importe": invoice["importe"],
        "moneda": "PES",
        "ctz": 1,
        "tipoDocRec": 80,
        "nroDocRec": int(invoice["receptor_cuit"].replace("-", "")),
        "tipoCodAut": "E",
        "codAut": int(invoice["cae"]),
    }
    b64 = base64.b64encode(
        json.dumps(data, separators=(",", ":")).encode()
    ).decode()
    return f"https://www.afip.gob.ar/fe/qr/?p={b64}"


def _qr_png(url: str) -> bytes:
    buf = io.BytesIO()
    segno.make_qr(url).save(buf, kind="png", scale=6, border=1)
    return buf.getvalue()


# ── PDF ───────────────────────────────────────────────────────────────────────

def generate_invoice_pdf(invoice: dict, config: dict) -> bytes:
    """
    invoice : dict retornado por AFIPClient.create_invoice()
    config  : {"cuit", "razon_social", "domicilio", "pto_vta"}
    Retorna : bytes del PDF
    """
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()
    pdf.set_margins(0, 0, 0)
    pdf.set_auto_page_break(False)

    M  = 15   # margen
    CW = 180  # ancho de contenido

    def _fc(*rgb): pdf.set_fill_color(*rgb)
    def _tc(*rgb): pdf.set_text_color(*rgb)
    def _dc(*rgb): pdf.set_draw_color(*rgb)

    # ── Bloque tipo comprobante (azul) ────────────────────────────────────────
    _fc(*_PRIMARY); _dc(*_PRIMARY)
    pdf.rect(M, 15, 52, 35, "F")

    _tc(*_WHITE)
    pdf.set_font("Helvetica", "B", 42)
    pdf.set_xy(M, 16); pdf.cell(52, 20, "C", align="C")
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(M, 36); pdf.cell(52, 5, "FACTURA", align="C")
    pdf.set_font("Helvetica", "", 7)
    pdf.set_xy(M, 41); pdf.cell(52, 5, "ORIGINAL", align="C")

    # ── Bloque número + fecha ─────────────────────────────────────────────────
    _fc(*_GRAY_BG); _dc(*_BORDER)
    pdf.set_line_width(0.3)
    pdf.rect(M + 52, 15, CW - 52, 35, "FD")

    _tc(*_GRAY_TEXT)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_xy(M + 57, 17); pdf.cell(120, 4, "N° DE COMPROBANTE")

    _tc(*_BLACK)
    pdf.set_font("Helvetica", "B", 14)
    pto  = str(config["pto_vta"]).zfill(5)
    nro  = str(invoice["cbte_nro"]).zfill(8)
    pdf.set_xy(M + 57, 22); pdf.cell(120, 8, f"{pto}-{nro}")

    _tc(*_GRAY_TEXT)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_xy(M + 57, 31); pdf.cell(120, 4, "FECHA DE EMISIÓN")

    _tc(*_BLACK)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_xy(M + 57, 36); pdf.cell(120, 7, _fmt_date(invoice["fecha"]))

    # ── Emisor ────────────────────────────────────────────────────────────────
    y = 57
    _tc(*_GRAY_TEXT)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_xy(M, y); pdf.cell(CW, 4, "DATOS DEL EMISOR")

    y += 5
    _tc(*_BLACK)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_xy(M, y); pdf.cell(CW, 6, config["razon_social"])

    rows = [
        ("CUIT:",          _fmt_cuit(config["cuit"])),
        ("Condición IVA:", "Monotributista"),
        ("Domicilio:",     config["domicilio"]),
    ]
    for label, value in rows:
        y += 6
        _tc(*_GRAY_TEXT)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_xy(M, y); pdf.cell(32, 5, label)
        _tc(*_BLACK)
        pdf.set_xy(M + 32, y); pdf.cell(CW - 32, 5, value)

    # ── Separador ─────────────────────────────────────────────────────────────
    y += 10
    _dc(*_BORDER)
    pdf.line(M, y, M + CW, y)

    # ── Receptor ──────────────────────────────────────────────────────────────
    y += 5
    _tc(*_GRAY_TEXT)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_xy(M, y); pdf.cell(CW, 4, "DATOS DEL RECEPTOR")

    y += 5
    _tc(*_GRAY_TEXT)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(M, y); pdf.cell(32, 5, "CUIT:")
    _tc(*_BLACK)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(M + 32, y); pdf.cell(CW - 32, 5, _fmt_cuit(invoice["receptor_cuit"]))

    # Período de servicio
    if invoice.get("fch_serv_desde") and invoice.get("fch_serv_hasta"):
        y += 6
        _tc(*_GRAY_TEXT)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_xy(M, y); pdf.cell(38, 5, "Período de servicio:")
        _tc(*_BLACK)
        desde = _fmt_date(invoice["fch_serv_desde"])
        hasta = _fmt_date(invoice["fch_serv_hasta"])
        pdf.set_xy(M + 38, y); pdf.cell(CW - 38, 5, f"{desde} al {hasta}")

    # ── Tabla de items ────────────────────────────────────────────────────────
    y += 14

    _fc(*_PRIMARY); _dc(*_PRIMARY)
    pdf.rect(M, y, CW, 7, "F")
    _tc(*_WHITE)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_xy(M + 2, y); pdf.cell(CW - 42, 7, "DESCRIPCIÓN", align="L")
    pdf.set_xy(M + CW - 40, y); pdf.cell(38, 7, "IMPORTE", align="R")

    y += 7
    _fc(*_WHITE); _dc(*_BORDER)
    pdf.set_line_width(0.3)
    pdf.rect(M, y, CW, 9, "FD")

    _tc(*_BLACK)
    pdf.set_font("Helvetica", "", 9)
    desc = CONCEPTO_LABEL.get(invoice.get("concepto", 2), "Servicios")
    pdf.set_xy(M + 2, y); pdf.cell(CW - 42, 9, desc, align="L")
    pdf.set_xy(M + CW - 40, y)
    pdf.cell(38, 9, _fmt_amount(invoice["importe"]), align="R")

    # ── Totales ───────────────────────────────────────────────────────────────
    y += 14
    _dc(*_BORDER)
    pdf.line(M + CW - 72, y, M + CW, y)

    y += 3
    _tc(*_GRAY_TEXT)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(M + CW - 72, y); pdf.cell(30, 6, "No incluye IVA", align="L")
    _tc(*_BLACK)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(M + CW - 42, y); pdf.cell(40, 6, _fmt_amount(invoice["importe"]), align="R")

    y += 7
    _fc(*_PRIMARY); _dc(*_PRIMARY)
    pdf.rect(M + CW - 72, y, 72, 9, "F")
    _tc(*_WHITE)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_xy(M + CW - 72, y); pdf.cell(30, 9, "TOTAL", align="L")
    pdf.set_xy(M + CW - 42, y); pdf.cell(40, 9, _fmt_amount(invoice["importe"]), align="R")

    # ── CAE + QR ──────────────────────────────────────────────────────────────
    y += 20

    qr_url  = _qr_url(invoice, config)
    qr_data = _qr_png(qr_url)
    pdf.image(io.BytesIO(qr_data), x=M, y=y, w=36, h=36)

    tx = M + 40
    _tc(*_GRAY_TEXT)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_xy(tx, y); pdf.cell(CW - 40, 5, "COMPROBANTE AUTORIZADO POR AFIP")

    y += 7
    _tc(*_GRAY_TEXT)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(tx, y); pdf.cell(20, 5, "CAE:")
    _tc(*_BLACK)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_xy(tx + 20, y); pdf.cell(CW - 60, 5, invoice["cae"])

    y += 8
    _tc(*_GRAY_TEXT)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(tx, y); pdf.cell(28, 5, "Vto. CAE:")
    _tc(*_BLACK)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_xy(tx + 28, y); pdf.cell(CW - 68, 5, _fmt_date(invoice["cae_vto"]))

    y += 10
    _tc(*_GRAY_TEXT)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_xy(tx, y); pdf.cell(CW - 40, 5, "Verificá en www.afip.gob.ar/fe/qr")

    # ── Footer ────────────────────────────────────────────────────────────────
    _dc(*_BORDER)
    pdf.line(M, 283, M + CW, 283)
    _tc(*_GRAY_TEXT)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_xy(M, 285)
    pdf.cell(CW, 5,
             f"{config['razon_social']}  -  CUIT {_fmt_cuit(config['cuit'])}  -  Monotributista",
             align="C")

    return bytes(pdf.output())
