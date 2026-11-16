param(
    [string]$PackagePath = $PSScriptRoot,
    [string]$DataDirectory = (Join-Path $env:LOCALAPPDATA 'EchoScopeRadar'),
    [switch]$Remove,
    [switch]$NoStart
)
$ErrorActionPreference = 'Stop'
$taskName = 'EchoScopeRadar-' + [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
if ($Remove) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    Remove-ItemProperty -LiteralPath $runKey -Name 'EchoScopeRadar' -ErrorAction SilentlyContinue
    Write-Output 'Inicio automático desactivado; datos conservados.'
    exit 0
}
$package = (Resolve-Path -LiteralPath $PackagePath).Path
if (-not (Test-Path -LiteralPath (Join-Path $package 'EchoScopeRadar.exe'))) {
    throw 'PackagePath debe indicar la carpeta distribuible que contiene EchoScopeRadar.exe.'
}
$dataPath = [IO.Path]::GetFullPath($DataDirectory)
$version = (Get-Content -LiteralPath (Join-Path $package 'VERSION.txt') -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'Versión de paquete inválida.' }
$installPath = Join-Path $dataPath ('app\' + $version)
New-Item -ItemType Directory -Path $installPath -Force | Out-Null
# Copy, never move or delete the operator's existing files or database.
Copy-Item -Path (Join-Path $package '*') -Destination $installPath -Recurse -Force
$exePath = Join-Path $installPath 'EchoScopeRadar.exe'
$envPath = Join-Path $dataPath 'instalacion.env'
if (-not (Test-Path -LiteralPath $envPath)) {
    $template = Join-Path $package 'instalacion.env.example'
    $config = if (Test-Path -LiteralPath $template) { Get-Content -LiteralPath $template -Raw -Encoding UTF8 } else { '' }
    $config += "`r`nECHOSCOPE_DATA_DIR=" + ($dataPath -replace '\\','/') + "`r`n"
    [IO.File]::WriteAllText($envPath, $config, [Text.UTF8Encoding]::new($false))
}
$arguments = '--env-file "' + $envPath + '" --no-browser'
$mode = 'Programador de tareas: inicio de sesión'
try {
    $action = New-ScheduledTaskAction -Execute $exePath -Argument $arguments -WorkingDirectory $installPath
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
    $principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal `
        -Settings $settings -Description 'EchoScope Radar en segundo plano, sin navegador. Datos de la cuenta actual.' `
        -Force | Out-Null
    Remove-ItemProperty -LiteralPath $runKey -Name 'EchoScopeRadar' -ErrorAction SilentlyContinue
    if (-not $NoStart) { Start-ScheduledTask -TaskName $taskName }
} catch {
    if ($_.Exception -isnot [UnauthorizedAccessException] -and $_.Exception.Message -notmatch 'denegado|denied|0x80070005') {
        throw
    }
    $mode = 'Inicio de Windows: cuenta actual (permisos limitados)'
    New-Item -Path $runKey -Force | Out-Null
    New-ItemProperty -LiteralPath $runKey -Name 'EchoScopeRadar' -Value ('"' + $exePath + '" ' + $arguments) `
        -PropertyType String -Force | Out-Null
    if (-not $NoStart) { Start-Process -FilePath $exePath -ArgumentList $arguments -WorkingDirectory $installPath -WindowStyle Hidden }
}
[pscustomobject]@{ Startup = $mode; Task = $taskName; Executable = $exePath; Configuration = $envPath; Data = $dataPath }
