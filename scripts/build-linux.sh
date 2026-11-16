#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export UV_PROJECT_ENVIRONMENT=.cache/linux-build-venv
uv sync --locked --extra youtube --extra bundle
uv run --no-sync ruff check src tests
uv run --no-sync pytest -q -m 'not internet and not performance'
version=$(uv run --no-sync python -c 'from importlib.metadata import version; print(version("echoscope-radar"))')
release="dist/$version"
name=EchoScopeRadar-linux-x86_64
uv run --no-sync pyinstaller --noconfirm --name EchoScopeRadar --paths src \
    --collect-data echoscope --collect-data alembic --copy-metadata echoscope-radar \
    --hidden-import sqlalchemy.dialects.sqlite.aiosqlite \
    --hidden-import sqlalchemy.dialects.sqlite.pysqlite \
    --hidden-import sqlalchemy.ext.asyncio --hidden-import aiosqlite --hidden-import grpc \
    --add-data "$PWD/src/echoscope/storage/migrations:echoscope/storage/migrations" \
    --workpath .cache/pyinstaller-linux --specpath .cache \
    --distpath .cache/linux-bundle scripts/linux_entry.py
mkdir -p "$release/$name"
cp -a .cache/linux-bundle/EchoScopeRadar/. "$release/$name/"
cp scripts/install-linux-service.sh "$release/$name/"
cp deploy/instalacion.env.example "$release/$name/"
cp docs/inicio-automatico-y-distribuciones.md docs/almacenamiento-y-acceso.md \
   docs/prensa-y-segundo-plano.md docs/servidor.md CHANGELOG.md "$release/$name/"
cat > "$release/$name/abrir-echoscope.sh" <<'EOF'
#!/bin/sh
cd "$(dirname "$0")"
exec ./EchoScopeRadar "$@"
EOF
chmod 755 "$release/$name/EchoScopeRadar" "$release/$name/install-linux-service.sh" \
    "$release/$name/abrir-echoscope.sh"
tar -czf "$release/EchoScopeRadar-$version-linux-x86_64.tar.gz" -C "$release" "$name"
echo "Paquete Linux: $release/$name"
