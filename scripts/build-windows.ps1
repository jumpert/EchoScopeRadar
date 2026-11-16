$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
$env:UV_PROJECT_ENVIRONMENT = Join-Path (Get-Location) '.cache/windows-build-venv'
$migrations = Join-Path (Get-Location) 'src/echoscope/storage/migrations'
$icon = Join-Path (Get-Location) 'src/echoscope/web_assets/ciberdefensa.png'
$versionLine = Select-String -LiteralPath 'pyproject.toml' -Pattern '^version = "([0-9]+\.[0-9]+\.[0-9]+)"$'
$version = $versionLine.Matches[0].Groups[1].Value
$release = Join-Path (Get-Location) "dist/$version"
$package = Join-Path $release 'EchoScopeRadar'
uv sync --locked --extra youtube --extra windows-build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run --no-sync pyinstaller --noconfirm --windowed --name EchoScopeRadar `
    --icon $icon `
    --paths src --collect-data echoscope --collect-data alembic --copy-metadata echoscope-radar `
    --hidden-import sqlalchemy.dialects.sqlite.aiosqlite --hidden-import sqlalchemy.dialects.sqlite.pysqlite `
    --hidden-import sqlalchemy.ext.asyncio --hidden-import aiosqlite --hidden-import grpc `
    --add-data "$migrations;echoscope/storage/migrations" `
    --workpath .cache/pyinstaller --specpath .cache --distpath $release scripts/windows_entry.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Copy-Item -LiteralPath 'Probar EchoScope Radar.cmd', 'Abrir EchoScope Radar.cmd' -Destination $package
Copy-Item -LiteralPath 'docs/uso-administrativo.md', 'docs/fuentes-uruguay.md', 'CHANGELOG.md' -Destination $package
Copy-Item -LiteralPath 'docs/servidor.md' -Destination $package
Copy-Item -Path 'docs/documento-*.md', 'docs/auditoria-inicial.md', 'docs/informe-validacion.md' -Destination $package
Copy-Item -LiteralPath '.env.example' -Destination $package
Copy-Item -LiteralPath 'docs/dependency-audit.json' -Destination $package
Copy-Item -LiteralPath 'docs/fuentes-uruguay-conexiones.md', 'docs/consulta-base-datos.md', 'docs/validacion-comentarios.md', 'deploy/echoscope.service' -Destination $package
Copy-Item -LiteralPath 'docs/consulta-visual-y-prensa.md' -Destination $package
Copy-Item -LiteralPath 'docs/prensa-y-segundo-plano.md', 'docs/auditoria-prensa-2026-11-13.json' -Destination $package
Copy-Item -LiteralPath 'docs/almacenamiento-y-acceso.md' -Destination $package
Copy-Item -LiteralPath 'docs/assets' -Destination $package -Recurse -Force
Copy-Item -LiteralPath 'scripts/install-windows-startup.ps1', 'deploy/instalacion.env.example', 'docs/inicio-automatico-y-distribuciones.md' -Destination $package
[IO.File]::WriteAllText((Join-Path $package 'VERSION.txt'), $version, [Text.UTF8Encoding]::new($false))
uv run --no-sync python scripts/package-windows.py $package (Join-Path $release "EchoScopeRadar-$version-windows-x86_64.zip")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
