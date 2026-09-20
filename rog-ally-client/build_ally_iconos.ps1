# Compila RemotePlay_Ally.exe con los iconos empaquetados (2026-09-20).
# Igual que build_ally.ps1 de siempre, pero: --add-data de los iconos, registro completo en un
# archivo (el original tiraba todo a Out-Null y un fallo no dejaba rastro) y sin tocar la copia de E:.
$py = 'C:\ps3rp-build\python\python.exe'
$log = 'C:\ps3rp-build\build_ally_last.log'
$exe = 'C:\ps3rp-build\dist\RemotePlay_Ally.exe'
Set-Location 'C:\ps3rp-build\src'

if (Test-Path $exe) { Copy-Item $exe 'C:\ps3rp-build\dist\RemotePlay_Ally.exe.previo' -Force }
$inicio = Get-Date

& $py -m PyInstaller --noconfirm --onefile --windowed --name "RemotePlay_Ally" `
    --distpath "C:\ps3rp-build\dist" --workpath "C:\ps3rp-build\pyibuild" --specpath "C:\ps3rp-build" `
    --add-data "C:\ps3rp-build\src\iconos;iconos" `
    main_client.py *> $log

if ((Test-Path $exe) -and ((Get-Item $exe).LastWriteTime -gt $inicio)) {
    $i = Get-Item $exe
    Write-Output ("BUILD OK: {0} bytes, {1}" -f $i.Length, $i.LastWriteTime)
} else {
    Write-Output "BUILD FALLO - ultimas lineas del registro:"
    Get-Content $log -Tail 25
}
