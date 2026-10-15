"""Local administration: python -m app.manage --help."""
import argparse
import getpass

from sqlalchemy import inspect, text
from . import auth, database, models


def main():
    parser = argparse.ArgumentParser(description='Administración local de IAPolleras')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init-db', help='Crear tablas y agregar rebaja si falta; no borra productos')
    admin = commands.add_parser('create-admin', help='Crear o restablecer un administrador')
    admin.add_argument('--username', default='admin')
    admin.add_argument('--reset', action='store_true', help='Restablecer un usuario existente')
    commands.add_parser('upgrade-prices', help='Convertir FLOAT a DECIMAL en MySQL, luego de un respaldo')
    commands.add_parser('clean-audio', help='Limpiar la caché generada en data/audio')
    args = parser.parse_args()
    if args.command == 'clean-audio':
        from .tts_engine import cleanup_audio
        cleanup_audio()
        print('Caché de audio revisada.')
        return
    database.init_schema()
    if args.command == 'init-db':
        print('Base preparada. No se crea ningún administrador automáticamente.')
        return
    if args.command == 'upgrade-prices':
        if database.engine.dialect.name != 'mysql':
            print('Esta migración es para MySQL. En SQLite se normalizan importes a dos decimales en la aplicación.')
            return
        columns = {c['name']: str(c['type']).upper() for c in inspect(database.engine).get_columns('polleras')}
        with database.engine.connect() as connection:
            invalid = connection.execute(text(
                'SELECT COUNT(*) FROM polleras WHERE precio_base IS NULL OR precio_base <= 0 '
                'OR rebaja IS NULL OR rebaja < 0 OR rebaja >= precio_base '
                'OR precio_base >= 10000000000 OR rebaja >= 10000000000 '
                'OR ABS(precio_base - ROUND(precio_base, 2)) > 0.0001 '
                'OR ABS(rebaja - ROUND(rebaja, 2)) > 0.0001'
            )).scalar()
        if invalid:
            parser.error(f'Corrige los precios de {invalid} productos antes de migrar.')
        if any(not columns[name].startswith(('NUMERIC', 'DECIMAL')) for name in ('precio_base', 'rebaja')):
            with database.engine.begin() as connection:
                connection.execute(text('ALTER TABLE polleras MODIFY precio_base DECIMAL(12,2) NOT NULL, MODIFY rebaja DECIMAL(12,2) NOT NULL DEFAULT 0'))
        print('Columnas de precio preparadas.')
        return
    username = args.username.strip()
    if not username or len(username) > 50:
        parser.error('El usuario debe tener entre 1 y 50 caracteres.')
    with database.SessionLocal() as db:
        user = db.query(models.AdminUser).filter_by(username=username).first()
        if user and not args.reset:
            parser.error('El usuario ya existe. Usa --reset para cambiar su contraseña.')
        password = getpass.getpass('Nueva contraseña (mínimo 12 caracteres): ')
        if password != getpass.getpass('Repite la contraseña: '):
            parser.error('Las contraseñas no coinciden.')
        try:
            hashed = auth.get_password_hash(password)
        except ValueError as exc:
            parser.error(str(exc))
        if user:
            user.hashed_password = hashed
        else:
            db.add(models.AdminUser(username=username, hashed_password=hashed))
        db.commit()
    print('Administrador guardado. Inicia sesión desde /admin/login.')


if __name__ == '__main__':
    main()
