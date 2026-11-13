# Historial de versiones

## 0.12.0

- Fuentes por título relacionado y cuentas declaradas propias con seguimiento independiente del título.
- Captura de comentarios públicos de WordPress y Disqus, con respuestas, paginación y relación con la nota original.
- Ventanas configurables de descubrimiento y seguimiento, estados de cobertura y uso de claves Disqus en el almacén de cuenta.
- Recuperación del seguimiento activo por cuenta al reiniciar el servidor, antes de iniciar sesión.
- Registro de recursos sociales con acceso pendiente, guía verificada de Uruguay y consultas directas de SQLite.
- Plantilla systemd, instrucciones de arranque Windows y diagnóstico de ubicación de base sin secretos.

## 0.11.0

- Auditoría funcional y de seguridad, documentación de usuario, documento técnico con MER e informe de pruebas por sistema operativo.
- Configuración de despliegue tipada desde .env, variables del proceso y argumentos de CLI.
- Fábrica de persistencia con URL SQLAlchemy, registro de adaptadores e inyección de almacén y conectores.
- Validación de pertenencia de alertas, auditoría de revisiones, limpieza de decisiones huérfanas, lectura JSON limitada y errores HTTP sin datos internos.
- Cierre por SIGTERM de la estación web, salida UTF-8 de CLI y CI Windows/Ubuntu.
- Actualización de FileLock a una versión corregida y comprobación de dependencias.

## 0.10.0

- Los PDF incluyen barras con cifras y etiquetas legibles en escala de grises. El detalle completo agrega un cuadro por tipo de contenido.
- Fuentes organizadas por categorías, con grupos personalizados y orden manual guardado por cuenta.

## 0.9.0

- Chat en vivo agrupado por transmisión, con título y enlace original cuando están disponibles. Cada panel distingue fuentes habilitadas de recursos visibles.
- Reporte A4 para imprimir con publicaciones prioritarias, fragmentos breves y un resumen de revisión. El formato de detalle completo sigue disponible.
- Selector de apariencia con cuatro temas: Claro, Claro medio, Oscuro y Muy oscuro.

## 0.8.0

- Guía interactiva de reseñas que abre el formulario preparado para buscar una lista pública desde el enlace de una página.
- Catálogo de claves para redes sociales e inteligencia artificial, con proveedores personalizados. Los proveedores sin integración solo almacenan credenciales.
- PDF agrupado por publicación original, con enlaces y estado de revisión. Incluye resumen local de pendientes, verificadas, descartadas y marcadas como amenaza. YouTube se muestra como referencias agrupadas, fuera de las métricas.

## 0.7.0

- Comentarios de YouTube agrupados por video, con título, hora y autor.
- Filtros de alertas por revisión y tono. Selección individual y masiva de las alertas visibles, con estados para verificación, amenaza y descarte.
- Modo servidor HTTPS con cuentas y almacenamiento cifrado de claves por usuario. Pestaña Claves API para nombrar y elegir credenciales.
- Búsqueda en Brave, Tavily, Google mediante Serper y SearXNG configurable. Ayudas desplegables en las pantallas de configuración.

## 0.6.2

- Vistas previas breves en todas las pestañas de la mesa, incluso en resultados sin coincidencias.
- Ayudas ⓘ por panel y mensajes que explican por qué una fuente todavía no entrega datos.
- Verificación de la clave de YouTube, consultas manuales desde Fuentes y detección de feeds de reseñas.

## 0.6.1

- Titulares separados del contenido y hasta tres fragmentos alrededor de las coincidencias. La mesa, la búsqueda y las conversaciones conservan el enlace al original.
- Escudo de la Unidad de Ciberdefensa del Ejército y paleta verde, dorada y azul en la interfaz web.

## 0.6.0

- Enlaces al origen en los flujos, las alertas, la búsqueda y el reporte. Los comentarios de YouTube capturados en esta versión enlazan a su comentario cuando el proveedor lo permite.
- Conversaciones junto a los resultados de búsqueda. Lee feeds de comentarios y reseñas anunciados por medios, comentarios y chats de YouTube y respuestas públicas de Bluesky. Distingue ventanas parciales y fuentes sin acceso.
- Perfil de Uruguay ampliado con la diaria, Brecha, Caras y Caretas y Teledoce. Brave Search agrega descubrimiento regional e indexación de publicaciones públicas en redes.
- Exportación de alertas confirmadas por fechas a PDF, con enlaces, detalle por registro y métricas por sitio. El detalle de YouTube figura por separado de las métricas.

## 0.5.0

- Modo proyección con pantalla completa cuando el navegador lo admite. Conserva los flujos y la bandeja de alertas.
- Paneles reordenables por arrastre o menú, con ancho y columnas ajustables y distribución guardada por navegador.
- Búsqueda temática en historial, RSS/Atom habilitados, YouTube y, con clave opcional, web abierta mediante Brave Search. Los resultados permiten iniciar el seguimiento de comentarios o chats disponibles.
- Resaltado de alertas de mayor contraste e indicador de tono estimado en español.

## 0.4.0

- Mesa web local de monitoreo como interfaz administrativa predeterminada en Windows. Reutiliza el motor, los perfiles, las preferencias y el historial de SQLite.
- Seis tipos de flujo combinables, paneles con desplazamiento propio, controles para ocultar y maximizar, y bandeja de alertas debajo de la mesa.
- Tema claro u oscuro, filtros, detalle con resaltado exacto y pausa visual independiente del seguimiento.
- Formularios web para fuentes, lista blanca, acceso a YouTube y descubrimiento manual. El modo de práctica arranca con chat, comentarios y reseñas simulados.

## 0.3.0

- Pestañas en la ventana principal para Noticias, Comentarios de prensa, YouTube, Directos y Foros. Tema claro u oscuro guardado por perfil local.
- Seguimiento automático al abrir el escritorio. Continúa minimizado y termina al cerrar la ventana.
- Perfil inicial con prensa uruguaya y canales seleccionados de Ejército del Uruguay y VTV Noticias. Descubre videos, directos y feeds públicos de comentarios anunciados por notas pertinentes.
- Formulario para incorporar RSS/Atom autorizados de foros, canales, notas, videos y directos.
- Detección de sustituciones, separación de letras y alias aprobados. Las variantes aproximadas quedan disponibles en Para revisar y no generan alertas automáticas.
- Migración SQLite que conserva el historial existente y diferencia coincidencias confirmadas y aproximadas.

## 0.2.0 · 2026-11-09

- Ventana de escritorio para operar sin terminal, con una base separada para practicar.
- Formularios para agregar medios, videos y directos. Acceso a YouTube y tokens RSS durante la sesión.
- Perfil inicial de prensa uruguaya sobre Defensa Nacional y el Ejército, con cuatro fuentes activas al iniciar el seguimiento.
- Descubrimiento de feeds de comentarios anunciados en páginas públicas y captura de comentarios y respuestas de videos mediante YouTube Data API.
- Distinción entre noticias, comentarios y chat. Filtros, coincidencias resaltadas y acceso a la publicación original.
- Empaquetado local de Windows y pruebas de la interfaz, los conectores y la recuperación del motor.

## 0.1.0

- Primer motor headless y TUI con tres fuentes simuladas, SQLite, alertas, historial y replay.
- RSS/Atom público y protegido, chat de YouTube Live opcional y comandos operativos.
