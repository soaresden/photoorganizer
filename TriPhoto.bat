@echo off
rem TriPhoto - double-clic pour lancer (voir TriPhoto.ps1 pour les options)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0TriPhoto.ps1" %*
if errorlevel 1 pause
