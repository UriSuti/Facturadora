import base64
import calendar
import datetime
import ssl
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter


class _WeakDHAdapter(HTTPAdapter):
    """AFIP usa claves DH de 1024 bits; Python 3.x las rechaza por defecto."""
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


_session = requests.Session()
_session.mount("https://", _WeakDHAdapter())

WSAA_URL = {
    "homo": "https://wsaahomo.afip.gov.ar/ws/services/LoginCms",
    "prod": "https://wsaa.afip.gov.ar/ws/services/LoginCms",
}
WSFE_URL = {
    "homo": "https://wswhomo.afip.gov.ar/wsfev1/service.asmx",
    "prod": "https://servicios1.afip.gov.ar/wsfev1/service.asmx",
}
WSFE_NS  = "http://ar.gov.afip.dif.FEV1/"

CBTE_TIPO_C  = 11
DOC_TIPO_CUIT = 80
DOC_TIPO_CF   = 99
TZ_AR = datetime.timezone(datetime.timedelta(hours=-3))


class AFIPError(Exception):
    pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _valid_cuit(cuit: str) -> bool:
    cuit = cuit.replace("-", "").strip()
    if len(cuit) != 11 or not cuit.isdigit():
        return False
    factors = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    total = sum(int(cuit[i]) * factors[i] for i in range(10))
    check = 11 - (total % 11)
    if check == 11: check = 0
    if check == 10: return False
    return check == int(cuit[10])


def _normalize_date(date_str: str) -> str:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(date_str.strip(), fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    return datetime.datetime.now(TZ_AR).strftime("%Y%m%d")


def _month_range(yyyymmdd: str) -> tuple[str, str]:
    dt = datetime.datetime.strptime(yyyymmdd, "%Y%m%d")
    first = dt.replace(day=1).strftime("%Y%m%d")
    last  = dt.replace(day=calendar.monthrange(dt.year, dt.month)[1]).strftime("%Y%m%d")
    return first, last


def _tag(el: ET.Element, name: str) -> str:
    found = el.find(f".//{{{WSFE_NS}}}{name}")
    return found.text or "" if found is not None else ""


# ── WSAA ──────────────────────────────────────────────────────────────────────

def _build_tra() -> bytes:
    now    = datetime.datetime.now(TZ_AR).replace(microsecond=0)
    expire = now + datetime.timedelta(hours=10)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<loginTicketRequest version="1.0">'
        "<header>"
        f"<uniqueId>{int(now.timestamp())}</uniqueId>"
        f"<generationTime>{now.isoformat()}</generationTime>"
        f"<expirationTime>{expire.isoformat()}</expirationTime>"
        "</header>"
        "<service>wsfe</service>"
        "</loginTicketRequest>"
    ).encode("utf-8")


def _sign_cms(data: bytes, cert_path: str, key_path: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
        tmp.write(data)
        tra_path = tmp.name
    try:
        result = subprocess.run(
            [
                "openssl", "cms", "-sign",
                "-in",     tra_path,
                "-signer", cert_path,
                "-inkey",  key_path,
                "-nodetach",
                "-outform", "DER",
            ],
            capture_output=True,
            check=True,
        )
        return base64.b64encode(result.stdout).decode("ascii")
    except subprocess.CalledProcessError as e:
        raise AFIPError(f"Error firmando CMS: {e.stderr.decode()}") from e
    finally:
        Path(tra_path).unlink(missing_ok=True)


def _call_wsaa(cms_b64: str, env: str) -> tuple[str, str, str]:
    soap = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:wsaa="http://wsaa.view.sua.dvadac.desein.afip.gov.ar">'
        "<soapenv:Header/><soapenv:Body>"
        f"<wsaa:loginCms><wsaa:in0>{cms_b64}</wsaa:in0></wsaa:loginCms>"
        "</soapenv:Body></soapenv:Envelope>"
    )
    resp = _session.post(
        WSAA_URL[env], data=soap.encode("utf-8"),
        headers={"Content-Type": "text/xml;charset=UTF-8", "SOAPAction": '""'},
        timeout=30,
    )
    resp.raise_for_status()
    root   = ET.fromstring(resp.text)
    ns_wsaa = "http://wsaa.view.sua.dvadac.desein.afip.gov.ar"
    ta_xml = root.find(f".//{{{ns_wsaa}}}loginCmsReturn").text
    ta     = ET.fromstring(ta_xml)
    return (
        ta.find(".//token").text,
        ta.find(".//sign").text,
        ta.find(".//expirationTime").text,
    )


