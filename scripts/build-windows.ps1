$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
$env:UV_PROJECT_ENVIRONMENT = Join-Path (Get-Location) '.cache/windows-build-venv'
$migrations = Join-Path (Get-Location) 'src/echoscope/storage/migrations'
uv sync --locked --extra youtube --extra windows-build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run --no-sync pyinstaller --noconfirm --windowed --name EchoScopeRadar `
    --paths src --collect-data echoscope --collect-data alembic --copy-metadata echoscope-radar `
    --hidden-import sqlalchemy.dialects.sqlite.aiosqlite --hidden-import sqlalchemy.dialects.sqlite.pysqlite `
    --hidden-import sqlalchemy.ext.asyncio --hidden-import aiosqlite --hidden-import grpc `
    --add-data "$migrations;echoscope/storage/migrations" `
    --workpath .cache/pyinstaller --specpath .cache --distpath dist scripts/windows_entry.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Copy-Item -LiteralPath 'Probar EchoScope Radar.cmd', 'Abrir EchoScope Radar.cmd' -Destination 'dist/EchoScopeRadar'
Copy-Item -LiteralPath 'docs/uso-administrativo.md', 'docs/fuentes-uruguay.md', 'CHANGELOG.md' -Destination 'dist/EchoScopeRadar'
