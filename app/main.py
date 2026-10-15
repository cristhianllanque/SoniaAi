import asyncio
from datetime import date, timedelta
import json
import logging
import random
import re
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import assistant, auth, config, conversation, database, models, personality, schemas, uploads
from .security import RequestGuard, limiter
from .tts_engine import cleanup_audio, generate_audio
from .yolo_engine import get_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    await run_in_threadpool(database.init_schema)
    auth.signing_key()

    async def maintain_audio():
        while True:
            await run_in_threadpool(cleanup_audio)
            await asyncio.sleep(600)

    maintenance = asyncio.create_task(maintain_audio())
    try:
        yield
    finally:
        maintenance.cancel()
        with suppress(asyncio.CancelledError):
            await maintenance
        await run_in_threadpool(get_engine().stop)
        database.engine.dispose()


app = FastAPI(title='IAPolleras Asistente', lifespan=lifespan)
app.add_middleware(RequestGuard)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.ALLOWED_HOSTS)
app.mount('/static', StaticFiles(directory=config.BASE_DIR / 'app/static'), name='static')
app.mount('/media', StaticFiles(directory=config.UPLOAD_DIR, check_dir=False), name='media')
app.mount('/audio', StaticFiles(directory=config.AUDIO_DIR, check_dir=False), name='audio')
templates = Jinja2Templates(directory=config.BASE_DIR / 'app/templates')


@app.middleware('http')
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    if request.url.path.startswith(('/api/', '/admin', '/static/')):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    return response


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    logger.error('Error de base de datos: %s', type(exc).__name__)
    return JSONResponse({'detail': 'No pudimos consultar el catálogo. Intenta nuevamente en un momento.'}, status_code=503)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    fields = ', '.join(dict.fromkeys(str(e['loc'][-1]) for e in exc.errors()))
    return JSONResponse({'detail': f'Revisa los datos enviados: {fields}.'}, status_code=422)


def limit_speech(request: Request):
    limiter.check(('speech', request.client.host if request.client else 'unknown'), 20, 60)


def load_catalog(db: Session = Depends(database.get_db)):
    return [schemas.Pollera.model_validate(p) for p in db.query(models.Pollera).order_by(models.Pollera.codigo).limit(200).all()]


def load_chat_context(chat_msg: schemas.ChatMessage, db: Session = Depends(database.get_db)):
    codes = re.findall(r'[A-Za-z0-9_-]{1,50}', chat_msg.message.upper())
    explicit = db.query(models.Pollera).filter(or_(
        models.Pollera.codigo.in_(codes),
        models.Pollera.codigo == (chat_msg.codigo_actual or '').upper(),
    )).limit(20).all()
    ids = [p.id for p in explicit]
    rest = db.query(models.Pollera).filter(~models.Pollera.id.in_(ids)).order_by(models.Pollera.codigo).limit(200 - len(explicit)).all()
    return chat_msg, [schemas.Pollera.model_validate(p) for p in explicit + rest]


def find_product(codigo, db):
    product = db.query(models.Pollera).filter(models.Pollera.codigo == codigo.strip().upper()).first()
    if not product:
        raise HTTPException(404, 'Pollera no encontrada.')
    return product


def load_product(codigo: str, db: Session = Depends(database.get_db)):
    return schemas.Pollera.model_validate(find_product(codigo, db))


async def spoken_response(speech_or_text, **extra):
    if hasattr(speech_or_text, 'text'):
        text = speech_or_text.text
        mood = speech_or_text.main_mood
        audio_url = await generate_audio(speech_or_text)
        return {'text': text, 'audio_url': audio_url, 'mood': mood, **extra}
    text = str(speech_or_text)
    audio_url = await generate_audio(text)
    return {'text': text, 'audio_url': audio_url, **extra}


@app.get('/favicon.ico', include_in_schema=False)
def favicon():
    return Response(status_code=204)


@app.get('/')
async def read_root(request: Request):
    return templates.TemplateResponse(request=request, name='index.html')


@app.get('/api/config')
def public_config():
    return {'whatsapp_number': config.WHATSAPP_NUMBER}


@app.get('/api/health')
def health(db: Session = Depends(database.get_db)):
    db.execute(text('SELECT 1'))
    return {'status': 'ok'}


@app.post('/api/vision/start', dependencies=[Depends(auth.require_operator)])
def start_vision(request: Request):
    limiter.check(('camera', request.client.host), 10, 60)
    get_engine().start()
    return get_engine().status()


@app.post('/api/vision/stop', dependencies=[Depends(auth.require_operator)])
def stop_vision():
    get_engine().stop()
    return get_engine().status()


@app.get('/api/vision/status', dependencies=[Depends(auth.require_operator)])
def vision_status():
    return get_engine().status()


