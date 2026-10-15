"""Configuration from environment variables or a local .env file."""
from pathlib import Path
from starlette.config import Config

BASE_DIR = Path(__file__).resolve().parent.parent
env = Config(BASE_DIR / '.env') if (BASE_DIR / '.env').exists() else Config()
DATA_DIR = Path(env('DATA_DIR', default=str(BASE_DIR / 'data'))).resolve()
DATABASE_URL = env('DATABASE_URL', default=f"sqlite:///{DATA_DIR / 'iapolleras.db'}")
PRODUCTION = env('PRODUCTION', cast=bool, default=False)
SECRET_KEY = env('SECRET_KEY', default='')
COOKIE_SECURE = env('COOKIE_SECURE', cast=bool, default=PRODUCTION)
SESSION_MINUTES = env('SESSION_MINUTES', cast=int, default=60)
ALLOWED_HOSTS = [s.strip() for s in env('ALLOWED_HOSTS', default='localhost,127.0.0.1,[::1]').split(',')]
OLLAMA_URL = env('OLLAMA_URL', default='http://127.0.0.1:11434/api/generate')
OLLAMA_MODEL = env('OLLAMA_MODEL', default='llama3')
OLLAMA_TIMEOUT = env('OLLAMA_TIMEOUT', cast=float, default=20.0)
TTS_TIMEOUT = env('TTS_TIMEOUT', cast=float, default=15.0)
VOICE_EDGE = env('VOICE_EDGE', default='es-MX-DaliaNeural')
PIPER_BIN = env('PIPER_BIN', default='piper')
PIPER_MODEL = Path(env('PIPER_MODEL', default=str(BASE_DIR / 'es_ES-davefx-medium.onnx')))
WHATSAPP_NUMBER = env('WHATSAPP_NUMBER', default='51974342536')
CAMERA_INDEX = env('CAMERA_INDEX', cast=int, default=1)
CAMERA_FPS = max(1, min(15, env('CAMERA_FPS', cast=int, default=8)))
UPLOAD_DIR = DATA_DIR / 'uploads'
AUDIO_DIR = DATA_DIR / 'audio'
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_BODY_BYTES = 6 * 1024 * 1024
AUDIO_RETENTION_SECONDS = 24 * 60 * 60


def prepare_directories():
    if PRODUCTION and (len(SECRET_KEY) < 32 or not COOKIE_SECURE):
        raise RuntimeError('Producción requiere SECRET_KEY de al menos 32 caracteres y COOKIE_SECURE=true.')
    for directory in (DATA_DIR, UPLOAD_DIR, AUDIO_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def session_secret():
    """A persistent random key for local development; production supplies its own."""
    if SECRET_KEY:
        if len(SECRET_KEY) < 32:
            raise RuntimeError('SECRET_KEY debe tener al menos 32 caracteres.')
        return SECRET_KEY
    if PRODUCTION:
        raise RuntimeError('Falta configurar SECRET_KEY.')
    import secrets
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / '.session-key'
    try:
        with path.open('x', encoding='utf-8') as handle:
            handle.write(secrets.token_urlsafe(48))
    except FileExistsError:
        pass
    value = path.read_text(encoding='utf-8').strip()
    if len(value) < 32:
        raise RuntimeError('La clave local de sesión está incompleta. Configura una SECRET_KEY válida.')
    return value
