# Informe final de funcionamiento, seguridad y puesta en práctica

Versión 0.11.0 · 12 de noviembre de 2026

## Trabajo realizado

La auditoría inicial se hizo sobre v0.10.0 antes de modificar la configuración y las conexiones. Se revisaron dominio, motor, conectores, rutas HTTP, autenticación, secretos, persistencia, reportes, puntos de entrada y empaquetado.

Los cambios posteriores introducen configuración tipada, fábrica de persistencia, interfaces segregadas e inyección, y corrigen los hallazgos verificables descritos abajo.

## Resultado de seguridad

| Hallazgo | Resolución |
|---|---|
| FileLock 3.32.7 con 13 avisos en la consulta de dependencias | Actualizado a 4.2.10, repetición de pruebas de escritor |
| Acoplamiento a SQLite en administración y CLI | Fábrica común por URL y selección de adaptador, contratos EngineStore/RadarStore |
| Puertos, rutas y capacidad incrustados | RuntimeSettings, .env.example y argumentos explícitos |
| API acepta hashes de revisión sin una alerta propia | Comprueba persistencia vigente y ventana de sesión del usuario antes de guardar |
| Decisiones huérfanas tras purga | Limpieza de alert_reviews sin observaciones conservadas |
| Cambios de revisión sin evento operativo | Evento de auditoría por cambio de estado |
| Respuestas JSON completas de YouTube y Brave | Lectura acotada y errores tipados |
| Cabeceras omitidas en rechazos tempranos | Middleware de cabeceras aplicado a respuestas de error |
| Posible exposición de parámetros SQL | hide_parameters y respuestas de error operativas |
| Parada abrupta del servidor web local por SIGTERM | Cierre coordinado del motor y conexiones |
| CLI Windows falla al redirigir determinados caracteres | UTF-8 explícito con sustitución de caracteres no representables |

La consulta final de pip-audit cubrió 45 paquetes de ejecución y del extra YouTube fijados por el lockfile, sin vulnerabilidades conocidas informadas. Es una consulta de avisos publicados en esa fecha, no una prueba de ausencia de vulnerabilidades. Los informes JSON original y final quedan en el directorio de evidencias de la validación local.

La API conserva autenticación por cuenta, origen exacto, CSRF, cookies protegidas y separación de secretos. Los feeds conservan DNS público validado, límites XML y bloqueo de redirecciones. Las cuentas continúan administrándose desde terminal.

