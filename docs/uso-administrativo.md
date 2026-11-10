# Guía de uso administrativo

## Empezar

1. En Windows, extraé toda la carpeta de la aplicación y abrí **EchoScopeRadar.exe**. Se abre en tu navegador. Conservá la carpeta `_internal` junto al ejecutable. También podés abrir **Abrir EchoScope Radar.cmd**.
2. Revisá **Tema y acceso**. El tema inicial incluye Ministerio de Defensa, Ejército Nacional, Fuerzas Armadas y otras expresiones relacionadas. Podés escribir una frase por línea y guardar.
3. El seguimiento arranca al abrir la mesa. Puede seguir con el navegador minimizado. **Fuentes** muestra qué medios están programados, consultando o requieren revisión. Usá **Cerrar EchoScope** al pie para finalizar el seguimiento y liberar la base. Si cerrás la pestaña, la sesión se detiene tras unos minutos sin actividad.
4. En **Mesa de monitoreo**, elegí los flujos que querés ver juntos. Seleccioná una fila para leer el texto completo y ver los términos resaltados. El detalle permite abrir la publicación original cuando la fuente entrega su enlace.
5. Usá el botón de sol o luna para cambiar de tema. EchoScope recuerda tu elección en este perfil.

Para practicar, abrí **Probar EchoScope Radar.cmd**. Usa una base separada y arranca con chat, comentarios y reseñas simulados. En los primeros ciclos aparecen `soldad0`, `d e f e n s a` y `ejersito`.

## Organizar la mesa

- Usá los botones de flujo sobre la mesa para mostrar u ocultar **Chat en vivo**, **Comentarios de prensa**, **Reseñas**, **Noticias**, **Videos de YouTube**, **Foros** y **Redes sociales**.
- En cada cabecera, usá **Maximizar** para dar todo el ancho a ese flujo y **Restaurar vista** para volver a la distribución anterior. El control **Ocultar** retira el panel de la mesa.
- Arrastrá el control de puntos de un panel sobre otro para cambiar su posición. El menú **↔** permite moverlo y ajustar su ancho sin arrastrar. Usá **Paneles por fila** para cambiar la cantidad de columnas y **↺** para recuperar la distribución inicial. El navegador recuerda tus ajustes.
- Elegí **Proyección** o presioná **P** fuera de los campos de texto. Se ocultan los controles generales para dar más espacio a paneles y alertas. Si el navegador mantiene visibles sus barras, usá **F11**. Volvé con **Esc** o **Salir de proyección**.
- Podés ocultar la bandeja de alertas. En ella, **Para revisar** muestra las coincidencias aproximadas por separado.
- **Congelar vista** deja los resultados quietos mientras el motor sigue en su estado actual. **Pausar seguimiento** detiene las consultas. El campo de búsqueda y el selector de coincidencias filtran los resultados. **Cargar más historial** amplía la ventana de lectura hasta 200 resultados por panel.

## Búsqueda automática

El perfil inicial consulta Telenoche, Subrayado, Montevideo Portal, El Observador, la diaria, Brecha, Caras y Caretas y Teledoce. Para las notas pertinentes busca feeds de comentarios anunciados por el propio medio. La disponibilidad de comentarios y reseñas depende del acceso que publique cada sitio.

Cuando cargás la clave de YouTube, el perfil consulta los canales de **Ejército del Uruguay** y **VTV Noticias**. Revisa videos recientes y busca directos activos relacionados con el tema. Las consultas se programan según la fuente. Los videos se revisan cada 30 minutos y los directos cada 60 minutos en el perfil inicial. Podés ajustar los intervalos en **Fuentes**.

### Buscar por tema

En la mesa elegí **Buscar por tema**, escribí palabras como `Ejército Uruguay` y presioná **Buscar**. Se consulta el historial local y la ventana actual de hasta 18 feeds habilitados. Con la clave de YouTube también se buscan videos y directos por tema. Para ampliar la búsqueda a sitios públicos indexados, cargá una clave de Brave Search en **Tema y acceso**. YouTube y Brave reciben el tema para ejecutar la consulta y pueden aplicar cuotas. También podés proporcionar las claves mediante `ECHOSCOPE_YOUTUBE_KEY` y `ECHOSCOPE_BRAVE_KEY` antes del arranque.

EchoScope consulta automáticamente la conversación de hasta dos resultados compatibles por grupo. Abrí **Comentarios y reseñas** o **Chat en vivo** en cualquier otro resultado para consultarlo. Podés seguir el video, directo, hilo de Bluesky o feed desde la misma tarjeta para incorporar mensajes nuevos a la mesa. Los enlaces llevan a la publicación o al comentario que entrega la fuente.

Brave Search agrega resultados regionales y publicaciones públicas indexadas en redes. En Bluesky se pueden leer las respuestas públicas de un hilo. Para Facebook, Instagram, X, TikTok y Reddit se ofrece el enlace de las publicaciones indexadas. Para leer en EchoScope, el proveedor debe entregar mensajes mediante una API integrada o un RSS/Atom accesible. Un contador refleja la ventana recibida, y la mesa indica cuando la cobertura es parcial.

## Descargar un reporte de alertas

