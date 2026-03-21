REM @echo off
REM Activar el entorno virtual

@if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo Entorno virtual 'venv' activado.
) else if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    echo Entorno virtual '.venv' activado.
) else (
    echo No se encontro el entorno virtual. Crealo con: python -m venv venv
    exit /b 1
)

