#!/bin/sh
# Install as a system service under an existing non-root user; requires sudo/root.
set -eu
if [ "$(id -u)" -ne 0 ]; then
    echo 'Ejecutar con sudo: sudo ./install-linux-service.sh USUARIO_EXISTENTE' >&2
    exit 1
fi
account=${1:?Indicá el usuario existente que será dueño de sus datos}
id "$account" >/dev/null
if [ "$(id -u "$account")" -eq 0 ]; then
    echo 'Elegí un usuario de servicio o de trabajo distinto de root.' >&2
    exit 1
fi
package=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test -x "$package/EchoScopeRadar" || { echo 'Falta el ejecutable Linux junto al instalador.' >&2; exit 1; }
account_home=$(getent passwd "$account" | cut -d: -f6)
account_group=$(id -gn "$account")
data="$account_home/.local/share/EchoScopeRadar"
install -d -m 755 /opt/echoscope-radar
cp -a "$package/." /opt/echoscope-radar/
install -d -m 700 -o "$account" -g "$account_group" "$data"
if [ ! -f "$data/instalacion.env" ]; then
    install -m 600 -o "$account" -g "$account_group" "$package/instalacion.env.example" "$data/instalacion.env"
    printf '\nECHOSCOPE_DATA_DIR=%s\n' "$data" >> "$data/instalacion.env"
fi
# systemd command paths escape spaces and percent specifiers literally.
escaped_data=$(printf '%s' "$data" | sed 's/%/%%/g; s/\\/\\\\/g; s/"/\\"/g')
cat > /etc/systemd/system/echoscope-radar.service <<EOF
[Unit]
Description=EchoScope Radar background monitoring
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$account
Group=$account_group
WorkingDirectory=/opt/echoscope-radar
Environment="HOME=$account_home"
ExecStart=/opt/echoscope-radar/EchoScopeRadar --env-file "$escaped_data/instalacion.env" --no-browser
Restart=on-failure
RestartSec=10
TimeoutStopSec=30
UMask=0077
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now echoscope-radar.service
systemctl --no-pager status echoscope-radar.service
printf '\nConfiguración: %s/instalacion.env\nDatos: %s\n' "$data" "$data"
