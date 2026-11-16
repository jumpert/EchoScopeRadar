> Para esta computadora, la ruta comprobada, conteos actuales y pasos de DBeaver están en [Almacenamiento y acceso real](almacenamiento-y-acceso.md). Las rutas personalizadas de los ejemplos siguientes no representan necesariamente tu instalación.

# Consultar directamente la base de datos

EchoScope Radar 0.12.0 · 12 de noviembre de 2026

## Qué conexión utiliza la aplicación

La instalación incluida utiliza SQLite. Se abre un archivo local y no requiere host, puerto, usuario ni contraseña de base de datos. Las credenciales de las redes son independientes.

| Forma de ejecución | Archivo predeterminado |
|---|---|
| Web o escritorio local, Windows | %LOCALAPPDATA%/EchoScopeRadar/administracion.sqlite |
| Práctica web o escritorio, Windows | %LOCALAPPDATA%/EchoScopeRadar/practica.sqlite |
| CLI operativa | radar.sqlite dentro de la carpeta de datos |
| Demo CLI | demo.sqlite dentro de la carpeta de datos |
| Web local, Ubuntu | ~/.local/share/EchoScopeRadar/administracion.sqlite, salvo XDG_DATA_HOME |
| Servidor compartido | SERVER_DIR/users/SHA256(usuario)/radar.sqlite |
| Cuentas del servidor | SERVER_DIR/accounts.sqlite |

ECHOSCOPE_DATA_DIR modifica la carpeta predeterminada. ECHOSCOPE_DATABASE_URL o --database-url selecciona una conexión explícita para la estación operativa. --db selecciona un archivo concreto. El demo conserva una base independiente. En servidor, cada usuario tiene un archivo propio dentro de SERVER_DIR.

## Encontrar la ubicación efectiva

La CLI puede indicar el motor y la URI de lectura sin abrir la base:

    uv run --no-sync echoscope --env-file /ruta/instalacion.env doctor --storage-info

Ese comando informa la base de la CLI. Para consultar la estación administrativa, indicá su archivo:

    uv run --no-sync echoscope --db C:/EchoScopeRadar/datos/administracion.sqlite doctor --storage-info

Para el servidor, el administrador puede calcular la subcarpeta correspondiente al usuario:

    python -c "import hashlib; print(hashlib.sha256('analista'.encode()).hexdigest())"

El resultado se encuentra debajo de SERVER_DIR/users. El usuario debe escribirse exactamente como en el inicio de sesión. El acceso al archivo depende de los permisos del sistema operativo. La base de cuentas contiene verificadores de contraseñas y se reserva a la administración del servidor.

## Abrir en una herramienta gráfica

En DB Browser for SQLite o en una conexión SQLite de DBeaver:

1. Elegí abrir una base SQLite existente.
2. Seleccioná el archivo identificado anteriormente.
3. Activá modo de solo lectura.
4. Usá la pestaña de ejecución SQL para pegar una consulta de esta guía.

Podés consultar mientras funciona EchoScope con transacciones de lectura cortas. Para hacer una copia consistente mediante copia de archivos, detené el motor primero y conservá los archivos auxiliares que existan. La edición externa puede romper cursores, reglas y asociaciones, por lo que esta guía utiliza lectura.

## Consultar desde terminal o Python

Con la herramienta sqlite3 instalada:

    sqlite3 -readonly "C:/EchoScopeRadar/datos/administracion.sqlite"

En Ubuntu:

    sqlite3 -readonly "/var/lib/echoscope/administracion.sqlite"

Con Python, sin instalar otro cliente:

    from pathlib import Path
    import sqlite3
    path = Path("C:/EchoScopeRadar/datos/administracion.sqlite").resolve()
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        print(db.execute("SELECT count(*) FROM messages").fetchone())

La URI mode=ro abre una base existente en modo lectura. [Documentación de SQLite](https://sqlite.org/uri.html)

## Consultas SQL

### Mensajes recientes y publicación relacionada

```sql
SELECT s.id, s.job, s.source,
       json_extract(s.metadata, '$.kind') AS tipo,
       json_extract(s.metadata, '$.resource_title') AS titulo_publicacion,
       json_extract(s.metadata, '$.resource_id') AS recurso,
       json_extract(s.metadata, '$.url') AS enlace_mensaje,
       json_extract(s.metadata, '$.author') AS autor,
       s.captured, v.body AS contenido
FROM message_sources s
JOIN message_versions v ON v.id = s.version
WHERE julianday(s.expires) > julianday('now')
ORDER BY s.id DESC LIMIT 100;
```

### Comentarios, reseñas y respuestas

```sql
SELECT s.id,
       json_extract(s.metadata, '$.resource_id') AS publicacion,
       json_extract(s.metadata, '$.resource_title') AS titulo,
       json_extract(s.metadata, '$.parent_id') AS comentario_padre,
       json_extract(s.metadata, '$.author') AS autor,
       json_extract(s.metadata, '$.url') AS enlace,
       v.body AS comentario
FROM message_sources s
JOIN message_versions v ON v.id = s.version
WHERE json_extract(s.metadata, '$.kind') IN
      ('COMMENT','PRESS_COMMENT','REVIEW','SOCIAL_COMMENT','FORUM_POST')
  AND julianday(s.expires) > julianday('now')
ORDER BY publicacion, s.id DESC LIMIT 200;
```

El identificador de recurso de YouTube es el ID del video. En prensa es la URL de la nota cuando el conector pudo establecer esa relación. parent_id conserva la respuesta a otro comentario cuando el proveedor la entregó.

### Coincidencias con la lista blanca

```sql
SELECT s.id, s.source, a.severity, a.confirmed,
       r.rule_id, m.term, m.method, m.start, m.end,
       json_extract(s.metadata, '$.resource_title') AS titulo,
       v.body
FROM alerts a
JOIN message_sources s ON s.id = a.observation
JOIN message_versions v ON v.id = s.version
JOIN rule_versions r ON r.revision = a.rule
JOIN match_occurrences m ON m.alert = a.id
WHERE julianday(s.expires) > julianday('now')
ORDER BY s.id DESC LIMIT 200;
```

confirmed=1 indica coincidencia confirmada por reglas. method=review identifica una aproximación. La decisión del operador se registra en otra tabla.

### Estado de revisión del operador

```sql
SELECT item AS identificador_alerta, state, changed
FROM alert_reviews
ORDER BY changed DESC LIMIT 100;
```

state puede ser verified, threat o dismissed. La ausencia de decisión equivale a sin verificar. item es un hash estable de tarea, origen, identificador externo y texto. SQLite estándar no incluye SHA256, por lo que esta consulta muestra las decisiones por su identificador. La aplicación realiza su asociación al consultar mensajes.

### Ejecuciones y seguimiento

```sql
SELECT job, enabled, paused, state, detail, last_at, next_at
FROM runtime ORDER BY job;

SELECT job, started, ended, outcome
FROM executions ORDER BY id DESC LIMIT 50;

SELECT key, value FROM desktop_settings
WHERE key IN ('monitoring_enabled', 'theme', 'source_layout');
```

Estas consultas no requieren funciones privadas de EchoScope. Evitá consultar o exportar credential_vault para tareas de análisis.

## Fechas y datos que pueden faltar

Las capturas y ejecuciones usan UTC. El contenido puede desaparecer por retención o purga. Los chats de YouTube se conservan en memoria durante la sesión y no aparecen como texto en SQLite. Las vistas previas son de sesión; para conservar capturas compatibles en el historial, agregá el recurso a Fuentes. Las bases anteriores pueden tener parent_id y resource_title vacíos.
