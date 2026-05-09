import base64
import io
import json

import segno
from fpdf import FPDF

# ── Colores ───────────────────────────────────────────────────────────────────
_BLACK  = (0,   0,   0)
_WHITE  = (255, 255, 255)
_LGRAY  = (200, 200, 200)  # bordes

CONCEPTO_LABEL = {1: "Productos", 2: "Servicios", 3: "Productos y Servicios"}


# ── Formatters ────────────────────────────────────────────────────────────────

def _fc(pdf, r, g, b): pdf.set_fill_color(r, g, b)
def _tc(pdf, r, g, b): pdf.set_text_color(r, g, b)
def _dc(pdf, r, g, b): pdf.set_draw_color(r, g, b)


def _fmt_cuit(c: str) -> str:
    c = c.replace("-", "")
    return f"{c[:2]}-{c[2:10]}-{c[10]}" if len(c) == 11 else c


def _fmt_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[6:8]}/{yyyymmdd[4:6]}/{yyyymmdd[:4]}"


def _fmt_amount(n: float) -> str:
    s = f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


# ── QR AFIP ───────────────────────────────────────────────────────────────────

def _qr_url(invoice: dict, config: dict) -> str:
    fecha = invoice["fecha"]
    data = {
        "ver":        1,
        "fecha":      f"{fecha[:4]}-{fecha[4:6]}-{fecha[6:8]}",
        "cuit":       int(config["cuit"].replace("-", "")),
        "ptoVta":     config["pto_vta"],
        "tipoCmp":    11,
        "nroCmp":     invoice["cbte_nro"],
        "importe":    invoice["importe"],
        "moneda":     "PES",
        "ctz":        1,
        "tipoDocRec": 80,
        "nroDocRec":  int(invoice["receptor_cuit"].replace("-", "")),
        "tipoCodAut": "E",
        "codAut":     int(invoice["cae"]),
    }
    b64 = base64.b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()
    return f"https://www.afip.gob.ar/fe/qr/?p={b64}"


def _qr_png(url: str) -> bytes:
    from PIL import Image as PILImage
    # Generar QR con segno
    buf_raw = io.BytesIO()
    segno.make_qr(url).save(buf_raw, kind="png", scale=8, border=4, dark="black", light="white")
    buf_raw.seek(0)
    # Convertir a RGB con Pillow para que fpdf2 lo embeba correctamente
    img = PILImage.open(buf_raw).convert("RGB")
    buf_out = io.BytesIO()
    img.save(buf_out, format="PNG")
    buf_out.seek(0)
    return buf_out.read()


# ── Una pagina de la factura ──────────────────────────────────────────────────

