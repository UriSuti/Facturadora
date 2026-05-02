# Facturadora AFIP

App web para emitir **Facturas C** (Monotributista) directamente desde el browser, conectada a la API oficial de AFIP/ARCA.

## Qué hace

- Emite Facturas C electrónicas via WSFE (Web Service de Facturación Electrónica de AFIP)
- Genera el PDF del comprobante con QR oficial de AFIP para descarga inmediata
- Parsea extractos bancarios de Santander Argentina para detectar ingresos facturables automáticamente
- Valida el CUIT del receptor con dígito verificador

## Requisitos

- Python 3.11 o superior
- `openssl` instalado (viene por defecto en macOS/Linux)
- Certificado digital autorizado en el portal de AFIP ([ver instrucciones](#certificado-digital))

## Instalación

```bash
git clone https://github.com/TU_USUARIO/facturadora.git
cd facturadora

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuración

```bash
cp .env.example .env
```

Editá `.env` con tus datos:

```env
CUIT=000000000
PTO_VTA=2
CERT_PATH=certs/cert.crt
KEY_PATH=certs/private.key
TESTING=false
```

Copiá los archivos del certificado en la carpeta `certs/`:
```
certs/
├── cert.crt      ← descargado del portal AFIP
└── private.key   ← generado localmente con openssl
```

## Correr la app

```bash
source venv/bin/activate
python main.py
```

Abrí [http://localhost:8000](http://localhost:8000) en el browser.

---

## Certificado Digital

Para conectarse a la API de AFIP necesitás un certificado digital vinculado a tu CUIT.

### Generar la clave y el pedido de certificado

```bash
openssl genrsa -out certs/private.key 4096

openssl req -new -key certs/private.key \
  -subj "/C=AR/O=TU NOMBRE/serialNumber=CUIT TU_CUIT/CN=facturadora" \
  -out certs/request.csr
```

### Registrar el certificado en AFIP

1. Ingresá a [afip.gob.ar](https://afip.gob.ar) con tu CUIT y clave fiscal
2. Ir a **Administrador de Relaciones de Clave Fiscal**
3. **Nueva Relación** → ARCA → Web Services → **Facturación Electrónica**
4. Tipo de representante: **Computador Fiscal** → ponerle un nombre (ej: `facturadora`)
5. Subir el archivo `certs/request.csr`
6. Descargar el `cert.crt` que genera AFIP y guardarlo en `certs/`

---

## Usar en otro dispositivo

Los archivos sensibles **no están en el repositorio** por seguridad. Tenés que transferirlos manualmente.

### Archivos que necesitás copiar

| Archivo | Dónde va |
|---|---|
| `cert.crt` | `certs/cert.crt` |
| `private.key` | `certs/private.key` |
| `.env` | raíz del proyecto |

### Recomendación

Guardá estos tres archivos en una carpeta privada en Google Drive (o iCloud) para tenerlos disponibles cuando necesites instalar la app en otro dispositivo. Simplemente los descargás y los ponés en su lugar.

```bash
# En el nuevo dispositivo, después de clonar el repo:
# 1. Copiar .env a la raíz
# 2. Copiar cert.crt y private.key a certs/
# 3. Instalar dependencias y correr

source venv/bin/activate
pip install -r requirements.txt
python main.py
```

> ⚠️ **No compartas estos archivos con nadie.** Con `private.key` + `cert.crt` cualquiera puede emitir facturas a tu nombre sin necesitar tu contraseña de AFIP.

---

## Estructura del proyecto

```
facturadora/
├── main.py          # Servidor FastAPI
├── afip.py          # Cliente WSAA + WSFE (autenticación y facturación)
├── pdf_parser.py    # Parseo de extractos Santander Argentina
├── invoice_pdf.py   # Generación del PDF del comprobante
├── requirements.txt
├── .env.example     # Plantilla de configuración
├── certs/           # Certificados (no se suben a git)
└── static/
    └── index.html   # Frontend
```