En la mesa elegí **Descargar PDF**, seleccioná las fechas de captura en UTC y presioná **Generar PDF**. Incluye coincidencias confirmadas del historial retenido y de las vistas previas aún disponibles en la sesión. El resumen muestra registros, conversaciones y alertas críticas por sitio. El detalle incluye fecha, tipo, término y enlaces. Los sitios y feeds incluyen un extracto y tono estimado cuando están disponibles. YouTube aparece como un listado de alertas locales con su enlace original.

## Agregar contenido

| Quiero seguir | Qué ingresar |
|---|---|
| Noticias de un medio | Nombre para reconocerlo y enlace HTTPS al RSS oficial del medio. Elegí cada cuántos minutos consultarlo. |
| Comentarios de una nota | Pegá el enlace de la nota y elegí **Detectar feed**. Si el sitio anuncia un feed de comentarios, el formulario completa el enlace. Si ya tenés un feed autorizado, pegalo directamente. |
| Reseñas de un sitio | Elegí **Reseñas de un sitio (RSS/Atom)** y pegá el enlace al feed autorizado que las publica. |
| Un video de YouTube | Pegá el enlace del video y seleccioná **Comentarios de un video de YouTube**. Usá **Tema y acceso → Cargar clave** para ingresar la clave de YouTube Data API que te haya entregado el responsable de la cuenta. |
| Buscar videos por tema | Con la clave cargada, escribí el tema y elegí **Buscar videos**. Seleccioná uno de los resultados y elegí **Seguir comentarios del video**. |
| Un chat de YouTube en directo | Pegá el enlace en **Chat de un directo de YouTube**. El chat debe estar activo y habilitado. El panel lo identifica como **solo sesión**. |
| Un canal de YouTube | Elegí **Canal de YouTube · videos automáticos** o **directos automáticos**. Pegá el enlace del canal o su `@nombre`. |
| Un foro o comunidad | Elegí **Foro o comunidad (RSS/Atom)** y pegá el enlace autorizado. Desde entonces se consulta automáticamente. |
| Un hilo público de Bluesky | Elegí **Respuestas de una publicación de Bluesky** y pegá el enlace al post. Las respuestas aparecen en **Redes sociales**. |

Si el medio te entrega un token Bearer para un feed protegido, ingresalo en el campo **Token del feed**. Cargá las claves y los tokens en los campos de la aplicación. Sus valores se usan durante esa sesión.

## Interpretar los resultados

- **Notas** son publicaciones del medio. **Comentarios** y **Chats en vivo** identifican mensajes de lectores y espectadores.
- En la mesa, cada resultado muestra unas líneas del cuerpo. Si hay coincidencias, se prioriza su contexto. En el detalle se ven hasta tres fragmentos alrededor de las coincidencias. Usá el enlace de origen para abrir el contenido completo cuando esté disponible.
- Los puntos **ⓘ** explican cada pestaña. En **Fuentes** y **Tema y acceso**, desplegá **Ayuda paso a paso** si necesitás instrucciones. En **Tema y acceso**, **Verificar acceso** comprueba que YouTube acepte la clave elegida en **Claves API**.
- En **Videos de YouTube**, cada título agrupa los comentarios del video con su hora, autor y extracto. Si la API no entrega el título, el grupo conserva el identificador y el enlace.
- En **Alertas**, combiná **Estado** y **Tono**. Marcá una o varias filas o usá **Seleccionar visibles** para marcarlas juntas. Elegí **Verificadas**, **Amenazas**, **Descartadas** o **Sin verificar** y presioná **Aplicar**. **Cargar más** amplía el conjunto visible hasta 500 alertas por operación.
- El término que disparó la alerta se resalta en el mensaje y en la bandeja. El símbolo junto al mensaje indica el tono estimado en español: **＋** positivo, **−** negativo, **±** mixto y **·** neutro. Es una estimación por vocabulario, con precisión limitada en ironía y lenguaje ambiguo. El tono y la severidad se muestran por separado.
- Las fuentes con filtro temático guardan solo coincidencias. En un video que ya elegiste por el tema, podés dejar ese filtro desactivado para ver todos los comentarios de la ventana consultada.
- **Cobertura parcial** indica que la fuente entregó una ventana limitada, faltaron respuestas o hubo un hueco durante la captura. La búsqueda muestra la ventana disponible y el historial local.
- **Comentarios no disponibles** indica que el video no permite acceder a comentarios por la API, o que el recurso solicitado ya no está disponible. **Sin permiso** indica que la fuente rechazó el acceso.
- **Pausar seguimiento** pausa las consultas y conserva los resultados persistidos. Quitar una fuente también conserva su historial. Los comentarios de video agregados desde la mesa tienen una retención de hasta siete días. El chat en vivo de YouTube se conserva en memoria durante la sesión del motor.

## Variantes en la lista blanca

EchoScope puede reconocer variantes como `soldad0` y `d e f e n s a`, y conserva el texto tal como apareció. Las coincidencias aproximadas, como `ejersito`, quedan en el filtro **Para revisar**. Para aprobar una forma conocida, agregala junto al término principal en **Tema y acceso**, por ejemplo `Ejército | ejersito`. La regla se aplica a las capturas siguientes.

El perfil inicial y la comprobación de cada medio se explican en [Fuentes uruguayas](fuentes-uruguay.md).
