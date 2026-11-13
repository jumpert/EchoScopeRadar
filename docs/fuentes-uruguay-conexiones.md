# Guía de fuentes de Uruguay y formas de conexión

EchoScope Radar 0.12.0 · comprobaciones del 12 de noviembre de 2026

Actualización 0.13.0: también existe lectura de cuerpos y comentarios en HTML estático identificable. Consultá [el recorrido de prensa y sus límites](consulta-visual-y-prensa.md). Las verificaciones de la tabla siguiente corresponden a la fecha indicada.

## Cómo usar esta guía

En Fuentes, elegí Agregar fuente y copiá el enlace de la columna de conexión. Para noticias de prensa elegí Noticias de un sitio (RSS). La aplicación consulta comentarios de publicaciones cuyo título coincida con la lista blanca. Para recursos que administrás, elegí Cuenta propia para observar también publicaciones con otros títulos.

Los resultados siguientes corresponden a consultas directas realizadas desde el entorno de validación. Los conteos describen la ventana recibida. La comprobación de comentarios utilizó una noticia por medio y no establece la capacidad de todas sus notas.

## Ocho medios del perfil existente

| Medio y sitio oficial | Conexión RSS directa | Resultado | Comentarios de la nota de muestra | Credencial |
|---|---|---|---|---|
| [Telenoche](https://www.telenoche.com.uy/) | [Nacionales](https://www.telenoche.com.uy/rss/pages/nacionales.xml) | 20 noticias | La página rechazó el acceso del lector | RSS sin clave |
| [Subrayado](https://www.subrayado.com.uy/) | [Nacional](https://www.subrayado.com.uy/rss/pages/nacional.xml) | 20 noticias | La página rechazó el acceso del lector | RSS sin clave |
| [Montevideo Portal](https://www.montevideo.com.uy/) | [Noticias](https://www.montevideo.com.uy/anxml.aspx?59) | 8 noticias | La lectura no devolvió una página compatible | RSS sin clave |
| [El Observador](https://www.elobservador.com.uy/) | [Nacional](https://www.elobservador.com.uy/rss/pages/nacional.xml) | 20 noticias | La página rechazó el acceso del lector | RSS sin clave |
| [la diaria](https://ladiaria.com.uy/) | [Artículos](https://ladiaria.com.uy/feeds/articulos/) | 50 noticias | No se detectó un mecanismo compatible en la muestra | RSS sin clave |
| [Brecha](https://brecha.com.uy/) | [Noticias](https://brecha.com.uy/feed/) | 50 noticias | Se identificó WordPress REST; la consulta pública devolvió cero comentarios | RSS/WordPress público sin clave |
| [Caras y Caretas](https://www.carasycaretas.com.uy/) | [Portada](https://www.carasycaretas.com.uy/rss/pages/home.xml) | 20 noticias | La página rechazó el acceso del lector | RSS sin clave |
| [Teledoce](https://www.teledoce.com/) | [Feed](https://www.teledoce.com/feed/) | 10 noticias | La página rechazó el acceso del lector | RSS sin clave |

Todos estos feeds entregaron noticias. Leer un feed de noticias no confirma que se hayan leído los comentarios de sus lectores.

Brecha anuncia además un [feed general de comentarios](https://brecha.com.uy/comments/feed/). Ese feed puede contener distintas notas. EchoScope prioriza el mecanismo por publicación cuando se detecta y filtra enlaces para asociar cada comentario con su nota.

La API WordPress identificada es [comentarios](https://brecha.com.uy/wp-json/wp/v2/comments). La consulta de la nota de muestra utiliza su ID de publicación. [Nota comprobada](https://brecha.com.uy/una-loteria/)

## Fuentes adicionales e institucionales

| Fuente | Acceso encontrado | Resultado y uso |
|---|---|---|
| [Ejército del Uruguay](https://www.ejercito.mil.uy/) | [RSS de noticias](https://www.ejercito.mil.uy/index.php/feed/) y [feed general de comentarios](https://www.ejercito.mil.uy/index.php/comments/feed/) anunciados en la página | RSS de noticias verificado con 10 entradas. El feed general de comentarios está anunciado; su contenido requiere comprobación específica antes de asumir cobertura |
| [Ministerio de Defensa Nacional](https://www.gub.uy/ministerio-defensa-nacional/) | Sitio institucional público | La portada consultada no anunció un RSS compatible dentro de la ventana HTML inspeccionada. Registrar un enlace de publicación o solicitar al sitio su feed |
| [M24](https://www.m24.com.uy/) | Sitio público | No se identificó un feed anunciado en la portada inspeccionada |
| [El País Uruguay](https://www.elpais.com.uy/) | Sitio público | No se identificó un feed anunciado en la portada inspeccionada. Los RSS de elpais.com corresponden al periódico español |
| [Medios Públicos](https://mediospublicos.uy/) | [Feed de podcast anunciado](https://mediospublicos.uy/feed/podcast) | El lector no logró validar ese feed como fuente compatible. Queda pendiente una conexión de noticias o comentarios comprobada |

Este catálogo es ampliable. La detección inspecciona una ventana acotada de HTML; un mecanismo que no se detecta puede requerir otra integración o acceso facilitado por el sitio.

## YouTube

| Canal o recurso | Conexión y requisito | Situación |
|---|---|---|
| [Ejército del Uruguay](https://www.youtube.com/channel/UCeeEsGE06kae6DF-yOGT9Tw) | Canal de YouTube automático, clave de YouTube Data API o token OAuth autorizado | Canal incluido en el perfil |
| [VTV Noticias](https://www.youtube.com/channel/UCdW5hWEhQqexGEApXjBqQrQ) | Canal automático, misma clase de credencial | Canal incluido en el perfil |
| [Video del Ejército utilizado en la prueba](https://www.youtube.com/watch?v=emaHe4GM4G0) | Comentarios de un video de YouTube | Prueba real con la clave local autorizada: 36 comentarios, 9 coincidencias con Ejército o Defensa, todos con título del video |
| Directos de los canales seleccionados | Chat accesible mediante la API oficial | Recuperación y mensajes probados con servidor gRPC local. No se confirmó un directo real elegible durante esta validación |

Para un canal propio, copiá el enlace del canal o su @nombre. Elegí la modalidad Cuenta propia. La clave del proyecto habilita la consulta pública disponible; la declaración de propiedad la realiza el operador y debe corresponder a un canal que administra.

Obtené una clave del proyecto con YouTube Data API habilitada y cargala desde Claves API. Para consultas que requieren una cuenta autorizada, el conector admite referencias OAuth en YAML. La adquisición y renovación automática de OAuth queda pendiente.

Los comentarios principales y respuestas utilizan endpoints separados. La lectura tiene presupuestos por ciclo y comunica captura parcial cuando queda paginación sin recorrer. [Hilos de comentarios](https://developers.google.com/youtube/data/reference/rest/v3/commentThreads/list) · [Respuestas](https://developers.google.com/youtube/data/reference/rest/v3/comments/list)

## Sistemas de comentarios de páginas

| Sistema | Qué proporcionar | Soporte de esta versión |
|---|---|---|
| RSS/Atom de comentarios | URL pública anunciada o proporcionada por el sitio | Integrado |
| WordPress REST | Página que anuncie API y permita identificar la publicación | Integrado para comentarios públicos aprobados, con respuestas y paginación |
| Disqus | Página con foro identificable y clave de proyecto propia en Claves API | Integrado; contrato probado con fixtures. Prueba externa pendiente de clave Disqus |
| Otro sistema incrustado o HTML propio | Documentación del acceso y autorización del sitio | Requiere validar e implementar el lector específico |

La clave de un RSS protegido se envía únicamente al feed configurado. La detección de comentarios no la reenvía a otros servicios. [WordPress Comments](https://developer.wordpress.org/rest-api/reference/comments/) · [Disqus listPosts](https://disqus.com/api/docs/threads/listPosts/)

## Redes sociales y mensajería

Podés registrar estos recursos en Fuentes mediante su plataforma de acceso pendiente, URL e identificador opcional. Permanecen desactivados hasta incorporar y validar el conector correspondiente. Guardar una clave de estos servicios no activa la captura por sí solo.

| Plataforma | Información que debe preparar el responsable | Acceso a comentarios y estado |
|---|---|---|
| Facebook | Página propia, ID, aplicación Meta y permisos de lectura aprobados | Validar comentarios de páginas y acceso al recurso. Integración pendiente con credenciales propias |
| Instagram | Cuenta profesional propia, ID, aplicación y autorización | Validar comentarios y eventos de directos autorizados. Integración pendiente |
| Threads | Perfil propio, aplicación y token con permisos de respuestas | API de replies; integración y validación pendientes |
| X | Proyecto, token y acceso al endpoint/plan correspondiente | Las respuestas se recuperan como publicaciones de la conversación; integración pendiente |
| TikTok | Cuenta, caso de uso y producto API aprobado | Research API documenta comentarios para solicitantes elegibles. Elegibilidad y conector pendientes |
| Reddit | Comunidad/recurso, aplicación y aprobación para Data API externa | El acceso externo y comercial tiene aprobación propia. Conector pendiente |
| Telegram | Canal y, si existen, grupo de discusión asociado; bot autorizado y token | Las publicaciones del canal y comentarios del grupo son recursos diferentes. El bot necesita acceso efectivo a los mensajes pertinentes; integración pendiente |
| Canales de WhatsApp | Identificador del canal y documentación de un acceso autorizado que realmente exponga su contenido | No se validó un mecanismo de lectura de canales para esta aplicación. WhatsApp Business Cloud API no se asume como lector de cualquier canal |
| Bluesky | URL del hilo público | Lectura de respuestas públicas ya integrada; cobertura limitada por la ventana recibida |

Referencias oficiales para tramitar accesos:

- [Meta Pages](https://developers.facebook.com/docs/pages-api/)
- [Instagram Platform](https://developers.facebook.com/docs/instagram-platform/)
- [Threads, colección oficial de Meta](https://www.postman.com/meta/threads/overview)
- [X Search](https://docs.x.com/x-api/posts/search/introduction)
- [TikTok Research](https://developers.tiktok.com/products/research-api/)
- [Reddit para integraciones externas](https://developers.reddit.com/docs/guides/faq)
- [Telegram Bots FAQ](https://core.telegram.org/bots/faq)
- [WhatsApp Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api/)

## Qué cuenta como conexión comprobada

Una conexión comprobada debe devolver datos o una respuesta válida de ausencia de comentarios del mecanismo correspondiente. Un RSS de noticias disponible, una página visible o una clave guardada no bastan para afirmar lectura de comentarios. Los resultados de esta guía deben revalidarse cuando cambien los sitios o los permisos.
