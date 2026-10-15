import hmac
import ipaddress
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from . import config, database, models

ALGORITHM = 'HS256'
COOKIE_NAME = 'iapolleras_session'
CSRF_COOKIE = 'iapolleras_csrf'
pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/api/admin/login', auto_error=False)


@lru_cache
def signing_key():
    return config.session_secret()


def verify_password(plain_password, hashed_password):
    if len(plain_password.encode('utf-8')) > 72:
        return False
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except (ValueError, TypeError):
        return False


def get_password_hash(password):
    if len(password) < 12 or len(password.encode('utf-8')) > 72:
        raise ValueError('La contraseña debe tener al menos 12 caracteres y como máximo 72 bytes.')
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta=None):
    now = datetime.now(timezone.utc)
    payload = {**data, 'iat': now, 'exp': now + (expires_delta or timedelta(minutes=config.SESSION_MINUTES))}
    return jwt.encode(payload, signing_key(), algorithm=ALGORITHM)


def set_session(response, username):
    csrf = secrets.token_urlsafe(32)
    token = create_access_token({'sub': username, 'csrf': csrf})
    options = dict(secure=config.COOKIE_SECURE, samesite='strict', max_age=config.SESSION_MINUTES * 60, path='/')
    response.set_cookie(COOKIE_NAME, token, httponly=True, **options)
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **options)


def get_current_user(request: Request, token: str | None = Depends(oauth2_scheme), db=Depends(database.get_db)):
    cookie_auth = not token
    token = token or request.cookies.get(COOKIE_NAME)
    unauthorized = HTTPException(401, 'Inicia sesión para continuar.', headers={'WWW-Authenticate': 'Bearer'})
    if not token:
        raise unauthorized
    try:
        payload = jwt.decode(token, signing_key(), algorithms=[ALGORITHM], options={'require_exp': True})
        username = payload.get('sub')
        if not isinstance(username, str) or not username:
            raise unauthorized
    except JWTError:
        raise unauthorized
    if cookie_auth and request.method not in ('GET', 'HEAD', 'OPTIONS'):
        supplied = request.headers.get('x-csrf-token', '')
        expected = payload.get('csrf', '')
        if not expected or not hmac.compare_digest(supplied, expected):
            raise HTTPException(403, 'La sesión debe renovarse. Vuelve a iniciar sesión.')
    user = db.query(models.AdminUser).filter(models.AdminUser.username == username).first()
    if not user:
        raise unauthorized
    return user


def require_operator(request: Request, token: str | None = Depends(oauth2_scheme), db=Depends(database.get_db)):
    """The physical kiosk can control detection; remote control requires login."""
    try:
        local = ipaddress.ip_address(request.client.host).is_loopback
    except (ValueError, AttributeError):
        local = False
    if local:
        return None
    return get_current_user(request, token, db)