@app.post('/api/audio/unlock', dependencies=[Depends(auth.require_operator)])
def unlock_vision():
    get_engine().reset_lock()
    return {'status': 'unlocked'}


@app.get('/api/video_feed', dependencies=[Depends(auth.get_current_user)])
def video_feed():
    if get_engine().status()['state'] not in ('starting', 'running'):
        raise HTTPException(409, 'Activa primero la detección de cámara.')
    return StreamingResponse(get_engine().generate_frames(), media_type='multipart/x-mixed-replace; boundary=frame')


@app.get('/api/check_interest', dependencies=[Depends(auth.require_operator)])
def check_interest():
    return {'interested': get_engine().check_interest(), **get_engine().status()}


@app.get('/api/audio/ofertas', dependencies=[Depends(limit_speech)])
async def generate_ofertas_audio(products=Depends(load_catalog)):
    available = [p for p in products if getattr(p, 'estado', 'DISPONIBLE') == 'DISPONIBLE']
    if not available:
        return await spoken_response(personality.empty_catalog(), imagen_url=None)
    product = random.choice(available)
    speech = personality.offer(product, educate=True)
    return await spoken_response(speech, imagen_url=product.imagen_url)


@app.get('/api/audio/detalles/{codigo}', dependencies=[Depends(limit_speech)])
async def generate_detalles_audio(product=Depends(load_product)):
    speech = personality.presentation(product)
    return await spoken_response(speech, pollera=product)


@app.post('/api/chat', dependencies=[Depends(limit_speech)])
async def chat_with_ai(context=Depends(load_chat_context)):
    chat_msg, products = context
    product = await assistant.select_product(chat_msg.message, products, chat_msg.codigo_actual)
    if product:
        if getattr(product, 'estado', 'DISPONIBLE') == 'ALQUILADA':
            speech, alt = personality.rented_presentation(product, products)
            return await spoken_response(speech, action='show_pollera', pollera=alt or product)
        speech = personality.presentation(product)
        return await spoken_response(speech, action='show_pollera', pollera=product)
    speech = personality.not_found() if products else personality.empty_catalog()
    return await spoken_response(speech, action='none', pollera=None)


@app.post('/api/conversacion', dependencies=[Depends(limit_speech)])
async def conversacion_product(msg: schemas.ConversationMessage, db: Session = Depends(database.get_db)):
    product = find_product(msg.codigo, db)
    catalog = db.query(models.Pollera).order_by(models.Pollera.codigo).limit(200).all()
    others = [schemas.Pollera.model_validate(p) for p in catalog if p.codigo != product.codigo]
    product_schema = schemas.Pollera.model_validate(product)
    reply = await conversation.respond(msg.message, product_schema, others)
    extra = {'action': reply.action}
    if reply.product:
        extra['pollera'] = reply.product
    return await spoken_response(reply.speech, **extra)


@app.get('/api/polleras/{codigo}', response_model=schemas.Pollera)
def read_pollera(codigo: str, db: Session = Depends(database.get_db)):
    return find_product(codigo, db)


@app.get('/api/polleras/', response_model=list[schemas.Pollera])
def list_polleras(skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200), db: Session = Depends(database.get_db)):
    return db.query(models.Pollera).order_by(models.Pollera.codigo).offset(skip).limit(limit).all()


@app.get('/admin/login')
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name='login.html')


@app.get('/admin/dashboard')
async def dashboard_page(request: Request, db: Session = Depends(database.get_db)):
    try:
        await run_in_threadpool(auth.get_current_user, request, None, db)
    except HTTPException:
        return RedirectResponse('/admin/login', status_code=303)
    return templates.TemplateResponse(request=request, name='admin.html')


@app.post('/api/admin/login')
def login(request: Request, response: Response, db: Session = Depends(database.get_db),
          form_data: OAuth2PasswordRequestForm = Depends()):
    limiter.check(('login', request.client.host if request.client else 'unknown'), 5, 60)
    user = db.query(models.AdminUser).filter(models.AdminUser.username == form_data.username).first()
    # Old installations must reset the publicly known default password using the CLI.
    if (not user or form_data.password == 'admin'
            or not auth.verify_password(form_data.password, user.hashed_password)):
        raise HTTPException(401, 'Usuario o contraseña incorrectos.')
    auth.set_session(response, user.username)
    return {'authenticated': True}


@app.get('/api/admin/me', dependencies=[Depends(auth.get_current_user)])
def session_info():
    return {'authenticated': True}


@app.post('/api/admin/logout', dependencies=[Depends(auth.get_current_user)])
def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME, path='/')
    response.delete_cookie(auth.CSRF_COOKIE, path='/')
    return {'authenticated': False}


