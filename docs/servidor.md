# EchoScope Radar en un servidor compartido

## Seguimiento permanente desde 0.12.0

Después de iniciar sesión y configurar las fuentes, elegí **Iniciar seguimiento**. La intención queda guardada por cuenta. Al reiniciar el servidor, se recuperan los espacios activos sin esperar otro inicio de sesión. Cerrar el navegador o cerrar sesión mantiene la captura. **Pausar seguimiento** guarda la pausa y evita la recuperación automática.

Para cuentas propias, elegí esa modalidad en el formulario de fuente. La propiedad es declarada por el operador. La lectura y los permisos se comprueban por separado al consultar. Las redes con acceso pendiente permanecen desactivadas.

El archivo deploy/echoscope.service es una plantilla para Ubuntu. Prepará una cuenta de servicio llamada echoscope, instalá el proyecto y su entorno en /opt/echoscope y el archivo de configuración en /etc/echoscope/instalacion.env. Configurá SERVER_DIR, BIND, ORIGIN, TLS_CERT, TLS_KEY y MASTER_KEY. Copiá la unidad a /etc/systemd/system y ejecutá systemctl daemon-reload y systemctl enable --now echoscope. Revisá journalctl -u echoscope. Estas operaciones las realiza el administrador de la instalación.

En Windows, usá el Programador de tareas con una cuenta de servicio autorizada. Creá una tarea con desencadenador **Al iniciar el sistema**, ejecutable C:/ruta/proyecto/.venv/Scripts/echoscope-web.exe y argumentos --env-file C:/EchoScopeRadar/instalacion.env --no-browser. Configurá el directorio de trabajo y los permisos de datos, certificados y archivo de entorno. Usá una única instancia y recuperación ante error. El archivo de entorno debe contener SERVER_DIR para iniciar el servidor compartido. Las credenciales del sistema se introducen mediante la interfaz de Windows.

El servidor sigue sujeto a MAX_WORKSPACES y a los límites de concurrencia. Un fallo de apertura de un espacio activo se informa durante el arranque para que el administrador pueda corregirlo. Esta entrega proporciona plantillas e instrucciones y no instala servicios automáticamente.

Cada cuenta tiene fuentes, historial, estado de alertas y claves propios. El modo compartido requiere HTTPS y una carpeta privada de datos bajo la cuenta del servicio. El ejecutable abierto con doble clic sigue iniciando la edición local. En la edición local, las claves cargadas en la aplicación duran la sesión.

## Preparar el servidor

1. Instalá las dependencias con `uv sync --locked --extra youtube`. Prepará un certificado TLS válido para el nombre del servidor y su clave privada.
2. Creá una cuenta desde la terminal. El comando pide la contraseña dos veces y guarda su verificador. Repetilo por cada usuario y reiniciá el servidor después de crear o cambiar cuentas.

   ```powershell
   uv run --no-sync echoscope-web --server-dir C:/EchoScope/datos --set-password analista
   ```

3. Generá una clave maestra una sola vez. En PowerShell podés generar el valor y asignarlo a la variable del proceso sin imprimirlo. Guardá ese mismo valor en el almacén de secretos del servicio para usarlo en cada reinicio.

   ```powershell
   $env:ECHOSCOPE_MASTER_KEY = uv run --no-sync python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

4. Iniciá el servidor con el nombre y el puerto que realmente usarán las personas. Para compartirlo, indicá en `--bind` la IP del servidor que corresponde a la red autorizada. El ejemplo usa una IP y un nombre ilustrativos.

   ```powershell
   uv run --no-sync echoscope-web --server-dir C:/EchoScope/datos --bind 192.168.1.20 --port 8765 --origin https://radar.example.org:8765 --tls-cert C:/EchoScope/tls/fullchain.pem --tls-key C:/EchoScope/tls/privkey.pem
   ```

5. Abrí la dirección HTTPS en el navegador, iniciá sesión y elegí **Iniciar seguimiento**. **Cerrar sesión** termina el acceso del navegador. Para detener la captura de tu cuenta, usá **Pausar seguimiento**.

Respaldá la carpeta de datos y guardá la clave maestra por separado. Si cambia la clave maestra, las claves API guardadas dejan de poder abrirse. La primera ejecución de esta versión actualiza la base local existente. El servidor usa bases nuevas por cuenta.

## Buscadores y claves API

En **Claves API**, elegí YouTube, Brave Search, Tavily o Google mediante Serper. Poné un nombre reconocible a cada clave y usá **Usar** para seleccionar la activa de ese proveedor. Solo las claves activas se emplean en las consultas. El texto del tema se envía a los buscadores habilitados. No se envían tus otras claves.

También podés guardar claves de redes sociales, proveedores de inteligencia artificial y servicios que agregues mediante **Otro proveedor**. Las claves indicadas como **Solo almacenamiento** quedan cifradas en tu cuenta y no se utilizan en consultas ni reportes. Agregar una clave no habilita un conector ni envía datos al servicio.

Para habilitar SearXNG, el administrador puede indicar la URL base HTTPS pública con `ECHOSCOPE_SEARXNG_URL`. La instancia debe permitir respuestas JSON. Los motores que consulta dependen de la configuración de esa instancia. [API de SearXNG](https://docs.searxng.org/dev/search_api)

La cobertura se puede ampliar incorporando adaptadores a `TopicDiscovery` cuando exista acceso a una API y se puedan comprobar sus resultados, cuotas y atribución. Google mediante Serper usa un proveedor intermediario. La API clásica de Bing está retirada y Google Custom Search JSON no admite nuevos clientes. [Retiro de Bing](https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement) · [Google Custom Search JSON](https://developers.google.com/custom-search/v1/overview)
