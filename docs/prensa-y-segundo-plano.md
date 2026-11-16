# Prensa y seguimiento en segundo plano · 0.14.2

Comprobación del 13 de noviembre de 2026. Se consultaron individualmente 16 medios, sin iniciar sesión ni utilizar claves privadas. El informe reproducible está en [auditoria-prensa-2026-11-13.json](auditoria-prensa-2026-11-13.json). Se inspeccionaron hasta dos noticias recientes por medio; estos resultados no prueban todas las publicaciones ni todos sus comentarios.

| Medio | Publicaciones comprobadas | Comentarios de lectores y situación |
|---|---|---|
| [Canal 4 / Telenoche](https://www.telenoche.com.uy/) | RSS Nacionales y cuerpo HTML | Sin mecanismo de comentarios compatible en las dos muestras. No se afirma ausencia de comentarios en todo el sitio. |
| [Subrayado](https://www.subrayado.com.uy/) | RSS Nacional y cuerpo HTML | Disqus identificado. El lector está implementado; falta una clave Disqus propia para comprobar la consulta externa. |
| [Tele12 / Telemundo](https://www.teledoce.com/) | RSS, 10 publicaciones recibidas | Las dos páginas de muestra devolvieron acceso denegado. Comentarios sin verificar. |
| [Montevideo Portal](https://www.montevideo.com.uy/) | RSS Noticias y cuerpo HTML | Lector específico del servicio público de comentarios de la página. Se recibieron 10 comentarios de cada una de dos noticias, con más páginas disponibles. Implementada la continuación por ciclos. |
| [El Observador](https://www.elobservador.com.uy/) | RSS Nacional y cuerpo HTML | Sin comentarios HTML identificables ni API compatible en las muestras. |
| [la diaria](https://ladiaria.com.uy/) | RSS Artículos y cuerpo HTML público | Sin mecanismo compatible de comentarios en las muestras. No se accede a contenido reservado a suscriptores. |
| [Brecha](https://brecha.com.uy/) | RSS y cuerpo HTML público | API WordPress por noticia verificada: respuesta válida con cero comentarios en ambas muestras. |
| [Caras y Caretas](https://www.carasycaretas.com.uy/) | RSS Portada y cuerpo HTML | Sin mecanismo compatible de comentarios en las muestras. |
| [El País Uruguay](https://www.elpais.com.uy/) | Portada HTML; cuerpo identificable en una muestra | Sistema Arena identificado, integración pendiente. La aplicación lo informa expresamente. |
| [Medios Públicos / Canal 5](https://mediospublicos.uy/) | Portada HTML | API WordPress por noticia verificada: cero comentarios en las muestras. El feed de podcast anunciado no se utiliza como si fuera prensa escrita. |
| [Radio Monte Carlo](https://www.radiomontecarlo.com.uy/) | Portada HTML | Sin mecanismo compatible en las muestras. |
| [CW33 Florida](https://www.cw33florida.com.uy/) | Portada con enlaces de noticias adaptados al sitio | RSS anunciado pero vacío durante la comprobación; se utiliza la portada. Comentarios según mecanismo público detectable por nota. |
| [970 Universal](https://970universal.com/) | Portada entregada como aplicación JavaScript | El lector estático no recibe artículos. Requiere una integración de datos específica; no se activa una fuente vacía como conectada. |
| [M24](https://www.m24.com.uy/) | La dirección consultada devolvió un índice de servidor | No se comprobó una conexión de noticias ni comentarios. |
| [La República](https://www.larepublica.com.uy/) | La consulta no pudo completarse | Sin conexión comprobada. No se asocia automáticamente a otro dominio. |
| [LaRed21](https://www.lr21.com.uy/) | Acceso denegado | Sin conexión comprobada. |

Los primeros 12 medios están incluidos en el perfil de la aplicación. Los cuatro restantes requieren resolver el acceso o desarrollar y verificar su integración; no se presentan como capturas activas. No se eluden bloqueos, suscripciones ni autenticación.

## Lista blanca y opiniones

La modalidad **Todas las publicaciones y sus comentarios** revisa también las noticias cuyo título no coincide con la lista blanca. Así puede detectar una palabra de interés introducida únicamente por un lector. Las capturas se guardan aunque no tengan coincidencias y las alertas conservan el resaltado del texto original, su autor público, enlace y noticia de origen.

La modalidad **Por tema** sigue disponible para reducir el seguimiento a títulos relacionados. **Cuenta propia** conserva su significado de recurso administrado por el operador; no es necesario declararse dueño de un medio para revisar todas sus noticias. La actualización conserva las reglas y tareas deshabilitadas existentes y amplía el perfil incorporado una sola vez.

El análisis de tono existente distingue positivo, negativo, mixto y neutral mediante palabras y negaciones. Es una ayuda de revisión: no determina de forma fiable apoyo u oposición a un tema, ni ironía o intención política. La clasificación debe contrastarse con el comentario completo y su contexto.

## Segundo plano y salida

Abrí **Abrir EchoScope Radar.cmd** o el ejecutable de `dist/0.14.2/EchoScopeRadar`. La interfaz se muestra solamente en el navegador, sin ventana de control adicional. Cerrar el navegador mantiene el motor activo.

Volvé a `http://127.0.0.1:8765/` (puerto predeterminado) para consultar los datos acumulados. El botón **Cerrar EchoScope** ofrece **Confirmar segundo plano** o **Salir y detener captura**. Solo la segunda opción detiene el motor. La computadora debe seguir encendida y sin suspensión.

[Capacidad, limpieza y ruta real de la base](almacenamiento-y-acceso.md).

## Archivos de registro

En la carpeta local de datos de EchoScopeRadar (configurable con `ECHOSCOPE_DATA_DIR`) se guardan:

- `administracion.sqlite`: capturas, noticias, comentarios, chats, coincidencias, revisiones y ejecuciones del modo real. La base puede tener archivos auxiliares `-wal` y `-shm` mientras está abierta.
- `logs/echoscope.log`: inicio, cierre, lotes confirmados, conteos, alertas y estado de cobertura. Rota a los 2 MiB y conserva cinco archivos anteriores. No copia el texto de los comentarios ni claves API al log de actividad.
- El modo de prueba utiliza `practica.sqlite` y `logs/practica.log` por separado.

Los chats de YouTube ahora se persisten y pueden consultarse tras reiniciar. El perfil incorpora retención de siete días para esos recursos; la prensa conserva su retención configurada, hasta 30 días. Las exportaciones de **Base de datos** permiten guardar CSV, Excel o PDF de una consulta. La retención evita tratar el archivo como un archivo histórico indefinido.

Las claves locales agregadas desde la interfaz siguen siendo de sesión. Para una operación que deba reconectarse después de reiniciar, configurá las referencias de credenciales en el entorno o el mecanismo de claves del servidor. YouTube requiere una clave válida y cuota; los foros y reseñas requieren un feed o recurso compatible, y sus fuentes deben habilitarse. No se obtienen automáticamente comentarios privados de suscriptores, redes cerradas o plataformas pendientes.

## Cobertura y verificación

La lectura es periódica y acotada por los recursos por ciclo, las ventanas de los feeds, la retención y la cuota de cada proveedor. Los RSS Nacional/Nacionales no representan todas las secciones del medio. Las portadas cambian con el tiempo y pueden retirar enlaces; no se promete una captura exhaustiva. El estado de captura parcial y los accesos pendientes se mantienen visibles.

Para repetir la comprobación de medios: `uv run python scripts/audit-uruguay.py docs/auditoria-prensa-2026-11-13.json`. No altera la configuración del usuario ni publica comentarios.

Se verificaron regresiones de coincidencias solo en comentarios, paginación, identidad de la noticia, migración del perfil, persistencia de chats al reabrir y continuidad del servidor sin navegador. La versión 0.14.2 elimina la ventana de control y verifica por pruebas la reapertura de una instancia sin crear otro motor.