def validated_product(codigo, nombre, descripcion, talla, precio_base, rebaja, incluye_sombrero, incluye_manta):
    try:
        return schemas.PolleraCreate(
            codigo=codigo, nombre=nombre, descripcion=descripcion, talla=talla,
            precio_base=precio_base, rebaja=rebaja,
            incluye_sombrero=incluye_sombrero, incluye_manta=incluye_manta,
        )
    except ValidationError as exc:
        descriptions = []
        for error in exc.errors():
            field = str(error['loc'][-1]) if error['loc'] else 'precio'
            if field in ('precio_base', 'rebaja', 'precio'):
                descriptions.append('Revisa los precios: deben ser positivos, con hasta dos decimales y la rebaja menor al precio regular (0 sin rebaja).')
            else:
                descriptions.append(f'Revisa {field}: está vacío, es demasiado largo o contiene caracteres no permitidos.')
        raise HTTPException(422, ' '.join(dict.fromkeys(descriptions))) from exc


@app.post('/api/admin/polleras', response_model=schemas.Pollera, status_code=201)
def create_pollera(
    codigo: str = Form(...), nombre: str = Form(...), descripcion: str = Form(...),
    talla: str = Form(...), precio_base: str = Form(...), rebaja: str = Form('0'),
    incluye_sombrero: bool = Form(False), incluye_manta: bool = Form(False),
    imagen: UploadFile | None = File(None),
    imagen_2: UploadFile | None = File(None),
    imagen_3: UploadFile | None = File(None),
    imagen_4: UploadFile | None = File(None),
    db: Session = Depends(database.get_db),
    current_user=Depends(auth.get_current_user),
):
    if imagen_4 and getattr(imagen_4, 'filename', None):
        raise HTTPException(422, 'No se permiten más de tres fotografías por producto.')
    values = validated_product(codigo, nombre, descripcion, talla, precio_base, rebaja, incluye_sombrero, incluye_manta)
    if db.query(models.Pollera.id).filter(models.Pollera.codigo == values.codigo).first():
        raise HTTPException(409, 'Ya existe una pollera con ese código.')
    
    saved_images = []
    try:
        for up in (imagen, imagen_2, imagen_3):
            if up and getattr(up, 'filename', None):
                u = uploads.save_image(up)
                if u:
                    saved_images.append(u)
    except Exception:
        for u in saved_images:
            uploads.discard_image(u)
        raise

    img1 = saved_images[0] if len(saved_images) > 0 else None
    img2 = saved_images[1] if len(saved_images) > 1 else None
    img3 = saved_images[2] if len(saved_images) > 2 else None

    product = models.Pollera(
        **values.model_dump(),
        imagen_url=img1,
        imagen_url_2=img2,
        imagen_url_3=img3,
    )
    try:
        db.add(product)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        for u in saved_images:
            uploads.discard_image(u)
        raise HTTPException(409, 'Ya existe una pollera con ese código.') from exc
    except SQLAlchemyError:
        db.rollback()
        for u in saved_images:
            uploads.discard_image(u)
        raise
    db.refresh(product)
    return product


