@echo off
title Control Docentes - Servidor
cd /d "%~dp0"
echo Iniciando el servidor de Control Docentes...
echo No cierres esta ventana mientras uses el sistema.
echo.
echo Accede desde este mismo equipo en: http://127.0.0.1:8000/admin/
echo Accede desde otra computadora de la red en: http://192.168.101.6:8000/admin/
echo (si no carga, la IP pudo haber cambiado - revisa con "ipconfig")
echo.
venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
pause
