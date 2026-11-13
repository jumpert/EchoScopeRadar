# Documento funcional de EchoScope Radar

Actualizado para 0.12.0 · 12 de noviembre de 2026

Desde 0.12.0 podés elegir **Por tema** o **Cuenta propia · seguimiento permanente** en cada fuente. En la primera modalidad, prensa y canales seleccionan publicaciones por el título. En la segunda, siguen publicaciones recientes aunque el título sea diferente. En servidor, Iniciar seguimiento guarda la intención y la recupera al reiniciar, sin otro inicio de sesión. Pausar seguimiento guarda la pausa. Las ventanas iniciales de siete días y de seguimiento de treinta días se pueden ajustar por fuente en YAML mediante initial_days y follow_days; resources_per_cycle limita la rotación por ciclo.

Las redes registradas con acceso pendiente conservan su URL y modalidad, y permanecen desactivadas. WordPress público y Disqus amplían los mecanismos de lectura de comentarios. Disqus requiere una clave propia en el almacén. Las vistas previas usan reglas y alertas de sesión; agregá la fuente para conservar capturas persistentes compatibles.

## Finalidad

EchoScope Radar permite al personal administrativo seguir noticias, comentarios, reseñas, publicaciones y conversaciones sobre términos definidos por la organización. Reúne los mensajes recibidos, destaca coincidencias y permite revisar alertas y preparar informes.

La cobertura depende de cada sitio y del acceso configurado. Una página puede mostrar comentarios en el navegador y ofrecer a EchoScope únicamente noticias. El estado de la fuente y los enlaces originales permiten comprobar qué se recibió.

## Abrir y cerrar

En Windows, extraé el paquete completo y abrí **Abrir EchoScope Radar.cmd**. Se abre el navegador de la estación. **Probar EchoScope Radar.cmd** inicia una práctica con comentarios ficticios.

En un servidor compartido, abrí la dirección HTTPS que te entregue el administrador e iniciá sesión. Cada cuenta tiene sus fuentes, historial, claves y decisiones de revisión. **Cerrar sesión** termina el acceso desde el navegador. **Pausar seguimiento** detiene las consultas de esa cuenta.

La captura continúa aunque el navegador esté minimizado. En la estación local, **Cerrar EchoScope** termina el motor. La estación puede cerrarse si pierde durante el plazo configurado la comunicación con la ventana que abrió. En un servidor, el servicio determina la duración del motor.

## Primera configuración

1. Entrá a **Tema y acceso**.
2. Escribí una palabra o frase por línea. Por ejemplo, Ejército, Defensa y soldado.
3. Guardá la lista blanca.
4. Si vas a consultar YouTube o un buscador con clave, entrá a **Claves API**, elegí el proveedor y guardá la clave con un nombre reconocible.
5. En **Fuentes**, revisá qué recursos están activos.
6. Elegí **Iniciar seguimiento** y volvé a **Mesa de monitoreo**.

Las variantes claras de una palabra pueden generar coincidencias. Las aproximaciones se muestran en **Para revisar**. Revisá el contexto antes de decidir cómo clasificar un mensaje.

## Encontrar y seguir recursos

**Buscar por tema** consulta el historial y los mecanismos de descubrimiento habilitados. Los resultados pueden incluir varias publicaciones y sitios. Los buscadores activos reciben el texto de la consulta.

Los canales automáticos de YouTube consultan los videos o directos relacionados con los términos. También podés agregar manualmente un video, directo, canal, feed o hilo compatible desde **Agregar fuente**.

En **Fuentes**, las categorías iniciales son YouTube, Prensa, Redes sociales y Otros. Podés crear otra categoría y mover las fuentes arrastrando desde ⠿. El selector de categoría y las flechas permiten organizar con teclado. La organización se conserva en tu cuenta. Cambiar una categoría modifica la presentación de la lista.

## Configurar reseñas

1. En el panel **Reseñas**, abrí **Cómo recibir reseñas**.
2. Copiá la dirección de la página donde se leen las reseñas.
3. Elegí **Agregar una página de reseñas**, escribí un nombre y pegá la dirección.
4. Elegí **Buscar reseñas en la página**.
5. Si se encuentra una lista pública, guardá la fuente.
6. Con el seguimiento activo, entrá a **Fuentes** y elegí **Consultar ahora**, o esperá al siguiente ciclo.

