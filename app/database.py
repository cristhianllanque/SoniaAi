from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from . import config

engine = create_engine(
    config.DATABASE_URL, pool_pre_ping=True,
    connect_args={'check_same_thread': False} if config.DATABASE_URL.startswith('sqlite') else {},
)

if config.DATABASE_URL.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_schema():
    from . import models
    config.prepare_directories()
    Base.metadata.create_all(bind=engine)
    columns = {column['name'] for column in inspect(engine).get_columns('polleras')}
    with engine.begin() as connection:
        if 'rebaja' not in columns:
            connection.execute(text('ALTER TABLE polleras ADD COLUMN rebaja NUMERIC(12, 2) NOT NULL DEFAULT 0'))
        if 'imagen_url_2' not in columns:
            connection.execute(text('ALTER TABLE polleras ADD COLUMN imagen_url_2 VARCHAR(255)'))
        if 'imagen_url_3' not in columns:
            connection.execute(text('ALTER TABLE polleras ADD COLUMN imagen_url_3 VARCHAR(255)'))
        if 'estado' not in columns:
            connection.execute(text("ALTER TABLE polleras ADD COLUMN estado VARCHAR(20) NOT NULL DEFAULT 'DISPONIBLE'"))
        if 'fecha_alquiler' not in columns:
            connection.execute(text('ALTER TABLE polleras ADD COLUMN fecha_alquiler DATE'))
        if 'fecha_devolucion_estimada' not in columns:
            connection.execute(text('ALTER TABLE polleras ADD COLUMN fecha_devolucion_estimada DATE'))



def get_db():
    with SessionLocal() as db:
        yield db
