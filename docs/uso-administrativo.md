# Guía de uso administrativo

## Empezar

1. En Windows, abrí **EchoScopeRadar.exe** en la carpeta de la aplicación. Conservá la carpeta `_internal` junto al ejecutable. Si estás en la carpeta del proyecto, podés abrir **Abrir EchoScope Radar.cmd**.
2. Revisá **Tema y acceso**. El tema inicial incluye Ministerio de Defensa, Ejército Nacional, Fuerzas Armadas y otras expresiones relacionadas. Podés escribir una frase por línea y guardar.
3. En modo normal, el seguimiento arranca al abrir la ventana y sigue si la minimizás. **Fuentes** muestra qué medios están programados, consultando o requieren revisión. Cerrá la ventana para finalizar el seguimiento.
4. Abrí **Resultados** y elegí **Noticias**, **Comentarios de prensa**, **YouTube**, **Directos** o **Foros**. Seleccioná una fila para leer el texto y ver los términos resaltados. **Abrir publicación** lleva al sitio original.
5. Elegí **Claro** u **Oscuro** en la parte superior. EchoScope recuerda tu elección en este perfil.

Para practicar, abrí **Probar EchoScope Radar.cmd** y elegí **Iniciar seguimiento**. Usa una base separada. En los primeros ciclos aparecen `soldad0`, `d e f e n s a` y `ejersito` para probar alertas y revisión.

## Búsqueda automática

El perfil inicial consulta Telenoche, Subrayado, Montevideo Portal y El Observador. Para las notas pertinentes busca feeds de comentarios anunciados por el propio medio. La disponibilidad de los comentarios depende del acceso que publique cada sitio.

Cuando cargás la clave de YouTube, el perfil consulta los canales de **Ejército del Uruguay** y **VTV Noticias**. Revisa videos recientes y busca directos activos relacionados con el tema. Las consultas se programan según la fuente. Los videos se revisan cada 30 minutos y los directos cada 60 minutos en el perfil inicial. Podés ajustar los intervalos en **Fuentes**.

## Agregar contenido

| Quiero seguir | Qué ingresar |
|---|---|
| Noticias de un medio | Nombre para reconocerlo y enlace HTTPS al RSS oficial del medio. Elegí cada cuántos minutos consultarlo. |
| Comentarios de una nota | Pegá el enlace de la nota y elegí **Detectar feed**. Si el sitio anuncia un feed de comentarios, el formulario completa el enlace. Si ya tenés un feed autorizado, pegalo directamente. |
| Un video de YouTube | Pegá el enlace del video y seleccioná **Comentarios de un video de YouTube**. Usá **Tema y acceso → Cargar clave** para ingresar la clave de YouTube Data API que te haya entregado el responsable de la cuenta. |
| Buscar videos por tema | Con la clave cargada, escribí el tema y elegí **Buscar videos**. Seleccioná uno de los resultados y elegí **Seguir comentarios del video**. |
| Un chat de YouTube en directo | Pegá el enlace en **Chat de un directo de YouTube**. El chat debe estar activo y habilitado. El panel lo identifica como **solo sesión**. |
| Un canal de YouTube | Elegí **Canal de YouTube · videos automáticos** o **directos automáticos**. Pegá el enlace del canal o su `@nombre`. |
| Un foro o comunidad | Elegí **Foro o comunidad (RSS/Atom)** y pegá el enlace autorizado. Desde entonces se consulta automáticamente. |

Si el medio te entrega un token Bearer para un feed protegido, ingresalo en el campo **Token del feed**. Cargá las claves y los tokens en los campos de la aplicación. Sus valores se usan durante esa sesión.

## Interpretar los resultados

- **Notas** son publicaciones del medio. **Comentarios** y **Chats en vivo** identifican mensajes de lectores y espectadores.
- Las fuentes con filtro temático guardan solo coincidencias. En un video que ya elegiste por el tema, podés dejar ese filtro desactivado para ver todos los comentarios de la ventana consultada.
- **Cobertura parcial** indica que la fuente entregó una ventana limitada, faltaron respuestas o hubo un hueco durante la captura. La búsqueda muestra la ventana disponible y el historial local.
- **Comentarios no disponibles** indica que el video no permite acceder a comentarios por la API, o que el recurso solicitado ya no está disponible. **Sin permiso** indica que la fuente rechazó el acceso.
- **Detener seguimiento** pausa las consultas y conserva los resultados persistidos. Quitar una fuente también conserva su historial. Los comentarios de video agregados desde la ventana tienen una retención de hasta siete días. El chat en vivo de YouTube se conserva en memoria durante la sesión del motor.

## Variantes en la lista blanca

EchoScope puede reconocer variantes como `soldad0` y `d e f e n s a`, y conserva el texto tal como apareció. Las coincidencias aproximadas, como `ejersito`, quedan en el filtro **Para revisar**. Para aprobar una forma conocida, agregala junto al término principal en **Tema y acceso**, por ejemplo `Ejército | ejersito`. La regla se aplica a las capturas siguientes.

El perfil inicial y la comprobación de cada medio se explican en [Fuentes uruguayas](fuentes-uruguay.md).