Si el sitio no anuncia una lista pública, pedile el enlace a su lista de reseñas, también llamada RSS o Atom. Podés pegar ese enlace directamente. Una cuenta de una red social requiere además un conector compatible y los permisos de esa plataforma.

## Usar la mesa

Cada panel presenta su estado, resultados y cantidad de fuentes habilitadas respecto de las configuradas. **Recursos visibles** cuenta publicaciones, conversaciones o feeds distintos en la ventana que muestran los filtros.

Podés ocultar paneles, cambiar su orden y ancho, ampliar uno o usar **Proyección**. F11 utiliza la pantalla completa del navegador. **Congelar vista** permite leer mientras siguen llegando mensajes.

Los títulos aparecen separados de los fragmentos. Los comentarios de videos y chats se agrupan bajo el recurso original. Cada registro conserva la hora, autor disponible y un fragmento del contexto. Abrí el registro o el vínculo para ampliar la lectura.

El selector de apariencia ofrece Claro, Claro medio, Oscuro y Muy oscuro.

## Revisar alertas

Una coincidencia identifica un término de la lista. La severidad corresponde a la regla. El tono positivo, negativo, mixto o neutro es una estimación por reglas de texto.

1. Filtrá por estado o tono.
2. Abrí la alerta y leé su contexto.
3. Seleccioná una, varias o todas las visibles.
4. Elegí **Verificadas**, **Amenazas**, **Descartadas** o **Sin verificar** y aplicá el cambio.

**Amenazas** registra una valoración del operador. **Descartadas** permite gestionar falsos positivos conservando el historial mientras esté vigente. El filtro **Para revisar** reúne coincidencias aproximadas.

## Claves y accesos

Los proveedores integrados permiten seleccionar una clave activa. Los servicios indicados como **Solo almacenamiento** guardan una credencial para una futura integración. Incorporar una clave de IA por sí solo no ejecuta análisis mediante IA.

En servidor, las claves del almacén se cifran y se separan por cuenta. En estación local, las claves introducidas durante el uso duran la sesión. El administrador puede configurar claves locales desde un archivo protegido.

El token de un feed protegido se introduce al configurar esa fuente. Su disponibilidad debe comprobarse después de reiniciar porque el acceso del feed se mantiene en el entorno de la sesión.

## Informes

En **Descargar PDF**, indicá las fechas de captura en UTC.

**Resumen para imprimir** muestra el estado de revisión mediante barras, los términos más frecuentes y hasta cinco publicaciones prioritarias con dos alertas por publicación. Prioriza amenazas marcadas y críticas pendientes. Indica cuántos registros quedaron fuera del detalle.

**Detalle completo** agrega un cuadro por tipo de contenido y las publicaciones con sus coincidencias del período disponible, incluidas las descartadas. Cada grupo tiene el enlace original cuando se conoce. Las cifras se calculan sobre registros con coincidencias y estado actual de revisión.

YouTube aporta referencias agrupadas a los originales en el informe. La ventana de su chat dura la sesión y queda fuera de las cifras agregadas del PDF.

## Estados y resolución de problemas

| Mensaje | Cómo proceder |
|---|---|
| Seguimiento pausado | Elegí Iniciar seguimiento |
| Sin resultados | Revisá el filtro, los términos y la fecha de la fuente |
| Credencial ausente o inválida | Revisá la clave activa y verificá el acceso |
| Sin permiso | Pedí al responsable de la cuenta que revise sus permisos |
| Cuota alcanzada | Esperá la recuperación indicada por el proveedor |
| Esperando directo | El canal todavía no ofrece un directo pertinente accesible |
| Chat no disponible | Abrí el original y comprobá si tiene chat y acceso compatible |
| Captura parcial | Leé el historial disponible considerando el posible hueco |
| Base temporalmente inaccesible | Esperá el reintento y consultá al administrador si persiste |

Los datos expiran según la retención de cada fuente, con un máximo inicial de 30 días y límites inferiores para determinados conectores. El historial y replay consultan los datos todavía disponibles. Para soporte, indicá el nombre de la fuente, la hora y el mensaje de estado.
