# Inicio automático y distribuciones · 0.15.0

## Windows de esta computadora

El instalador se ejecuta con la cuenta habitual y coloca una copia del programa fuera de OneDrive:

```text
C:\Users\user\AppData\Local\EchoScopeRadar\app\0.15.0\EchoScopeRadar.exe
```

La configuración persistente y los datos quedan en:

```text
C:\Users\user\AppData\Local\EchoScopeRadar\instalacion.env
C:\Users\user\AppData\Local\EchoScopeRadar\administracion.sqlite
```

La instalación configura una tarea `EchoScopeRadar-<SID de la cuenta>` al **iniciar sesión en Windows**, con `--no-browser`, sin ventana ni navegador, sin límite de 72 horas y sin detenerse por pasar a batería. La tarea ignora intentos simultáneos y reintenta hasta diez veces ante un fallo del proceso. Una salida normal elegida desde la aplicación no provoca un reinicio inmediato.

Si Windows no permite registrar la tarea con esta cuenta, el instalador utiliza **Inicio de Windows** mediante el valor propio `EchoScopeRadar` de `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. Esta alternativa también se inicia al entrar a la sesión, y no dispone de los reintentos del Programador de tareas.

Con los permisos actuales esto **no es un servicio anterior al inicio de sesión**. Si nadie inicia sesión, la aplicación de esta cuenta no arranca. Para una instalación que deba capturar antes de iniciar sesión hay que preparar una cuenta de servicio y una tarea al inicio del sistema con un administrador. No se guardan contraseñas de Windows ni se configura ejecución como SYSTEM.

Para instalar o actualizar desde una distribución descomprimida:

```powershell
powershell -NoProfile -File .\install-windows-startup.ps1
```

Para desactivar el inicio automático sin borrar los datos:

```powershell
powershell -NoProfile -File .\install-windows-startup.ps1 -Remove
```

La copia de cada versión se conserva en una carpeta distinta. Para actualizar, terminá la versión anterior mediante **Salir y detener captura**, ejecutá el instalador nuevo y verificá que se retoma el seguimiento. No copies una base mientras su escritor esté activo.

## Linux

La distribución `EchoScopeRadar-0.15.0-linux-x86_64.tar.gz` contiene un ejecutable Linux y sus bibliotecas en `_internal`. Se compiló para Linux **x86_64 con glibc 2.36 o posterior**, por ejemplo Debian 12 y Ubuntu 24.04. No es para ARM, Alpine/musl ni macOS. Conservá toda la carpeta extraída.

```sh
tar -xzf EchoScopeRadar-0.15.0-linux-x86_64.tar.gz
cd EchoScopeRadar-linux-x86_64
./abrir-echoscope.sh
```

Para un servicio que arranque al encender Linux, sin esperar una sesión gráfica, indicá un usuario Linux existente distinto de root:

```sh
sudo ./install-linux-service.sh TU_USUARIO
```

El instalador coloca el programa en `/opt/echoscope-radar`, crea y habilita `echoscope-radar.service` con systemd y lo ejecuta bajo ese usuario. Los datos se conservan en `~TU_USUARIO/.local/share/EchoScopeRadar`; el archivo de configuración es `instalacion.env` dentro de esa carpeta. Requiere una distribución con systemd y acceso sudo; no se instala un servicio en el equipo Windows por generar el paquete Linux.

```sh
sudo systemctl status echoscope-radar
sudo systemctl restart echoscope-radar
sudo systemctl disable --now echoscope-radar
journalctl -u echoscope-radar
```

## Dónde cambiar la dirección y el dominio

Los parámetros ya están centralizados en **instalacion.env**. La precedencia es: variables del sistema, archivo pasado con `--env-file` o `ECHOSCOPE_ENV_FILE`, `.env` junto al programa y, cuando no existe ese `.env`, `instalacion.env` en la carpeta de datos del usuario. Reiniciá el proceso después de cambiar el archivo. El instalador conserva un archivo existente.

| Parámetro | Función |
|---|---|
| `ECHOSCOPE_BIND` | Interfaz de escucha del proceso; actualmente `127.0.0.1` |
| `ECHOSCOPE_PORT` | Puerto de escucha; actualmente `8765` |
| `ECHOSCOPE_ORIGIN` | Dirección HTTPS exacta del servidor compartido, por ejemplo `https://radar.ejemplo.uy` |
| `ECHOSCOPE_SERVER_DIR` | Carpeta de cuentas y bases del modo servidor |
| `ECHOSCOPE_TLS_CERT` / `ECHOSCOPE_TLS_KEY` | Certificado y clave del servidor HTTPS |
| `ECHOSCOPE_MASTER_KEY` | Clave maestra estable para las credenciales privadas del servidor |
| `ECHOSCOPE_DATA_DIR` | Carpeta de datos de la estación local |

**ORIGIN no es una configuración de DNS ni convierte por sí solo la edición local en un servidor público.** Para utilizar un dominio en red se habilita el modo servidor con cuentas, TLS y los parámetros anteriores, siguiendo [servidor.md](servidor.md). El DNS debe apuntar a la dirección del servidor y el certificado debe corresponder al dominio. Para ocultar el puerto en la dirección pública se utiliza HTTPS en 443, normalmente mediante un proxy configurado por el administrador. El puerto interno del motor puede seguir siendo 8765.

El modo servidor crea bases independientes por cuenta. No cambia automáticamente la base local existente: si se migra a ese modo, hay que planificar la transferencia de datos. No se habilitó acceso remoto ni se modificaron DNS, certificados o firewall en esta entrega.

Las claves API cargadas solo para una sesión no sobreviven al reinicio del proceso. Para captura desatendida, configurá las variables de proveedores necesarias en `instalacion.env` o usá el almacén persistente del modo servidor. No incluyas claves reales al compartir las distribuciones.

## Encendido, suspensión y acceso

Después del arranque correspondiente, abrí `http://127.0.0.1:8765/` desde el mismo equipo. La captura no requiere mantener el navegador abierto. Apagar, hibernar o suspender detiene temporalmente la ejecución; no se captura contenido mientras el equipo no está funcionando. Tras reiniciar se retoma desde los cursores guardados, sujeto a la ventana de cada proveedor.

## Reproducir las compilaciones

Windows se genera con `scripts/build-windows.ps1`. Linux se genera dentro de Linux con `sh scripts/build-linux.sh`, o desde este equipo con:

```powershell
docker build -f deploy/Dockerfile.linux --output type=local,dest=dist/0.15.0 .
```

Las distribuciones se encuentran bajo `dist/0.15.0/`. Windows incluye un ZIP y Linux un TAR.GZ. Los instaladores de inicio automático van incluidos en cada paquete; no se incorporan bases, claves privadas ni archivos `.env` personales.