def _draw_page(pdf: FPDF, invoice: dict, config: dict, copy_label: str) -> None:
    pdf.add_page()
    pdf.set_margins(0, 0, 0)
    pdf.set_auto_page_break(False)

    M  = 10   # margen
    PW = 210  # ancho pagina
    CW = PW - 2 * M   # 190mm

    # Coordenadas de columnas del header
    # Izquierda: M .. M+83      (83mm)
    # Centro:    M+83 .. M+113  (30mm)
    # Derecha:   M+113 .. M+CW  (77mm)
    LC = M           # left col x
    LW = 83          # left col width
    CC = M + LW      # center col x
    CX = 30          # center col width
    RC = CC + CX     # right col x
    RW = CW - LW - CX  # right col width  (~77mm)

    header_h = 55
    header_y = 10

    # ── Borde exterior del header ─────────────────────────────────────────────
    _dc(pdf, *_LGRAY)
    pdf.set_line_width(0.3)
    pdf.rect(M, header_y, CW, header_h, "D")

    # ── Lineas divisoras verticales ───────────────────────────────────────────
    pdf.line(CC, header_y, CC, header_y + header_h)
    pdf.line(RC, header_y, RC, header_y + header_h)

    # ── COLUMNA IZQUIERDA: datos del emisor ───────────────────────────────────
    _tc(pdf, *_BLACK)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_xy(LC + 2, header_y + 3)
    pdf.cell(LW - 4, 6, config["razon_social"])

    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(LC + 2, header_y + 10)
    pdf.cell(LW - 4, 5, config["domicilio"])

    pdf.set_xy(LC + 2, header_y + 20)
    pdf.cell(LW - 4, 5, f"Condicion frente al IVA: Monotributo")

    pdf.set_xy(LC + 2, header_y + 26)
    pdf.multi_cell(LW - 4, 4, f"Domicilio Comercial: {config['domicilio']}", align="L")

    # ── COLUMNA CENTRAL: letra y codigo ──────────────────────────────────────
    _fc(pdf, *_BLACK)
    _tc(pdf, *_BLACK)
    pdf.set_font("Helvetica", "B", 40)
    pdf.set_xy(CC, header_y + 5)
    pdf.cell(CX, 25, "C", align="C")

    pdf.set_font("Helvetica", "", 7)
    pdf.set_xy(CC, header_y + 32)
    pdf.cell(CX, 5, "COD. 011", align="C")

    # ── COLUMNA DERECHA: tipo + datos del comprobante ─────────────────────────
    _tc(pdf, *_BLACK)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_xy(RC + 2, header_y + 3)
    pdf.cell(RW / 2 - 2, 7, "FACTURA", align="L")
    pdf.set_xy(RC + RW / 2, header_y + 3)
    pdf.cell(RW / 2 - 2, 7, copy_label, align="R")

    rows_r = [
        ("Fecha de Emision:",              _fmt_date(invoice["fecha"])),
        ("CUIT:",                          _fmt_cuit(config["cuit"])),
        ("Ingresos Brutos:",               config.get("ing_brutos", "exenta")),
        ("Fecha de Inicio de Actividades:", config.get("inicio_actividades", "")),
    ]
    y_r = header_y + 13
    pdf.set_font("Helvetica", "", 7)
    for label, value in rows_r:
        pdf.set_xy(RC + 2, y_r)
        pdf.cell(32, 4, label)
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_xy(RC + 34, y_r)
        pdf.cell(RW - 36, 4, value)
        pdf.set_font("Helvetica", "", 7)
        y_r += 5

    pto  = str(config["pto_vta"]).zfill(5)
    nro  = str(invoice["cbte_nro"]).zfill(8)
    pdf.set_xy(RC + 2, y_r)
    pdf.cell(32, 4, "Punto de Venta:")
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_xy(RC + 34, y_r)
    pdf.cell(RW - 36, 4, f"{pto}  Comp. Nro: {nro}")

    # ── SECCION PERIODO ───────────────────────────────────────────────────────
    y = header_y + header_h
    period_h = 12
    _dc(pdf, *_LGRAY)
    pdf.rect(M, y, CW, period_h, "D")

    desde = _fmt_date(invoice.get("fch_serv_desde") or invoice["fecha"])
    hasta = _fmt_date(invoice.get("fch_serv_hasta") or invoice["fecha"])

    pdf.set_font("Helvetica", "", 8)
    _tc(pdf, *_BLACK)
    pdf.set_xy(M + 2, y + 2)
    pdf.cell(50, 4, f"Periodo Facturado Desde: {desde}")
    pdf.set_xy(M + 52, y + 2)
    pdf.cell(40, 4, f"Hasta: {hasta}")
    pdf.set_xy(M + 95, y + 2)
    pdf.cell(55, 4, f"Fecha de Vto. para el pago: {_fmt_date(invoice['fecha'])}")

    pdf.set_xy(M + 2, y + 7)
    pdf.cell(40, 4, "Condicion de venta: Contado")

    # ── SECCION RECEPTOR ──────────────────────────────────────────────────────
    y += period_h
    recep_h = 22
    _dc(pdf, *_LGRAY)
    pdf.rect(M, y, CW, recep_h, "D")

    nombre    = invoice.get("receptor_nombre", "").upper()
    domicilio = invoice.get("receptor_domicilio", "")

    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(M + 2, y + 2)
    pdf.cell(55, 4, "Apellido y Nombre / Razon Social:")
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_xy(M + 57, y + 2)
    pdf.cell(80, 4, nombre)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(RC, y + 2)
    pdf.cell(RW, 4, f"CUIT: {_fmt_cuit(invoice['receptor_cuit'])}", align="R")

    pdf.set_xy(M + 2, y + 8)
    pdf.cell(35, 4, "Condicion frente al IVA:")
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_xy(M + 37, y + 8)
    pdf.cell(60, 4, "Consumidor Final")

    if domicilio:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_xy(M + 2, y + 14)
        pdf.cell(22, 4, "Domicilio:")
        pdf.set_xy(M + 24, y + 14)
        pdf.cell(CW - 24, 4, domicilio)

    # ── TABLA DE ITEMS: encabezado ────────────────────────────────────────────
    y += recep_h
    table_header_h = 8

    _dc(pdf, *_LGRAY)
    pdf.set_fill_color(230, 230, 230)
    pdf.rect(M, y, CW, table_header_h, "FD")

    cols = [
        ("Codigo Producto / Servicio", 65, "L"),
        ("Cantidad",                   18, "C"),
        ("U. Medida",                  20, "C"),
        ("Precio Unit.",               22, "R"),
        ("% Bonif",                    16, "C"),
        ("Imp. Bonif.",                20, "R"),
        ("Subtotal",                   29, "R"),
    ]
    pdf.set_font("Helvetica", "B", 7)
    _tc(pdf, *_BLACK)
    xc = M
    for label, w, align in cols:
        pdf.set_xy(xc, y + 1)
        pdf.cell(w, table_header_h - 2, label, align=align)
        xc += w

    # ── TABLA DE ITEMS: filas ─────────────────────────────────────────────────
    y += table_header_h
    row_h = 8
    desc = CONCEPTO_LABEL.get(invoice.get("concepto", 2), "Servicios")
    importe = invoice["importe"]

    _dc(pdf, *_LGRAY)
    pdf.rect(M, y, CW, row_h, "D")

    pdf.set_font("Helvetica", "", 8)
    xc = M
    row_data = [
        (desc,                65, "L"),
        ("1,00",              18, "C"),
        ("unidades",          20, "C"),
        (_fmt_amount(importe), 22, "R"),
        ("0,00",              16, "C"),
        ("0,00",              20, "R"),
        (_fmt_amount(importe), 29, "R"),
    ]
    for value, w, align in row_data:
        pdf.set_xy(xc, y + 1)
        pdf.cell(w, row_h - 2, value, align=align)
        xc += w

    # Filas vacías (para que se vea el espacio como en el original)
    for _ in range(3):
        y += row_h
        pdf.rect(M, y, CW, row_h, "D")

    # ── TOTALES ───────────────────────────────────────────────────────────────
    y += row_h
    tot_x = M + CW - 80

    _dc(pdf, *_LGRAY)

    # Subtotal
    pdf.rect(M, y, CW - 80, 7, "D")
    pdf.rect(tot_x, y, 80, 7, "D")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(tot_x + 2, y + 1.5)
    pdf.cell(55, 4, "Subtotal: $", align="R")
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_xy(tot_x + 57, y + 1.5)
    pdf.cell(21, 4, _fmt_amount(importe), align="R")

    y += 7
    # Otros tributos
    pdf.rect(M, y, CW - 80, 7, "D")
    pdf.rect(tot_x, y, 80, 7, "D")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(tot_x + 2, y + 1.5)
    pdf.cell(55, 4, "Importe Otros Tributos: $", align="R")
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_xy(tot_x + 57, y + 1.5)
    pdf.cell(21, 4, "0,00", align="R")

    y += 7
    # Total
    pdf.rect(M, y, CW - 80, 7, "D")
    pdf.rect(tot_x, y, 80, 7, "D")
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(tot_x + 2, y + 1.5)
    pdf.cell(55, 4, "Importe Total: $", align="R")
    pdf.set_xy(tot_x + 57, y + 1.5)
    pdf.cell(21, 4, _fmt_amount(importe), align="R")

    # ── CAE + QR ──────────────────────────────────────────────────────────────
    y += 14
    qr_url  = _qr_url(invoice, config)
    qr_data = _qr_png(qr_url)
    qr_size = 35

    # QR: esquina inferior derecha del bloque CAE
    qr_x = M + CW - qr_size
    qr_y = y

    _tc(pdf, *_BLACK)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(M, y)
    pdf.cell(50, 5, f"CAE N°: {invoice['cae']}")
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(M, y + 6)
    pdf.cell(55, 5, f"Fecha de Vto. de CAE: {_fmt_date(invoice['cae_vto'])}")

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(M, y + 13)
    pdf.cell(50, 5, "Comprobante Autorizado")

    pdf.set_font("Helvetica", "", 7)
    _tc(pdf, 120, 120, 120)
    pdf.set_xy(M, y + 19)
    pdf.multi_cell(M + CW - qr_size - 10, 3.5,
                   "Esta Agencia no se responsabiliza por los datos\n"
                   "ingresados en el detalle de la operacion", align="L")

    pdf.image(io.BytesIO(qr_data), x=qr_x, y=qr_y, w=qr_size, h=qr_size)

    # ── FOOTER ────────────────────────────────────────────────────────────────
    _tc(pdf, *_BLACK)
    _dc(pdf, *_LGRAY)
    pdf.line(M, 285, M + CW, 285)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_xy(M, 286)
    pdf.cell(CW / 2, 5, f'"{config["razon_social"]}"', align="L")
    pdf.set_xy(M + CW / 2, 286)
    pdf.cell(CW / 2, 5, "Pag. 1/1", align="R")


# ── Generador principal ───────────────────────────────────────────────────────

def generate_invoice_pdf(invoice: dict, config: dict) -> bytes:
    """
    Genera un PDF con 3 paginas: ORIGINAL, DUPLICADO, TRIPLICADO.
    invoice : dict retornado por AFIPClient.create_invoice()
    config  : {"cuit", "razon_social", "domicilio", "ing_brutos",
               "inicio_actividades", "pto_vta"}
    """
    pdf = FPDF(orientation="P", unit="mm", format="A4")

    for copy_label in ("ORIGINAL", "DUPLICADO", "TRIPLICADO"):
        _draw_page(pdf, invoice, config, copy_label)

    return bytes(pdf.output())
