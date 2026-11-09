from alembic import context
from sqlalchemy import engine_from_config

if context.is_offline_mode():
    context.configure(url=context.config.get_main_option("sqlalchemy.url"))
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = engine_from_config(context.config.get_section("alembic"), prefix="sqlalchemy.")
    with engine.begin() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        context.configure(connection=connection, transactional_ddl=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
