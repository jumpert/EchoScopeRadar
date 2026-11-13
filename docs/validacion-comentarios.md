# Validación de comentarios y seguimiento permanente

EchoScope Radar 0.12.0 · 12 de noviembre de 2026

## Comportamiento

- Las fuentes de prensa y los canales de terceros seleccionan publicaciones por coincidencia confirmada en el título.
- Las cuentas declaradas propias consultan publicaciones con otros títulos y analizan todos los comentarios recibidos.
- Las ventanas predeterminadas son siete días para incorporar publicaciones y treinta días para volver a consultar las conversaciones incorporadas. Sin fecha original, se utiliza la primera detección.
- Los presupuestos de recursos, páginas y respuestas limitan la cobertura. Los estados señalan acceso pendiente, falta de acceso, comentarios no disponibles y captura parcial.
- WordPress conserva padre de respuesta y publicación. Disqus conserva cursor y padre de respuesta. Los feeds globales se filtran para evitar asociar comentarios de otras notas.
- Las claves están separadas por cuenta. La propiedad del recurso es declarada por el operador.
- El servidor recupera las cuentas con seguimiento activo durante el arranque. Una pausa explícita evita su recuperación.

## Pruebas externas

Los ocho feeds existentes devolvieron noticias, con ventanas de 8 a 50 entradas. La inspección de una noticia por medio identificó WordPress en Brecha; su API pública devolvió cero comentarios para la nota consultada.

El feed del Ejército del Uruguay anunció noticias y comentarios. Se verificaron diez noticias de su feed. M24, El País Uruguay y el Ministerio de Defensa respondieron como páginas públicas sin un RSS identificado en la ventana inspeccionada. El podcast anunciado por Medios Públicos no se validó como feed compatible.

La prueba de YouTube utilizó exclusivamente la clave local cuya ubicación y uso fueron autorizados. Recuperó 36 comentarios del video emaHe4GM4G0, con 9 coincidencias y título en los 36 registros. El reporte guarda conteos; los textos y la clave no se incluyen en el documento.

Disqus se valida mediante fixtures de su contrato oficial y queda pendiente de una clave propia para la prueba externa. El chat de un directo real elegible queda pendiente; el contrato gRPC y la reconexión se verifican localmente.

## Accesos pendientes

Facebook, Instagram, X, TikTok, Threads, Reddit, Telegram y canales de WhatsApp se pueden registrar para preparar su integración. Esta versión no implementa sus lecturas autenticadas. Los requisitos específicos y enlaces oficiales están en fuentes-uruguay-conexiones.md.

La lectura HTML se utiliza para descubrir mecanismos anunciados. No se entrega un extractor genérico de todos los comentarios visibles de cualquier página. Un sistema adicional requiere un lector específico, permiso y una prueba de acceso.

## Operación

El ZIP Windows incluye las guías de fuentes y SQL, y la plantilla de servicio Ubuntu. Los servicios no se instalan automáticamente. La prueba Ubuntu se realiza en contenedor Ubuntu 24.04 con la red deshabilitada después de instalar las dependencias. Las consultas SQL de la guía se prueban con SQLite estándar en modo lectura.

## Resultados de plataforma

| Entorno | Resultado |
|---|---|
| Windows 11, Python 3.12.5 | 47 pruebas aprobadas; dos pruebas optativas de Internet/rendimiento excluidas |
| Ubuntu 24.04, Python 3.12.3, contenedor Linux/WSL2 | 46 pruebas aprobadas; una específica de Windows omitida; las dos optativas excluidas |
| Aceptación en ambos sistemas | Demo concurrente, historial tras reinicio, configuración por entorno, temas, exportación PDF y cierre ordenado |
| Ejecutable Windows empaquetado | Inicio con base temporal, versión 0.12.0, formulario actualizado, PDF y cierre comprobados |
| Navegador local | Registro de cuenta propia y plataforma pendiente comprobado; la fuente permanece desactivada y muestra su condición |

Las pruebas reproducibles incluyen WordPress, Disqus, paginación y respuestas de YouTube, seguimiento de cuentas propias, recuperación del servidor antes del inicio de sesión y consultas SQL de la guía. El cursor de comentarios de cada video continúa entre ciclos; al completar su ventana, la siguiente consulta vuelve a los comentarios recientes. Los cambios de paginación del proveedor pueden dejar huecos, indicados como captura parcial; las respuestas también están sujetas al presupuesto de consultas.

La validación Linux es headless y web en contenedor, sin comprobación visual de una terminal gráfica Ubuntu física. Permanecen dos avisos no bloqueantes de aiohttp sobre el uso recomendado de AppKey. No se presenta una nueva medición de rendimiento como parte de esta entrega.