# ── WSFE (raw SOAP) ───────────────────────────────────────────────────────────

def _wsfe(env: str, action: str, body: str) -> ET.Element:
    soap = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:ar="{WSFE_NS}">'
        "<soapenv:Header/>"
        f"<soapenv:Body>{body}</soapenv:Body>"
        "</soapenv:Envelope>"
    )
    resp = _session.post(
        WSFE_URL[env], data=soap.encode("utf-8"),
        headers={
            "Content-Type": "text/xml;charset=UTF-8",
            "SOAPAction": f'"{WSFE_NS}{action}"',
        },
        timeout=30,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    result = root.find(f".//{{{WSFE_NS}}}{action}Result")
    if result is None:
        raise AFIPError(f"Respuesta inesperada de WSFE:\n{resp.text[:400]}")
    # Check for top-level errors
    for err in result.findall(f".//{{{WSFE_NS}}}Err"):
        code = err.findtext(f"{{{WSFE_NS}}}Code") or ""
        msg  = err.findtext(f"{{{WSFE_NS}}}Msg") or ""
        raise AFIPError(f"WSFE {code}: {msg}")
    return result


def _auth_xml(token: str, sign: str, cuit: str) -> str:
    return (
        f"<ar:Auth>"
        f"<ar:Token>{token}</ar:Token>"
        f"<ar:Sign>{sign}</ar:Sign>"
        f"<ar:Cuit>{cuit}</ar:Cuit>"
        f"</ar:Auth>"
    )


# ── Client ────────────────────────────────────────────────────────────────────

class AFIPClient:
    def __init__(self, cuit: str, cert_path: str, key_path: str, testing: bool = True):
        self.cuit      = cuit
        self.cert_path = cert_path
        self.key_path  = key_path
        self.env       = "homo" if testing else "prod"
        self._token:   str | None = None
        self._sign:    str | None = None
        self._expires: str | None = None

    def certs_available(self) -> bool:
        return Path(self.cert_path).exists() and Path(self.key_path).exists()

    def _refresh_ticket(self) -> None:
        if not self.certs_available():
            raise AFIPError(
                "Certificado no encontrado. "
                "Copiá cert.crt y private.key en la carpeta certs/."
            )
        tra    = _build_tra()
        cms    = _sign_cms(tra, self.cert_path, self.key_path)
        self._token, self._sign, self._expires = _call_wsaa(cms, self.env)

    def _get_token_sign(self) -> tuple[str, str]:
        now = datetime.datetime.now(TZ_AR).replace(microsecond=0).isoformat()
        if not self._token or not self._expires or now >= self._expires:
            self._refresh_ticket()
        return self._token, self._sign

    def test_connection(self) -> bool:
        result = _wsfe(self.env, "FEDummy", "<ar:FEDummy/>")
        return _tag(result, "AppServer") == "OK"

    def _last_cbte(self, pto_vta: int) -> int:
        token, sign = self._get_token_sign()
        body = (
            f"<ar:FECompUltimoAutorizado>"
            f"{_auth_xml(token, sign, self.cuit)}"
            f"<ar:PtoVta>{pto_vta}</ar:PtoVta>"
            f"<ar:CbteTipo>{CBTE_TIPO_C}</ar:CbteTipo>"
            f"</ar:FECompUltimoAutorizado>"
        )
        result = _wsfe(self.env, "FECompUltimoAutorizado", body)
        return int(_tag(result, "CbteNro") or "0")

    def create_invoice(
        self,
        pto_vta: int,
        receptor_cuit: str,
        importe: float,
        concepto: int = 2,
        fecha: str | None = None,
        use_month_period: bool = True,
    ) -> dict:
        token, sign = self._get_token_sign()

        fecha_str = _normalize_date(fecha) if fecha else datetime.datetime.now(TZ_AR).strftime("%Y%m%d")
        importe   = round(float(importe), 2)

        cuit_clean = receptor_cuit.replace("-", "").strip()
        if cuit_clean and _valid_cuit(cuit_clean):
            doc_tipo, doc_nro = DOC_TIPO_CUIT, cuit_clean
        else:
            doc_tipo, doc_nro = DOC_TIPO_CF, "0"

        next_cbte = self._last_cbte(pto_vta) + 1

        # Service period
        desde = hasta = None
        service_dates = ""
        if concepto in (2, 3):
            desde, hasta = _month_range(fecha_str) if use_month_period else (fecha_str, fecha_str)
            service_dates = (
                f"<ar:FchServDesde>{desde}</ar:FchServDesde>"
                f"<ar:FchServHasta>{hasta}</ar:FchServHasta>"
                f"<ar:FchVtoPago>{fecha_str}</ar:FchVtoPago>"
            )

        body = (
            f"<ar:FECAESolicitar>"
            f"{_auth_xml(token, sign, self.cuit)}"
            f"<ar:FeCAEReq>"
            f"<ar:FeCabReq>"
            f"<ar:CantReg>1</ar:CantReg>"
            f"<ar:PtoVta>{pto_vta}</ar:PtoVta>"
            f"<ar:CbteTipo>{CBTE_TIPO_C}</ar:CbteTipo>"
            f"</ar:FeCabReq>"
            f"<ar:FeDetReq><ar:FECAEDetRequest>"
            f"<ar:Concepto>{concepto}</ar:Concepto>"
            f"<ar:DocTipo>{doc_tipo}</ar:DocTipo>"
            f"<ar:DocNro>{doc_nro}</ar:DocNro>"
            f"<ar:CbteDesde>{next_cbte}</ar:CbteDesde>"
            f"<ar:CbteHasta>{next_cbte}</ar:CbteHasta>"
            f"<ar:CbteFch>{fecha_str}</ar:CbteFch>"
            f"<ar:ImpTotal>{importe:.2f}</ar:ImpTotal>"
            f"<ar:ImpTotConc>0</ar:ImpTotConc>"
            f"<ar:ImpNeto>{importe:.2f}</ar:ImpNeto>"
            f"<ar:ImpOpEx>0</ar:ImpOpEx>"
            f"<ar:ImpIVA>0</ar:ImpIVA>"
            f"<ar:ImpTrib>0</ar:ImpTrib>"
            f"<ar:MonId>PES</ar:MonId>"
            f"<ar:MonCotiz>1</ar:MonCotiz>"
            f"{service_dates}"
            f"</ar:FECAEDetRequest></ar:FeDetReq>"
            f"</ar:FeCAEReq>"
            f"</ar:FECAESolicitar>"
        )

        result = _wsfe(self.env, "FECAESolicitar", body)

        det = result.find(f".//{{{WSFE_NS}}}FECAEDetResponse")
        if det is None:
            raise AFIPError("Respuesta de WSFE sin detalle de comprobante.")

        resultado = _tag(det, "Resultado")
        if resultado != "A":
            obs = " | ".join(
                f"{o.findtext(f'{{{WSFE_NS}}}Code')}: {o.findtext(f'{{{WSFE_NS}}}Msg')}"
                for o in det.findall(f".//{{{WSFE_NS}}}Obs")
            )
            raise AFIPError(f"Comprobante rechazado: {obs or 'sin detalle'}")

        return {
            "cbte_nro":       next_cbte,
            "cae":            _tag(det, "CAE"),
            "cae_vto":        _tag(det, "CAEFchVto"),
            "fecha":          fecha_str,
            "importe":        importe,
            "receptor_cuit":  cuit_clean,
            "concepto":       concepto,
            "fch_serv_desde": desde,
            "fch_serv_hasta": hasta,
        }
