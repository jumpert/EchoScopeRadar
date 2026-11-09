# Guía de uso administrativo

## Empezar

1. En Windows, abrí **EchoScopeRadar.exe** en la carpeta de la aplicación. Conservá la carpeta `_internal` junto al ejecutable. Si estás en la carpeta del proyecto, podés abrir **Abrir EchoScope Radar.cmd**.
2. Revisá **Tema y acceso**. El tema inicial incluye Ministerio de Defensa, Ejército Nacional, Fuerzas Armadas y otras expresiones relacionadas. Podés escribir una frase por línea y guardar.
3. Elegí **Iniciar seguimiento**. La pestaña **Fuentes** muestra qué medios están programados, consultando o requieren revisión.
4. Abrí **Resultados**. Seleccioná una fila para leer el texto completo. Los términos encontrados aparecen resaltados. **Abrir publicación** lleva al sitio original.

Para practicar, abrí **Probar EchoScope Radar.cmd**. Usa datos simulados en una base separada. Ese acceso también viene junto al ejecutable distribuible.

## Agregar contenido

| Quiero seguir | Qué ingresar |
|---|---|
| Noticias de un medio | Nombre para reconocerlo y enlace HTTPS al RSS oficial del medio. Elegí cada cuántos minutos consultarlo. |
| Comentarios de una nota | Pegá el enlace de la nota y elegí **Detectar feed**. Si el sitio anuncia un feed de comentarios, el formulario completa el enlace. Si ya tenés un feed autorizado, pegalo directamente. |
| Un video de YouTube | Pegá el enlace del video y seleccioná **Comentarios de un video de YouTube**. Usá **Tema y acceso → Cargar clave** para ingresar la clave de YouTube Data API que te haya entregado el responsable de la cuenta. |
| Buscar videos por tema | Con la clave cargada, escribí el tema y elegí **Buscar videos**. Seleccioná uno de los resultados y elegí **Seguir comentarios del video**. |
| Un chat de YouTube en directo | Pegá el enlace en **Chat de un directo de YouTube**. El chat debe estar activo y habilitado. El panel lo identifica como **solo sesión**. |

Si el medio te entrega un token Bearer para un feed protegido, ingresalo en el campo **Token del feed**. Cargá las claves y los tokens en los campos de la aplicación. Sus valores se usan durante esa sesión.

## Interpretar los resultados

- **Notas** son publicaciones del medio. **Comentarios** y **Chats en vivo** identifican mensajes de lectores y espectadores.
- Las fuentes con filtro temático guardan solo coincidencias. En un video que ya elegiste por el tema, podés dejar ese filtro desactivado para ver todos los comentarios de la ventana consultada.
- **Cobertura parcial** indica que la fuente entregó una ventana limitada, faltaron respuestas o hubo un hueco durante la captura. La búsqueda muestra la ventana disponible y el historial local.
- **Comentarios no disponibles** indica que el video no permite acceder a comentarios por la API, o que el recurso solicitado ya no está disponible. **Sin permiso** indica que la fuente rechazó el acceso.
- **Detener seguimiento** pausa las consultas y conserva los resultados persistidos. Quitar una fuente también conserva su historial. Los comentarios de video agregados desde la ventana tienen una retención de hasta siete días. El chat en vivo de YouTube se conserva en memoria durante la sesión del motor.

El perfil inicial y la comprobación de cada medio se explican en [Fuentes uruguayas](fuentes-uruguay.md).
