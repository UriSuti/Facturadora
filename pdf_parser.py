import io
import re
from typing import Optional

import pdfplumber

# ── Exclusions ────────────────────────────────────────────────────────────────
# Fuentes no facturables: bancos, inversiones, renta, organismos

_EXCLUDED = [
    # Brokers / inversiones
    r"invertironline",
    r"\biol\b",
    r"portfolio\s*personal",
    r"\bppi\b",
    r"balanz",
    r"bull\s*market",
    r"naci[oó]n\s*burs[aá]til",
    r"fondos?\s*com[uú]n",
    r"allaria",
    r"cohen\s*(sa)?",
    r"mariva",
    r"tpcedear",
    # Bancos (transferencias propias u operaciones interbancarias)
    r"banco\s+(santander|galicia|naci[oó]n|bbva|macro|hsbc|icbc|ciudad|patagonia|hipotecario|ita[uú]|supervielle|comafi|industrial|credicoop|piano)",
    r"santander\s*(r[ií]o)?",
    r"\bbrubank\b",
    r"\bnaranja\b",
    r"\bual[aá]\b",
    # Intereses / rendimientos
    r"inter[eé]s(es)?",
    r"rendimiento",
    r"caja\s*ahorro",
    r"plazo\s*fijo",
    r"fci\b",
    # Organismos
    r"\bafip\b",
    r"\banses\b",
    r"jubilaci[oó]n",
    r"pensi[oó]n",
    r"asignaci[oó]n\s*familiar",
    # Reintegros / devoluciones
    r"reintegro",
    r"devoluci[oó]n",
    r"reversa",
    # Sueldo (si aplica)
    r"\bsueldo\b",
    r"\bhaberes?\b",
    r"liquidaci[oó]n\s*de\s*sueldos",
]

_EXCLUDED_RE = re.compile("|".join(_EXCLUDED), re.IGNORECASE)

# ── Transfer detection ─────────────────────────────────────────────────────────
_TRANSFER_KW = re.compile(
    r"transfer|acreditac|dep[oó]sito|pago\s+de|ingreso|recib[io]|enviado\s+por|créd\.?",
    re.IGNORECASE,
)

# ── Amount: Argentine format (1.234,56 or 1234,56 or 1234.56) ─────────────────
_AMOUNT_RE = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}|\d+\.\d{2}")

_DATE_RE = re.compile(r"\b(\d{2}[/-]\d{2}[/-]\d{4})\b")


# ── Public API ────────────────────────────────────────────────────────────────

def parse_santander_pdf(pdf_bytes: bytes) -> list[dict]:
    """
    Parse a Santander Argentina account statement PDF.
    Returns all credit (income) entries; excluded ones have excluded=True.
    """
    results: list[dict] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            if tables:
                for table in tables:
                    results.extend(_from_table(table))
            else:
                text = page.extract_text() or ""
                results.extend(_from_text(text))

    # Deduplicate by (date, amount, description)
    seen: set[tuple] = set()
    unique: list[dict] = []
    for r in results:
        key = (r["date"], r["amount"], r["description"][:40])
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return unique


# ── Table parser ──────────────────────────────────────────────────────────────

def _from_table(table: list[list]) -> list[dict]:
    if not table or len(table) < 2:
        return []

    header = [str(c).lower().strip() if c else "" for c in table[0]]
    date_col = _col(header, ["fecha", "date", "fch"])
    desc_col = _col(header, ["concepto", "descripci", "detalle", "movimiento", "referencia"])
    credit_col = _col(header, ["haber", "cr[eé]d", "credito", "crédito", "entrada", "ingreso", "acreditac"])
    debit_col = _col(header, ["debe", "d[eé]bit", "debito", "débito", "salida", "egreso"])

    results = []
    for row in table[1:]:
        if not row:
            continue
        date_raw = _cell(row, date_col)
        description = _cell(row, desc_col) or _longest_text(row, {date_col, credit_col, debit_col})
        credit_raw = _cell(row, credit_col)

        if not date_raw or not credit_raw:
            continue

        amount = _parse_amount(credit_raw)
        if not amount or amount <= 0:
            continue

        date_match = _DATE_RE.search(date_raw)
        if not date_match:
            continue

        results.append(_make_entry(date_match.group(0), description, amount))

    return results


# ── Text parser ───────────────────────────────────────────────────────────────

def _from_text(text: str) -> list[dict]:
    results = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        date_match = _DATE_RE.search(line)
        if not date_match:
            continue
        if not _TRANSFER_KW.search(line):
            continue
        amounts = _AMOUNT_RE.findall(line)
        if not amounts:
            continue
        # In a typical layout: date | description | debit | credit | balance
        # Credit is the second-to-last amount (balance is last)
        amount_str = amounts[-2] if len(amounts) >= 2 else amounts[-1]
        amount = _parse_amount(amount_str)
        if not amount or amount <= 0:
            continue
        results.append(_make_entry(date_match.group(0), line, amount))
    return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_entry(date: str, description: str, amount: float) -> dict:
    excluded = bool(_EXCLUDED_RE.search(description))
    return {
        "date": date.replace("-", "/"),
        "description": description.strip(),
        "amount": amount,
        "excluded": excluded,
        "selected": not excluded,
        "receptor_cuit": "",
    }


def _col(header: list[str], patterns: list[str]) -> Optional[int]:
    for i, h in enumerate(header):
        for p in patterns:
            if re.search(p, h, re.IGNORECASE):
                return i
    return None


def _cell(row: list, col: Optional[int]) -> str:
    if col is None or col >= len(row):
        return ""
    v = row[col]
    return str(v).strip() if v is not None else ""


def _longest_text(row: list, skip: set) -> str:
    best = ""
    for i, cell in enumerate(row):
        if i in skip or cell is None:
            continue
        s = str(cell).strip()
        if len(s) > len(best) and not _DATE_RE.fullmatch(s) and not _AMOUNT_RE.fullmatch(s):
            best = s
    return best


def _parse_amount(s: str) -> Optional[float]:
    """Convert Argentine format (1.234,56) to float."""
    s = s.strip().replace(" ", "")
    if not s:
        return None
    # Find all amount-like patterns and take the last one
    matches = _AMOUNT_RE.findall(s)
    if not matches:
        return None
    raw = matches[-1]
    # Argentine: period = thousands separator, comma = decimal
    raw = raw.replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None
