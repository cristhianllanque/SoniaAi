"""Started only by browser_smoke.cjs with a fresh temporary database."""
import os
from pathlib import Path

if os.environ.get('IAPOLLERAS_BROWSER_TEST') != '1':
    raise RuntimeError('This fixture must only be started by the isolated browser test.')

from app import assistant, auth, config, database, main, models

if not config.DATA_DIR.parent.name.startswith('iapolleras-browser-'):
    raise RuntimeError('Unsafe test data directory.')
database.init_schema()
with database.SessionLocal() as db:
    db.add(models.AdminUser(username='owner', hashed_password=auth.get_password_hash('browser-test-password')))
    db.add(models.Pollera(codigo='34TM',nombre='Pollera Andina',descripcion='Bordado floral para tu celebración.',
                         talla='M',precio_base=100,rebaja=80,incluye_sombrero=True,incluye_manta=False,
                         imagen_url='/static/img/taran.jpeg',
                         imagen_url_2='/static/img/default.svg',
                         imagen_url_3='/static/img/taran.jpeg'))
    db.commit()


async def no_voice(text):
    return None


async def no_model(prompt):
    return None


main.generate_audio = no_voice
assistant.query_ollama = no_model

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(main.app,host='127.0.0.1',port=int(os.environ['IAPOLLERAS_TEST_PORT']),log_level='warning')
