# Almacenamiento y acceso real · 0.14.2

## Base comprobada en esta computadora

La lectura directa del 13 de noviembre de 2026 confirmó el archivo existente:

```text
C:\Users\user\AppData\Local\EchoScopeRadar\administracion.sqlite
```

| Medida | Resultado de la comprobación |
|---|---:|
| Archivo principal | 3.899.392 bytes = 3,90 MB = 3,72 MiB |
| Capturas almacenadas (`message_sources`) | 1.242 |
| Mensajes únicos (`messages`) | 1.202 |
| Alertas por regla (`alerts`) | 110 |
| Noticias | 1.080 |
| Comentarios de prensa | 77 |
| Comentarios de video (`COMMENT`) | 73 |
| Publicaciones de video | 12 |
| Ejecuciones | 2.403 |
| Eventos | 5.180 |

Las capturas incluyen observaciones de un mismo mensaje en distintas tareas o versiones; no equivalen necesariamente a personas ni comentarios únicos. Las alertas son asociaciones con reglas, no un conteo de personas. Los números y tamaños cambian mientras el motor recaba datos. No se eliminaron datos de esta base durante la implementación ni las pruebas.

La misma carpeta contiene `demo.sqlite`, que pertenece a una demostración anterior y tiene sus propios datos. No debe confundirse con la base real. La práctica de la mesa web usa `practica.sqlite` cuando se ejecuta sin una ruta personalizada.

## Verlo desde EchoScope

1. Abrí la aplicación con **Abrir EchoScope Radar.cmd**. La versión 0.14.2 no crea ventana de control adicional.
2. Entrá a **Base de datos**. **Almacenamiento y mantenimiento** muestra la ruta absoluta obtenida del almacén que realmente está abierto, no una ruta de ejemplo ni la base de otro comando.
3. Usá **Actualizar capacidad** para ver conteos, bytes del archivo principal, WAL y SHM, páginas reutilizables y espacio libre del disco.
4. **Copiar ruta** copia el archivo activo para abrirlo con un gestor externo.
5. Más abajo, **Consultar** permite filtrar fechas, fuente, tipo, palabras, tono y coincidencias. **Ver contenido completo** muestra lo guardado. También se puede exportar a CSV, Excel o PDF.

La instalación SQLite no reserva un cupo fijo de almacenamiento: comparte el espacio libre del disco con el resto de los archivos. Borrar registros puede liberar páginas dentro de SQLite sin achicar inmediatamente el archivo; por eso se muestran tanto tamaño físico como espacio reutilizable. El WAL contiene cambios pendientes de consolidación y su tamaño fluctúa durante la captura.

En servidor compartido, los conteos corresponden a la cuenta autenticada; la interfaz no revela la ruta privada ni el espacio global del servidor.

## Limpieza por antigüedad

Indicá cuántos días querés conservar y elegí **Previsualizar limpieza**. Por defecto está activado **Conservar todos los registros con coincidencias**, incluidas aproximaciones pendientes de revisión. Si desmarcás esa opción, también podrán eliminarse coincidencias antiguas, lo cual se advierte en la vista previa.

Antes de eliminar se muestran el límite de antigüedad y los conteos de capturas, alertas y eventos técnicos afectados. Solo se ejecuta al presionar **Eliminar datos antiguos**; **Cancelar** conserva todo. La confirmación vence a los cinco minutos. Los registros que llegan después de la vista previa no se incluyen en esa selección.

La función elimina las capturas seleccionadas, sus alertas y asociaciones huérfanas, los eventos técnicos antiguos sin capturas y las ejecuciones antiguas que queden sin eventos. Conserva fuentes, lista blanca, claves y configuración. El motor se pausa durante el mantenimiento y recupera su estado previo, incluso si la operación falla. SQLite intenta compactar al terminar; si otro lector impide la compactación, se informa y las páginas libres siguen disponibles para reutilizar.

Esta limpieza manual no extiende la retención automática de las fuentes. La pantalla muestra los plazos configurados; el perfil actual aplica hasta 30 días de prensa y siete días a los recursos de YouTube incorporados. Exportá los resultados que quieras conservar fuera de esos plazos.

## Abrir el archivo existente en DBeaver

1. Elegí **Base de datos → Nueva conexión → SQLite**.
2. En **Path / Database file**, pegá la ruta completa comprobada arriba. Seleccioná el archivo existente `administracion.sqlite`.
3. Finalizá la conexión. SQLite local no requiere host, puerto, usuario ni contraseña. DBeaver puede pedir descargar su controlador SQLite.
4. Para inspeccionar, configurá una conexión de solo lectura. Abrí **Views / Vistas → capturas → Data / Datos**.
5. La vista `capturas` se crea al abrir la base con 0.14.2. Si aún no aparece, iniciá una vez esta versión y actualizá el árbol de DBeaver. En versiones anteriores se pueden consultar directamente `message_sources` y `message_versions` con el SQL siguiente.

[Documentación oficial de la conexión SQLite en DBeaver](https://dbeaver.com/docs/dbeaver/Database-driver-SQLite/).

Consulta después de actualizar:

```sql
SELECT * FROM capturas ORDER BY id DESC LIMIT 100;
```

Consulta compatible con la base anterior, sin necesitar la vista nueva:

```sql
SELECT s.id, s.source AS fuente, s.captured AS capturado_utc,
       json_extract(s.metadata, '$.kind') AS tipo,
       coalesce(json_extract(s.metadata, '$.resource_title'),
                json_extract(s.metadata, '$.title')) AS titulo,
       json_extract(s.metadata, '$.author') AS autor,
       v.body AS texto, json_extract(s.metadata, '$.url') AS enlace
FROM message_sources s
JOIN message_versions v ON v.id = s.version
ORDER BY s.id DESC LIMIT 100;
```

No selecciones `administracion.sqlite-wal`, `-shm`, un ejecutable o una carpeta de instalación como base. Las carpetas `dist` contienen el programa; los datos reales comprobados están en AppData. Las variables de entorno o `--db` pueden seleccionar otra base, y en ese caso manda la ruta que muestra la propia aplicación. No pegues una ruta de ejemplo si querés inspeccionar datos existentes: un gestor puede crear accidentalmente un archivo vacío si el nombre es incorrecto.

Para repetir el inventario sin modificar datos:

```powershell
.venv\Scripts\python.exe scripts/database-inventory.py "C:\Users\user\AppData\Local\EchoScopeRadar\administracion.sqlite"
```

## Navegador y continuidad

Tras iniciar la aplicación, la dirección local predeterminada es `http://127.0.0.1:8765/`. Al cerrar la pestaña o el navegador, el proceso sigue recabando y guardando información. Al volver a esa dirección se consultan los resultados acumulados. Volver a ejecutar el acceso de apertura reutiliza una instancia de esta versión que ya esté sirviendo la misma base en el mismo puerto.

Para terminar realmente, usá **Cerrar EchoScope → Salir y detener captura** en el navegador. La elección **Confirmar segundo plano** permite cerrar el navegador sin parar el proceso. El equipo debe seguir encendido y sin suspensión. Apagar o reiniciar Windows detiene el proceso; luego hay que iniciar la aplicación otra vez. No se instala un servicio ni un inicio automático de Windows con esta actualización.
