"""Storage composition. Drivers are registered independently of application services."""

from importlib.metadata import entry_points
from pathlib import Path

from sqlalchemy.engine import make_url

from echoscope.settings import runtime_settings


def create_store(target):
    if isinstance(target, Path) or "://" not in str(target):
        from .sqlite import Store

        return Store(Path(target))
    try:
        url = make_url(str(target))
    except Exception:
        raise ValueError("La dirección de la base de datos no es válida.") from None
    if url.get_backend_name() == "sqlite":
        if (
            url.drivername not in {"sqlite", "sqlite+aiosqlite"}
            or not url.database
            or url.database == ":memory:"
            or url.query
        ):
            raise ValueError("Usá una base SQLite en archivo, sin parámetros de URL.")
        from .sqlite import Store

        return Store(Path(url.database))
    adapters = entry_points(group="echoscope.storage")
    adapter = next((item for item in adapters if item.name == url.get_backend_name()), None)
    if adapter is None:
        raise ValueError(
            "El motor de base configurado requiere un adaptador de persistencia instalado. "
            "SQLite está incluido."
        )
    return adapter.load()(url, runtime_settings())
