# Auditoría inicial de EchoScope Radar

Fecha de revisión: 12 de noviembre de 2026. Base revisada: v0.10.0, commit f2309f2.

## Funcionamiento revisado

El producto es un monolito modular Python con dominio de mensajes y reglas, motor asíncrono, conectores registrados, persistencia SQLite, CLI, TUI, interfaz web y escritorio anterior. Los canales automáticos de YouTube descubren videos relacionados y consultan comentarios. Los feeds y páginas aportan solo los mensajes accesibles mediante los mecanismos integrados. Las claves de proveedores futuros se almacenan sin activar conectores.

El historial relaciona originales, versiones de texto, observaciones por tarea y reglas. Los checkpoints y alertas se confirman en la misma transacción. Los chats de YouTube viven en una ventana de sesión. El reporte breve prioriza grupos de publicaciones y conserva una alternativa completa.

## Hallazgos y trabajo priorizado

| Prioridad | Hallazgo | Consecuencia | Acción |
|---|---|---|---|
| Alta | Administración y CLI instancian directamente el almacén SQLite | Cambiar de adaptador exige modificar consumidores | Introducir fábrica de persistencia, contratos e inyección |
| Alta | El análisis posterior de dependencias detecta avisos publicados en FileLock 3.32.7 | La instalación conserva una versión con correcciones de seguridad disponibles | Actualizar a 4.2.10 y repetir la validación |
| Alta | IP, directorios y límites repartidos entre puntos de entrada | Operación inconsistente entre instalaciones | Cargar configuración tipada desde entorno y archivo explícito |
| Alta | El servidor aiohttp puede registrar excepciones con datos de solicitudes y errores SQL de bajo nivel | Posible exposición en diagnósticos | Ocultar parámetros SQL y emitir respuestas operativas sin secretos |
| Media | Revisión de alertas acepta identificadores sin comprobar pertenencia | Se pueden registrar decisiones sin una alerta existente en la cuenta | Comprobar el alcance y auditar cambios |
| Media | Revisiones locales persisten después de purgar mensajes | Retención incompleta de derivados | Limpiar revisiones huérfanas |
| Media | Varias APIs oficiales cargan JSON completo sin límite explícito | Una respuesta excesiva puede consumir memoria | Aplicar lectura limitada compartida |
| Media | Límites de autenticación y concurrencia fijos | Dificultad para ajustar capacidad | Parametrizar con límites validados |
| Media | Apagado web sin manejo propio de SIGTERM | Servicio Ubuntu puede interrumpir ciclos en ejecución | Instalar cierre coordinado |
| Media | No hay CI multiplataforma en el repositorio | La portabilidad depende de verificación manual | Añadir validación Windows y Ubuntu |
| Baja | Fuentes, tareas y conjuntos de reglas residen en JSON | El MER lógico difiere del esquema físico | Documentar ambas representaciones |

## Controles existentes

- Contraseñas con scrypt y sal aleatoria, sesiones con expiración, cookie Secure/HttpOnly/SameSite y verificación de origen.
- Cuentas con bases y claves separadas, secretos cifrados en modo servidor, comparación de tokens en tiempo constante.
- Consultas SQL parametrizadas, bloqueo de escritor por base y transacciones de captura.
- Feeds HTTPS con resolución pública verificada, redirecciones desactivadas y XML protegido frente a entidades externas.
- Texto del navegador construido mediante nodos de texto, enlaces validados y cabeceras de seguridad.
- Pausas, deduplicación, reglas Unicode y aislamiento de fallos de fuentes.

## Límites de la revisión

La auditoría incluye inspección del código, contratos y pruebas reproducibles locales. Los permisos externos dependen del proveedor y credenciales. La verificación de despliegue, hallazgos corregidos y límites finales se registra en el informe de validación de esta versión.