@app.put('/api/admin/polleras/{product_id}', response_model=schemas.Pollera)
def update_pollera(
    product_id: int, codigo: str = Form(...), nombre: str = Form(...), descripcion: str = Form(...),
    talla: str = Form(...), precio_base: str = Form(...), rebaja: str = Form('0'),
    incluye_sombrero: bool = Form(False), incluye_manta: bool = Form(False),
    imagen: UploadFile | None = File(None),
    imagen_2: UploadFile | None = File(None),
    imagen_3: UploadFile | None = File(None),
    imagen_4: UploadFile | None = File(None),
    eliminar_imagen_1: bool = Form(False),
    eliminar_imagen_2: bool = Form(False),
    eliminar_imagen_3: bool = Form(False),
    db: Session = Depends(database.get_db),
    current_user=Depends(auth.get_current_user),
):
    if imagen_4 and getattr(imagen_4, 'filename', None):
        raise HTTPException(422, 'No se permiten más de tres fotografías por producto.')
    product = db.get(models.Pollera, product_id)
    if not product:
        raise HTTPException(404, 'Pollera no encontrada.')
    values = validated_product(codigo, nombre, descripcion, talla, precio_base, rebaja, incluye_sombrero, incluye_manta)

    newly_saved = []
    discard_candidates = []
    try:
        new1 = uploads.save_image(imagen) if (imagen and getattr(imagen, 'filename', None)) else None
        if new1:
            newly_saved.append(new1)
        new2 = uploads.save_image(imagen_2) if (imagen_2 and getattr(imagen_2, 'filename', None)) else None
        if new2:
            newly_saved.append(new2)
        new3 = uploads.save_image(imagen_3) if (imagen_3 and getattr(imagen_3, 'filename', None)) else None
        if new3:
            newly_saved.append(new3)

        # Slot 1
        slot1 = None
        if eliminar_imagen_1:
            if product.imagen_url:
                discard_candidates.append(product.imagen_url)
        elif new1:
            slot1 = new1
            if product.imagen_url and product.imagen_url != new1:
                discard_candidates.append(product.imagen_url)
        else:
            slot1 = product.imagen_url

        # Slot 2
        slot2 = None
        if eliminar_imagen_2:
            if product.imagen_url_2:
                discard_candidates.append(product.imagen_url_2)
        elif new2:
            slot2 = new2
            if product.imagen_url_2 and product.imagen_url_2 != new2:
                discard_candidates.append(product.imagen_url_2)
        else:
            slot2 = product.imagen_url_2

        # Slot 3
        slot3 = None
        if eliminar_imagen_3:
            if product.imagen_url_3:
                discard_candidates.append(product.imagen_url_3)
        elif new3:
            slot3 = new3
            if product.imagen_url_3 and product.imagen_url_3 != new3:
                discard_candidates.append(product.imagen_url_3)
        else:
            slot3 = product.imagen_url_3

        # Compact images so primary slot 1 is never empty if other photos exist
        compacted = [u for u in (slot1, slot2, slot3) if u]
        if len(compacted) > 3:
            raise HTTPException(422, 'No se permiten más de tres fotografías por producto.')

        product.imagen_url = compacted[0] if len(compacted) > 0 else None
        product.imagen_url_2 = compacted[1] if len(compacted) > 1 else None
        product.imagen_url_3 = compacted[2] if len(compacted) > 2 else None

        for field, value in values.model_dump(exclude={'estado', 'fecha_alquiler', 'fecha_devolucion_estimada'}).items():
            setattr(product, field, value)

        db.commit()
        for old_u in discard_candidates:
            if old_u not in compacted:
                uploads.discard_image(old_u)
    except IntegrityError as exc:
        db.rollback()
        for u in newly_saved:
            uploads.discard_image(u)
        raise HTTPException(409, 'Ya existe una pollera con ese código.') from exc
    except (SQLAlchemyError, HTTPException):
        db.rollback()
        for u in newly_saved:
            uploads.discard_image(u)
        raise
    db.refresh(product)
    return product


@app.delete('/api/admin/polleras/{product_id}', status_code=200)
def delete_pollera(
    product_id: int,
    db: Session = Depends(database.get_db),
    current_user=Depends(auth.get_current_user),
):
    product = db.get(models.Pollera, product_id)
    if not product:
        raise HTTPException(404, 'Pollera no encontrada.')
    images = [u for u in (product.imagen_url, product.imagen_url_2, product.imagen_url_3) if u]
    try:
        db.delete(product)
        db.commit()
        for img_url in images:
            uploads.discard_image(img_url)
    except SQLAlchemyError:
        db.rollback()
        raise
    return {'detail': 'Pollera eliminada con éxito.'}


@app.post('/api/admin/polleras/{product_id}/alquilar', response_model=schemas.Pollera)
async def alquilar_pollera(
    product_id: int,
    request: Request,
    db: Session = Depends(database.get_db),
    current_user=Depends(auth.get_current_user),
):
    product = db.get(models.Pollera, product_id)
    if not product:
        raise HTTPException(404, 'Pollera no encontrada.')

    f_alq = None
    f_dev = None
    content_type = request.headers.get('content-type', '')
    if 'application/json' in content_type:
        try:
            body = await request.json()
            if body.get('fecha_alquiler'):
                f_alq = date.fromisoformat(str(body['fecha_alquiler']))
            if body.get('fecha_devolucion_estimada'):
                f_dev = date.fromisoformat(str(body['fecha_devolucion_estimada']))
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    else:
        form = await request.form()
        if form.get('fecha_alquiler'):
            try:
                f_alq = date.fromisoformat(str(form['fecha_alquiler']))
            except ValueError:
                pass
        if form.get('fecha_devolucion_estimada'):
            try:
                f_dev = date.fromisoformat(str(form['fecha_devolucion_estimada']))
            except ValueError:
                pass

    today = date.today()
    product.estado = 'ALQUILADA'
    product.fecha_alquiler = f_alq or today
    product.fecha_devolucion_estimada = f_dev or (product.fecha_alquiler + timedelta(days=5))
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    db.refresh(product)
    return product


@app.post('/api/admin/polleras/{product_id}/devolver', response_model=schemas.Pollera)
def devolver_pollera(
    product_id: int,
    db: Session = Depends(database.get_db),
    current_user=Depends(auth.get_current_user),
):
    product = db.get(models.Pollera, product_id)
    if not product:
        raise HTTPException(404, 'Pollera no encontrada.')
    product.estado = 'DISPONIBLE'
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    db.refresh(product)
    return product