Referencias técnicas consultadas: [FileLock](https://py-filelock.readthedocs.io/en/latest/changelog.html), [SQLAlchemy 2.0](https://docs.sqlalchemy.org/en/20/core/engines.html), [python-dotenv](https://pypi.org/project/python-dotenv/).

## Ejecución reproducible

Desde el código fuente:

    uv sync --locked --extra youtube
    uv run --no-sync pytest -q -m "not internet and not performance"
    uv run --no-sync python scripts/validate-platform.py

El script de aceptación crea bases temporales y comprueba demo concurrente, configuración por archivo y entorno, lectura del historial tras terminar el proceso, servidor web, tema persistido, PDF breve y completo y cierre coordinado. Todas las capturas de esta aceptación son simuladas.

La suite incluye pruebas HTTPS con dos cuentas y un servidor gRPC local que reproduce reconexiones de chat. Las pruebas TUI usan Textual Pilot.

## Instalación Windows

### Personal administrativo

1. Extraer el ZIP completo, conservando _internal.
2. Copiar .env.example a .env junto al ejecutable.
3. Si se cambia la ubicación de datos, establecer ECHOSCOPE_DATA_DIR con una carpeta local, por ejemplo C:/EchoScopeRadar/datos.
4. Abrir Probar EchoScope Radar.cmd para práctica o Abrir EchoScope Radar.cmd para el perfil operativo.
5. Configurar palabras y fuentes desde la aplicación.

### Operación técnica

    uv run --no-sync echoscope-web --env-file C:/EchoScopeRadar/instalacion.env
    uv run --no-sync echoscope --env-file C:/EchoScopeRadar/instalacion.env demo --headless --seconds 5

Para el servidor compartido se usa SERVER_DIR, ORIGIN HTTPS, TLS_CERT, TLS_KEY y MASTER_KEY. La guía servidor.md explica la creación de usuarios. Windows debe asignar a la cuenta de servicio permisos sobre la carpeta de datos y lectura de certificados. El ejecutable empaquetado es una estación de doble clic; la provisión interactiva de contraseñas se realiza desde la instalación Python.

## Instalación Ubuntu 24.04

Instalar Python 3.12, python3-venv y uv. Desde el código:

    uv sync --locked --extra youtube
    uv run --no-sync echoscope demo --headless --seconds 5
    uv run --no-sync echoscope-web --demo --no-browser

La dirección predeterminada de práctica es http://127.0.0.1:8766. En un servidor sin navegador se puede usar la CLI headless o configurar el modo compartido HTTPS.

Para una instalación de servicio, ubicar el código en una carpeta de aplicación, los datos en /var/lib/echoscope y el archivo de entorno en /etc/echoscope/instalacion.env con permisos de la cuenta del servicio. El comando del servicio es:

    /ruta/proyecto/.venv/bin/echoscope-web --env-file /etc/echoscope/instalacion.env --no-browser

El archivo contiene SERVER_DIR, ORIGIN, BIND, PORT y rutas TLS para el modo compartido. En systemd se configuran User, WorkingDirectory y ExecStart para esa instalación. SIGTERM realiza el cierre coordinado. El servicio compartido se prepara con cuentas existentes y un certificado válido para su dirección.

Para el escritorio anterior tkinter se requiere python3-tk y un entorno gráfico. La interfaz web y headless funcionan sin ese paquete.

## Copias, actualización y recuperación

1. Detener el motor o servicio.
2. Copiar la carpeta de datos completa. En servidor, incluir accounts.sqlite y los directorios de cada cuenta.
3. Custodiar la clave maestra por separado y registrar la versión instalada.
4. Actualizar código o paquete, conservando configuración y datos.
5. Iniciar la nueva versión, que aplica las migraciones pendientes antes de ejecutar.
6. Verificar estado, fuentes e historial y realizar una captura de prueba.

Para restaurar, detener el motor y recuperar la copia consistente de datos y su clave maestra. Perder MASTER_KEY impide abrir el vault. Un backup del archivo SQLite mientras se escribe puede ser inconsistente; esta guía utiliza parada para simplificar la operación.

## Límites que permanecen

- SQLite es el adaptador de datos entregado. Otros motores requieren instalar un adaptador y migrar sus datos. Las migraciones SQLite no son migraciones universales.
- El catálogo de cuentas continúa en SQLite. Se mantiene un único proceso servidor por carpeta de cuentas.
- La validación de Ubuntu se realiza en un contenedor Ubuntu real sobre Docker Linux. No certifica un escritorio Ubuntu ni una instalación systemd de producción.
- Las API externas requieren credenciales, recursos y permisos efectivos. Esta auditoría no equivale a volver a aprobar el acceso de todas las plataformas.
- Las claves del vault persisten cifradas en servidor. Los tokens particulares de feeds siguen siendo de sesión y requieren cargarse después del reinicio.
- La auditoría registra el cambio de revisión y el estado, pero no conserva un historial completo por alerta con comentarios de analista.
- Los eventos operativos, ejecuciones y auditoría aún requieren una política específica de archivo a largo plazo. La retención de mensajes elimina sus observaciones y derivados relacionados.
- El cifrado de texto histórico en disco depende de las protecciones del sistema, por ejemplo BitLocker o cifrado de volumen. El vault cifra secretos.
- Los dos avisos de aiohttp sobre claves internas de request son recomendaciones de API y se registran en las salidas de prueba.
- La nueva configuración de CI queda lista para ejecuciones futuras. Los resultados locales indicados aquí proceden de esta revisión.

## Evidencias y resultado

| Entorno real | Resultado |
|---|---|
| Windows 11, Python 3.12.5 | 40 pruebas aprobadas, 2 pruebas optativas excluidas |
| Ubuntu 24.04 en Docker Linux/WSL2, Python 3.12.3 | 39 aprobadas, 1 omitida por requerir una ventana Windows, 2 optativas excluidas |
| Aceptación por CLI y HTTP, Windows | Captura concurrente, historial tras reinicio, archivo de entorno, tema y PDF, cierre por comando |
| Aceptación por CLI y HTTP, Ubuntu, red del contenedor deshabilitada | Mismos recorridos y cierre coordinado por SIGTERM |
| Ruff | Sin hallazgos y formato validado |
| Dependencias de ejecución y YouTube | 45 paquetes auditados, 0 vulnerabilidades conocidas informadas en la consulta final |

En ambas plataformas se instalaron las dependencias desde el mismo uv.lock. En Ubuntu, la imagen se construyó con la imagen oficial ubuntu:24.04. El contenedor de prueba se eliminó al terminar. No se modificaron bases operativas del usuario.

La comprobación del paquete Windows usa un .env externo y una carpeta temporal para confirmar que los puertos y la ubicación de datos se aplican sin cambiar el código. El paquete incluye el ejemplo de configuración y los documentos de esta revisión.

La consulta inicial y final de dependencias está documentada con las versiones fijadas. El informe JSON final se entrega junto a esta documentación. La prueba de carga de 10.000 mensajes y la prueba optativa de Internet no forman parte de esta ejecución.
