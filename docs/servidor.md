# EchoScope Radar en un servidor compartido

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
