@echo off
setlocal

echo Menghentikan window Radmon yang dibuat oleh launcher utama ...
for %%T in (
  "RADMON CENTRAL"
  "RADMON PUBLIC"
  "RADMON SYNC"
  "RADMON ADMIN"
  "RADMON DETECTOR"
  "RADMON DUMMY"
) do (
  taskkill /FI "WINDOWTITLE eq %%~T*" /T /F >nul 2>&1
)

echo Selesai. Proses lain di luar window RADMON tidak disentuh.
exit /b 0
