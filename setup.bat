@echo off
echo ============================================
echo   Instalando Facturadora AFIP...
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no esta instalado.
    echo Descargalo de https://www.python.org/downloads/
    echo Asegurate de marcar "Add Python to PATH" durante la instalacion.
    pause
    exit /b 1
)

echo Creando entorno virtual...
python -m venv venv

echo Instalando dependencias...
call venv\Scripts\activate
pip install -r requirements.txt

echo.
echo ============================================
echo   Instalacion completada.
echo ============================================
echo.
echo Proximos pasos:
echo  1. Copia tu cert.crt a la carpeta certs\
echo  2. Copia tu private.key a la carpeta certs\
echo  3. Copia .env.example a .env y editalo con tus datos
echo  4. Ejecuta start.bat para arrancar la app
echo.
pause
