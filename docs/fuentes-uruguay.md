# Fuentes uruguayas · Perfil Defensa

El perfil inicia con cuatro RSS públicos de noticias y busca coincidencias en los titulares y resúmenes que publica cada medio. El resultado depende de la ventana que entrega el RSS en cada consulta.

| Fuente | Resultado de la comprobación inicial del 9 de noviembre de 2026 |
|---|---|
| [Telenoche · Nacionales](https://www.telenoche.com.uy/contenidos/rss.html) | 20 entradas. Una coincidencia sobre Sandra Lazo y la investigación de Fray Bentos. |
| [Subrayado · Nacional](https://www.subrayado.com.uy/contenidos/rss.html) | 20 entradas accesibles. |
| [Montevideo Portal · Noticias](https://www.montevideo.com.uy/Utiles/Las-noticias-de-Montevideo-Portal-en-formato-RSS-uc27383) | 8 entradas accesibles. |
| [El Observador · Nacional](https://www.elobservador.com.uy/rss/pages/nacional.xml) | 20 entradas accesibles. |

## Notas de referencia encontradas

- [Telenoche · Sandra Lazo se reunió con legisladores por el caso de los buzos fallecidos](https://www.telenoche.com.uy/nacionales/sandra-lazo-se-reunio-legisladores-caso-buzos-fallecidos-la-investigacion-debe-ser-garantista-n5407053)
- [Subrayado · Informe del Ejército sobre la muerte de tres militares en Fray Bentos](https://www.subrayado.com.uy/informe-del-ejercito-la-muerte-tres-militares-fray-bentos-no-es-concluyente-dijo-la-ministra-sandra-lazo-n1023039)
- [Montevideo Portal · Investigación del Ejército sobre la tragedia en Fray Bentos](https://www.montevideo.com.uy/Noticias/Investigacion-del-Ejercito-sobre-tragedia-en-Fray-Bentos-no-es-concluyente--informo-Lazo-uc981594)
- [El Observador · Lazo se reunió con familiares de militares fallecidos en Fray Bentos](https://www.elobservador.com.uy/nacional/lazo-se-reunio-fray-bentos-los-familiares-los-militares-fallecidos-estoy-dar-la-cara-y-dar-respuestas-las-familias-n6062722)
- [Ministerio de Defensa Nacional · Noticias institucionales](https://www.gub.uy/ministerio-defensa-nacional/tematica/noticias-pagina-principal)

Se comprobó la detección en las notas enlazadas de Telenoche, Subrayado y Montevideo Portal. Ninguna anunció un RSS/Atom de comentarios en su encabezado HTML. Para activar comentarios de esos sitios se necesita un feed anunciado o un mecanismo de acceso que ofrezca el medio. El perfil distingue esos casos de una consulta que sí leyó comentarios y devolvió cero resultados.

## YouTube

La prueba pública de oEmbed confirmó el video [Acto central por el 213.º aniversario del Ejército Nacional](https://www.youtube.com/watch?v=emaHe4GM4G0), del canal Ejército del Uruguay. La consulta de comentarios al endpoint oficial sin credenciales devolvió `403 PERMISSION_DENIED`. La lectura autenticada de ese video queda pendiente de una clave válida y de que el video tenga comentarios habilitados. Los flujos de búsqueda, paginación, respuestas y chat se probaron con servidores locales. [API oficial de comentarios](https://developers.google.com/youtube/v3/docs/commentThreads/list)

La captura de videos consulta una ventana reciente y limita las llamadas adicionales para respuestas. Los registros de esta versión están pensados para seguimiento y lectura. Antes de redistribuir datos obtenidos de YouTube, revisá las condiciones de uso y la política de datos de la integración. [Políticas para desarrolladores](https://developers.google.com/youtube/terms/developer-policies?hl=es)
