"""Regression tests; isolated files, database and external services."""
import asyncio
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Never import application configuration against the operator's database.
TEST_TEMP = tempfile.TemporaryDirectory(prefix='iapolleras-tests-')
TEST_ROOT = Path(TEST_TEMP.name).resolve()
os.environ['DATA_DIR'] = str(TEST_ROOT)
os.environ['DATABASE_URL'] = f"sqlite:///{TEST_ROOT / 'test.db'}"
os.environ['SECRET_KEY'] = 'isolated-test-key-' * 4
os.environ['PRODUCTION'] = 'false'
os.environ['COOKIE_SECURE'] = 'false'
os.environ['ALLOWED_HOSTS'] = 'testserver,localhost,127.0.0.1'

import httpx
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, inspect, text

from app import assistant, auth, config, conversation, database, main, models, personality, schemas, tts_engine
from app.security import limiter
from app.yolo_engine import YoloEngine, get_engine

PASSWORD = 'test-password-with-entropy'
HASH = auth.get_password_hash(PASSWORD)


def tearDownModule():
    database.engine.dispose()
    if TEST_ROOT.parent != Path(tempfile.gettempdir()).resolve():
        raise RuntimeError('Unexpected temporary directory.')
    TEST_TEMP.cleanup()


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(Path(database.engine.url.database).resolve().parent, TEST_ROOT)
        database.Base.metadata.drop_all(database.engine)
        database.init_schema()
        limiter.entries.clear()
        with database.SessionLocal() as db:
            db.add(models.AdminUser(username='owner', hashed_password=HASH))
            db.add(models.Pollera(codigo='34TM', nombre='Pollera Andina', descripcion='Bordado floral.',
                                 talla='M', precio_base=100, rebaja=80, incluye_sombrero=True, incluye_manta=False))
            db.commit()
        self.client = TestClient(main.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.voice = patch.object(main, 'generate_audio', AsyncMock(return_value=None))
        self.voice.start()
        self.addCleanup(self.voice.stop)
        self.selection = patch.object(assistant, 'query_ollama', AsyncMock(return_value=None))
        self.selection.start()
        self.addCleanup(self.selection.stop)
        self.data = dict(codigo='NEW', nombre='Nueva', descripcion='Descripción', talla='M',
                         precio_base='120.50', rebaja='0')

    def login(self):
        result = self.client.post('/api/admin/login', data={'username': 'owner', 'password': PASSWORD})
        self.assertEqual(result.status_code, 200, result.text)
        return {'X-CSRF-Token': self.client.cookies.get(auth.CSRF_COOKIE)}

    def test_catalog_health_and_missing_product(self):
        self.assertEqual(self.client.get('/api/health').status_code, 200)
        product = self.client.get('/api/polleras/34tm').json()
        self.assertEqual(product['precio_final'], 80)
        self.assertEqual(product['precio_base'], 100)
        self.assertEqual(self.client.get('/api/polleras/NOT_FOUND').status_code, 404)

    def test_public_pages_have_no_camera_stream_or_virtual_fitting(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        for fragment in ('/api/video_feed', 'tryOn', 'cameraFeed', 'tensorflow'):
            self.assertNotIn(fragment, response.text)
        self.assertEqual(self.client.get('/static/img/default.svg').status_code, 200)

    def test_anonymous_mutation_camera_and_dashboard_are_protected(self):
        self.assertEqual(self.client.post('/api/admin/polleras', data=self.data).status_code, 401)
        self.assertEqual(self.client.get('/api/video_feed').status_code, 401)
        self.assertEqual(self.client.post('/api/vision/start').status_code, 401)
        self.assertEqual(self.client.get('/admin/dashboard', follow_redirects=False).status_code, 303)

    def test_cookie_login_csrf_logout(self):
        headers = self.login()
        cookies = self.client.cookies
        self.assertTrue(cookies.get(auth.COOKIE_NAME))
        result = self.client.get('/api/admin/me')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.post('/api/admin/polleras', data=self.data).status_code, 403)
        self.assertEqual(self.client.post('/api/admin/polleras', data=self.data, headers=headers).status_code, 201)
        self.assertEqual(self.client.post('/api/admin/logout', headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/api/admin/me').status_code, 401)

    def test_session_cookie_flags(self):
        result = self.client.post('/api/admin/login', data={'username': 'owner', 'password': PASSWORD})
        session_cookie = next(c for c in result.headers.get_list('set-cookie') if c.startswith(auth.COOKIE_NAME))
        self.assertIn('HttpOnly', session_cookie)
        self.assertIn('SameSite=strict', session_cookie)

    def test_old_default_password_is_rejected(self):
        with database.SessionLocal() as db:
            db.add(models.AdminUser(username='admin', hashed_password=auth.pwd_context.hash('admin')))
            db.commit()
        self.assertEqual(self.client.post('/api/admin/login', data={'username':'admin','password':'admin'}).status_code, 401)

    def test_login_throttling(self):
        for _ in range(5):
            self.assertEqual(self.client.post('/api/admin/login', data={'username':'owner','password':'wrong'}).status_code, 401)
        self.assertEqual(self.client.post('/api/admin/login', data={'username':'owner','password':'wrong'}).status_code, 429)

    def test_invalid_prices_and_codes(self):
        headers = self.login()
        for updates in [{'precio_base':'-1'}, {'precio_base':'0'}, {'precio_base':'nan'},
                        {'precio_base':'1.001'}, {'rebaja':'121'}, {'rebaja':'-1'},
                        {'codigo':'../../bad'}, {'nombre':' '}, {'codigo':'x'*51}]:
            with self.subTest(updates=updates):
                result = self.client.post('/api/admin/polleras', data={**self.data, **updates}, headers=headers)
                self.assertEqual(result.status_code, 422, result.text)

    def test_duplicate_is_conflict_and_edit_updates_price(self):
        headers = self.login()
        result = self.client.post('/api/admin/polleras', data=self.data, headers=headers)
        self.assertEqual(result.status_code, 201)
        self.assertEqual(self.client.post('/api/admin/polleras', data=self.data, headers=headers).status_code, 409)
        result = self.client.put('/api/admin/polleras/'+str(result.json()['id']),
                                 data={**self.data,'rebaja':'99.99'},headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['precio_final'], 99.99)

    def test_invalid_image_rejected(self):
        headers = self.login()
        result = self.client.post('/api/admin/polleras', data=self.data, headers=headers,
                                  files={'imagen':('fake.jpg',b'<html>bad</html>','image/jpeg')})
        self.assertEqual(result.status_code, 422)

    def test_uploaded_filename_cannot_choose_destination(self):
        headers = self.login()
        buffer = io.BytesIO()
        Image.new('RGB',(12,12),'red').save(buffer,'PNG')
        result = self.client.post('/api/admin/polleras', data=self.data, headers=headers,
                                  files={'imagen':('../../../outside.html',buffer.getvalue(),'text/html')})
        self.assertEqual(result.status_code, 201, result.text)
        url = result.json()['imagen_url']
        self.assertRegex(url, r'^/media/[a-f0-9]{32}\.jpg$')
        self.assertTrue((config.UPLOAD_DIR / url.split('/')[-1]).is_file())
        self.assertFalse((TEST_ROOT/'outside.html').exists())
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'image/jpeg')

    def test_delete_pollera_and_cleanup_image(self):
        headers = self.login()
        buffer = io.BytesIO()
        Image.new('RGB', (10, 10), 'blue').save(buffer, 'JPEG')
        created = self.client.post('/api/admin/polleras', data={**self.data, 'codigo': 'DELTEST'},
                                   files={'imagen': ('del.jpg', buffer.getvalue(), 'image/jpeg')},
                                   headers=headers)
        self.assertEqual(created.status_code, 201)
        pid = created.json()['id']
        img_file = config.UPLOAD_DIR / created.json()['imagen_url'].split('/')[-1]
        self.assertTrue(img_file.is_file())

        # Logged-in client without CSRF token is rejected with 403
        self.assertEqual(self.client.delete(f'/api/admin/polleras/{pid}').status_code, 403)

        # Anonymous client without session cookie is rejected with 401
        with TestClient(main.app) as anon:
            self.assertEqual(anon.delete(f'/api/admin/polleras/{pid}').status_code, 401)

        # Admin with valid session and CSRF deletes successfully
        deleted = self.client.delete(f'/api/admin/polleras/{pid}', headers=headers)
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(img_file.is_file())
        self.assertEqual(self.client.get('/api/polleras/DELTEST').status_code, 404)

    def test_update_pollera_cleans_old_image(self):
        headers = self.login()
        buf1 = io.BytesIO()
        Image.new('RGB', (10, 10), 'red').save(buf1, 'JPEG')
        created = self.client.post('/api/admin/polleras', data={**self.data, 'codigo': 'IMGTEST'},
                                   files={'imagen': ('img1.jpg', buf1.getvalue(), 'image/jpeg')},
                                   headers=headers)
        pid = created.json()['id']
        old_file = config.UPLOAD_DIR / created.json()['imagen_url'].split('/')[-1]
        self.assertTrue(old_file.is_file())

        buf2 = io.BytesIO()
        Image.new('RGB', (10, 10), 'green').save(buf2, 'JPEG')
        updated = self.client.put(f'/api/admin/polleras/{pid}', data={**self.data, 'codigo': 'IMGTEST'},
                                  files={'imagen': ('img2.jpg', buf2.getvalue(), 'image/jpeg')},
                                  headers=headers)
        self.assertEqual(updated.status_code, 200)
        new_file = config.UPLOAD_DIR / updated.json()['imagen_url'].split('/')[-1]
        self.assertTrue(new_file.is_file())
        self.assertFalse(old_file.is_file())

    def test_body_limit_and_origin_protection(self):
        self.assertEqual(self.client.post('/api/admin/login', content=b'x',headers={'Content-Length':str(config.MAX_BODY_BYTES+1)}).status_code, 413)
        self.assertEqual(self.client.post('/api/admin/login', data={},headers={'Origin':'https://foreign.example'}).status_code, 403)
        self.assertEqual(self.client.get('/',headers={'Host':'foreign.example'}).status_code, 400)

    def test_empty_chat_and_pagination_rejected(self):
        for message in ['', '  ', 'x'*1001]:
            self.assertEqual(self.client.post('/api/chat', json={'message':message}).status_code, 422)
        for query in ['limit=-1','skip=-1','limit=201','limit=0']:
            self.assertEqual(self.client.get('/api/polleras/?'+query).status_code, 422)

    def test_catalog_text_survives_voice_failure_without_loading_camera(self):
        with patch.object(main, 'get_engine', side_effect=AssertionError('Camera must not be loaded')):
            response = self.client.post('/api/chat', json={'message':'34TM'})
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertIsNone(data['audio_url'])
            self.assertIn('80.00 soles',data['text'])
            self.assertEqual(data['pollera']['codigo'],'34TM')
            self.assertEqual(self.client.get('/api/audio/detalles/34TM').status_code,200)
        assistant.query_ollama.assert_not_awaited()

    def test_unknown_code_does_not_select_another_product(self):
        response = self.client.post('/api/chat',json={'message':'ZZ999'})
        self.assertEqual(response.status_code,200)
        self.assertIsNone(response.json()['pollera'])
        assistant.query_ollama.assert_not_awaited()

    def test_current_product_context_uses_catalog(self):
        response = self.client.post('/api/chat',json={'message':'¿qué incluye esta?', 'codigo_actual':'34TM'})
        self.assertEqual(response.json()['pollera']['codigo'],'34TM')
        self.assertIn('sombrero', response.json()['text'])

    def test_model_cannot_set_prices_or_invent_products(self):
        assistant.query_ollama.return_value = schemas.ProductSelection.model_validate({
            'codigo_mostrar':'34TM','respuesta_hablada':'Cuesta 1 sol. Solo por hoy.'
        })
        response = self.client.post('/api/chat',json={'message':'Recomiéndame algo'})
        self.assertIn('80.00 soles',response.json()['text'])
        self.assertNotIn('Solo por hoy',response.json()['text'])
        assistant.query_ollama.return_value = schemas.ProductSelection(codigo_mostrar='INVENTADO')
        self.assertIsNone(self.client.post('/api/chat',json={'message':'Recomiéndame algo'}).json()['pollera'])

    def test_legacy_invalid_discount_uses_base_price_everywhere(self):
        with database.SessionLocal() as db:
            product = db.query(models.Pollera).first()
            product.rebaja = 150
            db.commit()
        self.assertEqual(self.client.get('/api/polleras/34TM').json()['precio_final'],100)
        self.assertIn('100.00 soles',self.client.get('/api/audio/detalles/34TM').json()['text'])

    def test_details_not_truncated_by_catalog_window(self):
        with database.SessionLocal() as db:
            for n in range(201):
                db.add(models.Pollera(codigo=f'A{n:04}',nombre='Item',descripcion='Detalle',talla='S',precio_base=20,rebaja=0))
            db.commit()
        self.assertEqual(self.client.get('/api/audio/detalles/A0200').status_code, 200)
        response = self.client.post('/api/chat', json={'message': 'A0200'})
        self.assertEqual(response.json()['pollera']['codigo'], 'A0200')

    def test_camera_monitor_with_session(self):
        self.login()
        fake = MagicMock()
        fake.status.return_value = {'state':'running','error':None}
        fake.generate_frames.return_value = iter([b'--frame\r\n\r\nsample\r\n'])
        with patch.object(main,'get_engine',return_value=fake):
            response = self.client.get('/api/video_feed')
        self.assertEqual(response.status_code,200)

    def test_no_default_admin_created_in_lifespan(self):
        with database.SessionLocal() as db:
            db.query(models.AdminUser).delete()
            db.commit()
        with TestClient(main.app) as client:
            self.assertEqual(client.get('/api/health').status_code,200)
        with database.SessionLocal() as db:
            self.assertEqual(db.query(models.AdminUser).count(),0)

    def test_conversation_endpoint(self):
        res1 = self.client.post('/api/conversacion', json={'codigo': '34TM', 'message': '¿esta manta cuántas salidas ya tiene?'})
        self.assertEqual(res1.status_code, 200)
        d1 = res1.json()
        self.assertIn('ese detalle no lo tengo registrado', d1['text'])
        self.assertIn('WhatsApp', d1['text'])
        self.assertEqual(d1['action'], 'answer')

        res2 = self.client.post('/api/conversacion', json={'codigo': '34TM', 'message': '¿y este no lo tiene en otro color?'})
        self.assertEqual(res2.status_code, 200)
        d2 = res2.json()
        self.assertIn('inventario no veo', d2['text'].lower())

        res3 = self.client.post('/api/conversacion', json={'codigo': '34TM', 'message': '¿su precio es así?'})
        self.assertEqual(res3.status_code, 200)
        d3 = res3.json()
        self.assertIn('80.00 soles', d3['text'])
        self.assertIn('WhatsApp', d3['text'])

        res4 = self.client.post('/api/conversacion', json={'codigo': '34TM', 'message': 'muchas gracias eso es todo chau'})
        self.assertEqual(res4.status_code, 200)
        d4 = res4.json()
        self.assertEqual(d4['action'], 'farewell')
        self.assertEqual(d4['mood'], 'despedida')
        self.assertIn('Gracias a ti', d4['text'])

        self.assertEqual(self.client.post('/api/conversacion', json={'codigo': 'NOEXISTE', 'message': 'hola'}).status_code, 404)


class AsyncServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_ollama_wait_does_not_block_other_tasks(self):
        original_client = httpx.AsyncClient
        started = asyncio.Event()

        async def handler(request):
            started.set()
            await asyncio.sleep(0.08)
            return httpx.Response(200,json={'response':'{"codigo_mostrar":"34TM"}'})

        transport = httpx.MockTransport(handler)
        with patch.object(assistant.httpx, 'AsyncClient',side_effect=lambda **kw: original_client(transport=transport,**kw)):
            task = asyncio.create_task(assistant.query_ollama('select'))
            await started.wait()
            await asyncio.sleep(0.005)
            self.assertFalse(task.done(), 'Other tasks must run while Ollama waits.')
            self.assertEqual((await task).codigo_mostrar,'34TM')

    async def test_tts_outage_returns_none_and_cleans_partial_file(self):
        with patch.object(tts_engine.config,'PIPER_MODEL',TEST_ROOT/'missing.onnx'), \
             patch.object(tts_engine.edge_tts,'Communicate',side_effect=RuntimeError('offline')):
            self.assertIsNone(await tts_engine.generate_audio('offline fixture'))
        self.assertEqual(list(config.AUDIO_DIR.glob('*.tmp')),[])

    async def test_tts_cache_reuses_audio(self):
        async def save(path):
            Path(path).write_bytes(b'test-audio')
        communicate = MagicMock()
        communicate.save = AsyncMock(side_effect=save)
        with patch.object(tts_engine.config,'PIPER_MODEL',TEST_ROOT/'missing.onnx'), \
             patch.object(tts_engine.edge_tts,'Communicate',return_value=communicate):
            one = await tts_engine.generate_audio('cached fixture')
            two = await tts_engine.generate_audio('cached fixture')
        self.assertEqual(one,two)
        self.assertTrue(one.startswith('/audio/'))
        communicate.save.assert_awaited_once()

    async def test_audio_cleanup_only_removes_expired_cache(self):
        old = config.AUDIO_DIR/'expired.mp3'
        fresh = config.AUDIO_DIR/'fresh.mp3'
        unrelated = config.AUDIO_DIR/'keep.txt'
        config.AUDIO_DIR.mkdir(exist_ok=True,parents=True)
        for file in [old,fresh,unrelated]:
            file.write_bytes(b'fixture')
        os.utime(old,(0,0))
        os.utime(unrelated,(0,0))
        tts_engine.cleanup_audio()
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())
        self.assertTrue(unrelated.exists())

    async def test_personality_speech_and_prosody_segments(self):
        p = schemas.Pollera(id=1, codigo='TST', nombre='Pollera Test', descripcion='Bordados',
                            talla='M', precio_base=100, rebaja=80, incluye_sombrero=True, incluye_manta=False)
        speech = personality.presentation(p)
        self.assertTrue(len(speech.segments) >= 3)
        self.assertTrue(speech.main_mood in personality.EMOTIONS)
        segments = speech.voice_segments()
        self.assertTrue(all('rate' in prosody for _, prosody in segments))
        timeline = speech.timeline()
        self.assertEqual(len(timeline), len(speech.segments))

        # Test multi-segment synthesis
        async def fake_stream():
            yield {'type': 'audio', 'data': b'part'}

        communicate = MagicMock()
        communicate.stream = fake_stream
        with patch.object(tts_engine.config, 'PIPER_MODEL', TEST_ROOT / 'missing.onnx'), \
             patch.object(tts_engine.edge_tts, 'Communicate', return_value=communicate):
            url = await tts_engine.generate_audio(speech)
            self.assertIsNotNone(url)
            self.assertTrue(url.startswith('/audio/'))


class CameraTests(unittest.TestCase):
    def test_engine_is_lazy_and_event_is_consumed_once(self):
        engine = YoloEngine()
        self.assertEqual(engine.status()['state'],'stopped')
        self.assertIsNone(engine.thread)
        engine.is_interested = True
        self.assertTrue(engine.check_interest())
        self.assertFalse(engine.check_interest())
        engine.reset_lock()
        self.assertGreater(engine.lock_until,time.monotonic())
        engine.stop()
        self.assertEqual(engine.status()['state'],'stopped')


class MigrationTests(unittest.TestCase):
    def test_old_catalog_gets_discount_column_without_losing_rows(self):
        legacy = create_engine(f"sqlite:///{TEST_ROOT / 'legacy.db'}")
        try:
            with legacy.begin() as connection:
                connection.execute(text('CREATE TABLE polleras (id INTEGER PRIMARY KEY, codigo VARCHAR, nombre VARCHAR, descripcion VARCHAR, talla VARCHAR, precio_base FLOAT, incluye_sombrero BOOLEAN, incluye_manta BOOLEAN, imagen_url VARCHAR)'))
                connection.execute(text("INSERT INTO polleras (id,codigo,nombre,descripcion,talla,precio_base,incluye_sombrero,incluye_manta) VALUES (1,'ORIGINAL','Prenda','Detalle','M',100,0,0)"))
            with patch.object(database, 'engine', legacy):
                database.init_schema()
                database.init_schema()  # Migration is safe to run again.
            self.assertIn('rebaja', {column['name'] for column in inspect(legacy).get_columns('polleras')})
            with legacy.connect() as connection:
                self.assertEqual(connection.execute(text('SELECT codigo, precio_base, rebaja FROM polleras')).one(), ('ORIGINAL',100,0))
        finally:
            legacy.dispose()


class MejorasTests(ApiTests):
    def _create_img_bytes(self, color='red'):
        buf = io.BytesIO()
        Image.new('RGB', (10, 10), color).save(buf, 'JPEG')
        return buf.getvalue()

    def test_registro_una_dos_tres_fotografias(self):
        headers = self.login()
        img1 = self._create_img_bytes('red')
        img2 = self._create_img_bytes('green')
        img3 = self._create_img_bytes('blue')

        # 1 foto
        r1 = self.client.post('/api/admin/polleras', data={**self.data, 'codigo': 'FOTO1'},
                              files={'imagen': ('f1.jpg', img1, 'image/jpeg')}, headers=headers)
        self.assertEqual(r1.status_code, 201)
        j1 = r1.json()
        self.assertIsNotNone(j1['imagen_url'])
        self.assertIsNone(j1['imagen_url_2'])
        self.assertIsNone(j1['imagen_url_3'])
        self.assertEqual(len(j1['imagenes']), 1)

        # 2 fotos
        r2 = self.client.post('/api/admin/polleras', data={**self.data, 'codigo': 'FOTO2'},
                              files={'imagen': ('f1.jpg', img1, 'image/jpeg'),
                                     'imagen_2': ('f2.jpg', img2, 'image/jpeg')}, headers=headers)
        self.assertEqual(r2.status_code, 201)
        j2 = r2.json()
        self.assertIsNotNone(j2['imagen_url'])
        self.assertIsNotNone(j2['imagen_url_2'])
        self.assertIsNone(j2['imagen_url_3'])
        self.assertEqual(len(j2['imagenes']), 2)

        # 3 fotos
        r3 = self.client.post('/api/admin/polleras', data={**self.data, 'codigo': 'FOTO3'},
                              files={'imagen': ('f1.jpg', img1, 'image/jpeg'),
                                     'imagen_2': ('f2.jpg', img2, 'image/jpeg'),
                                     'imagen_3': ('f3.jpg', img3, 'image/jpeg')}, headers=headers)
        self.assertEqual(r3.status_code, 201)
        j3 = r3.json()
        self.assertIsNotNone(j3['imagen_url'])
        self.assertIsNotNone(j3['imagen_url_2'])
        self.assertIsNotNone(j3['imagen_url_3'])
        self.assertEqual(len(j3['imagenes']), 3)

    def test_rechazo_de_cuarta_fotografia(self):
        headers = self.login()
        img = self._create_img_bytes('yellow')
        res = self.client.post('/api/admin/polleras', data={**self.data, 'codigo': 'FOTO4'},
                               files={'imagen': ('f1.jpg', img, 'image/jpeg'),
                                      'imagen_2': ('f2.jpg', img, 'image/jpeg'),
                                      'imagen_3': ('f3.jpg', img, 'image/jpeg'),
                                      'imagen_4': ('f4.jpg', img, 'image/jpeg')}, headers=headers)
        self.assertEqual(res.status_code, 422)
        self.assertIn('tres fotografías', res.json()['detail'])

    def test_conservacion_de_fotografias_existentes_al_editar(self):
        headers = self.login()
        img1 = self._create_img_bytes('red')
        img2 = self._create_img_bytes('green')
        created = self.client.post('/api/admin/polleras', data={**self.data, 'codigo': 'KEEPIMG'},
                                   files={'imagen': ('f1.jpg', img1, 'image/jpeg'),
                                          'imagen_2': ('f2.jpg', img2, 'image/jpeg')}, headers=headers)
        self.assertEqual(created.status_code, 201)
        j_c = created.json()
        pid = j_c['id']

        # Edit price only, sending no files and no delete flags
        updated = self.client.put(f'/api/admin/polleras/{pid}', data={**self.data, 'codigo': 'KEEPIMG', 'precio_base': '250.00'},
                                  headers=headers)
        self.assertEqual(updated.status_code, 200)
        j_u = updated.json()
        self.assertEqual(j_u['imagen_url'], j_c['imagen_url'])
        self.assertEqual(j_u['imagen_url_2'], j_c['imagen_url_2'])
        self.assertEqual(j_u['precio_base'], 250.0)

    def test_edicion_y_eliminacion_individual_de_imagenes(self):
        headers = self.login()
        img1 = self._create_img_bytes('red')
        img2 = self._create_img_bytes('green')
        img3 = self._create_img_bytes('blue')
        created = self.client.post('/api/admin/polleras', data={**self.data, 'codigo': 'INDIV'},
                                   files={'imagen': ('f1.jpg', img1, 'image/jpeg'),
                                          'imagen_2': ('f2.jpg', img2, 'image/jpeg'),
                                          'imagen_3': ('f3.jpg', img3, 'image/jpeg')}, headers=headers)
        pid = created.json()['id']
        url1 = created.json()['imagen_url']
        url2 = created.json()['imagen_url_2']
        url3 = created.json()['imagen_url_3']

        file2 = config.UPLOAD_DIR / url2.split('/')[-1]
        self.assertTrue(file2.is_file())

        # Delete image 2 individually
        res = self.client.put(f'/api/admin/polleras/{pid}',
                              data={**self.data, 'codigo': 'INDIV', 'eliminar_imagen_2': 'true'},
                              headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(file2.is_file())  # Deleted from disk
        j = res.json()
        self.assertEqual(len(j['imagenes']), 2)
        # slot 1 preserved
        self.assertEqual(j['imagen_url'], url1)

    def test_flujo_estados_alquiler_y_fechas(self):
        headers = self.login()
        # Verify initial state is DISPONIBLE
        p = self.client.get('/api/polleras/34TM').json()
        self.assertEqual(p['estado'], 'DISPONIBLE')

        # 5. Marcar como alquilada con fechas
        res = self.client.post(f"/api/admin/polleras/{p['id']}/alquilar",
                               data={'fecha_alquiler': '2026-10-15', 'fecha_devolucion_estimada': '2026-10-22'},
                               headers=headers)
        self.assertEqual(res.status_code, 200)
        j = res.json()
        self.assertEqual(j['estado'], 'ALQUILADA')
        self.assertEqual(j['fecha_alquiler'], '2026-10-15')
        self.assertEqual(j['fecha_devolucion_estimada'], '2026-10-22')

        # 8. Persistencia de estados
        p_check = self.client.get('/api/polleras/34TM').json()
        self.assertEqual(p_check['estado'], 'ALQUILADA')

        # 7. Cambio de alquilada a disponible
        res_dev = self.client.post(f"/api/admin/polleras/{p['id']}/devolver", headers=headers)
        self.assertEqual(res_dev.status_code, 200)
        self.assertEqual(res_dev.json()['estado'], 'DISPONIBLE')

    def test_exclusion_de_polleras_alquiladas_en_ofertas(self):
        headers = self.login()
        self.client.post('/api/admin/polleras', data={**self.data, 'codigo': 'DISPO'}, headers=headers)
        
        # Mark 34TM as ALQUILADA
        p1 = self.client.get('/api/polleras/34TM').json()
        self.client.post(f"/api/admin/polleras/{p1['id']}/alquilar", data={}, headers=headers)

        # /api/audio/ofertas should never pick 34TM
        for _ in range(5):
            res = self.client.get('/api/audio/ofertas')
            self.assertEqual(res.status_code, 200)
            self.assertNotIn('34TM', res.json()['text'])

    def test_consulta_especifica_pollera_alquilada_con_alternativas(self):
        headers = self.login()
        # Create an available alternative (e.g. blue pollera)
        self.client.post('/api/admin/polleras',
                         data={'codigo': 'AZUL01', 'nombre': 'Pollera Azul Cielo',
                               'descripcion': 'Bordados azules.', 'talla': 'M',
                               'precio_base': '110.00', 'rebaja': '0'},
                         headers=headers)
        
        # Mark 34TM as ALQUILADA
        p1 = self.client.get('/api/polleras/34TM').json()
        from datetime import date, timedelta
        dev_date = (date.today() + timedelta(days=5)).isoformat()
        self.client.post(f"/api/admin/polleras/{p1['id']}/alquilar",
                         data={'fecha_alquiler': date.today().isoformat(), 'fecha_devolucion_estimada': dev_date},
                         headers=headers)

        # Ask specifically for the rented pollera
        chat_res = self.client.post('/api/chat', json={'message': 'Tienes la pollera 34TM?'})
        self.assertEqual(chat_res.status_code, 200)
        resp = chat_res.json()
        self.assertIn('alquilada', resp['text'].lower())
        self.assertIn('aproximadamente', resp['text'].lower())
        self.assertIn('Pollera Azul Cielo', resp['text'])

        # Also test /api/conversacion when discussing another product and asking for 34TM
        conv_res = self.client.post('/api/conversacion', json={'message': 'Y la pollera 34TM?', 'codigo': 'AZUL01'})
        self.assertEqual(conv_res.status_code, 200)
        c_resp = conv_res.json()
        self.assertIn('alquilada', c_resp['text'].lower())


    def test_calculo_dias_restantes_y_vencidas(self):
        from datetime import date
        today = date(2026, 10, 15)
        
        # Future return (5 days)
        prod_future = models.Pollera(codigo='P1', nombre='Pollera Fiesta', descripcion='Linda', talla='M', precio_base=100, rebaja=0,
                                     estado='ALQUILADA', fecha_devolucion_estimada=date(2026, 10, 20))
        speech, alt = personality.rented_presentation(prod_future, [], today=today)
        self.assertIn('5 días aproximadamente', speech.text)

        # Tomorrow return (1 day)
        prod_tomorrow = models.Pollera(codigo='P1', nombre='Pollera Fiesta', descripcion='Linda', talla='M', precio_base=100, rebaja=0,
                                       estado='ALQUILADA', fecha_devolucion_estimada=date(2026, 10, 16))
        speech_t, _ = personality.rented_presentation(prod_tomorrow, [], today=today)
        self.assertIn('mañana aproximadamente', speech_t.text)

        # Overdue return
        prod_overdue = models.Pollera(codigo='P1', nombre='Pollera Fiesta', descripcion='Linda', talla='M', precio_base=100, rebaja=0,
                                      estado='ALQUILADA', fecha_devolucion_estimada=date(2026, 10, 10))
        speech_o, _ = personality.rented_presentation(prod_overdue, [], today=today)
        self.assertIn('ya venció, pero aún no se ha confirmado su devolución', speech_o.text)

        # No estimated date
        prod_no_date = models.Pollera(codigo='P1', nombre='Pollera Fiesta', descripcion='Linda', talla='M', precio_base=100, rebaja=0,
                                      estado='ALQUILADA', fecha_devolucion_estimada=None)
        speech_n, _ = personality.rented_presentation(prod_no_date, [], today=today)
        self.assertIn('no tenemos una fecha estimada de retorno confirmada', speech_n.text)

    def test_seguridad_rutas_alquiler(self):
        self.assertEqual(self.client.post('/api/admin/polleras/1/alquilar').status_code, 401)
        self.assertEqual(self.client.post('/api/admin/polleras/1/devolver').status_code, 401)
        self.login()
        self.assertEqual(self.client.post('/api/admin/polleras/1/alquilar').status_code, 403)
        self.assertEqual(self.client.post('/api/admin/polleras/1/devolver').status_code, 403)

    def test_normalizacion_de_expresiones_vocales(self):
        n1 = tts_engine.normalize_for_tts("Mmm... déjame pensar en qué pollera mostrarte")
        self.assertTrue(n1.startswith("A ver... déjame pensar"))
        self.assertNotIn("Mmm", n1)
        self.assertNotIn("mmm", n1)

        n2 = tts_engine.normalize_for_tts("mmm, qué bonita pollera")
        self.assertTrue(n2.startswith("A ver... qué bonita"))

        n3 = tts_engine.normalize_for_tts("Mmm... a ver", provider='piper')
        self.assertTrue(n3.startswith("A ver..."))

        n4 = tts_engine.normalize_for_tts("medida de 50 mm de ancho")
        self.assertIn("50 mm", n4)

    def test_migracion_agrega_columnas_fotos_y_alquiler(self):
        legacy = create_engine(f"sqlite:///{TEST_ROOT / 'legacy2.db'}")
        try:
            with legacy.begin() as conn:
                conn.execute(text('CREATE TABLE polleras (id INTEGER PRIMARY KEY, codigo VARCHAR, nombre VARCHAR, descripcion VARCHAR, talla VARCHAR, precio_base FLOAT, rebaja FLOAT, incluye_sombrero BOOLEAN, incluye_manta BOOLEAN, imagen_url VARCHAR)'))
                conn.execute(text("INSERT INTO polleras (id,codigo,nombre,descripcion,talla,precio_base,rebaja,incluye_sombrero,incluye_manta) VALUES (1,'LEGACY','Tradicional','Desc','S',120,0,0,0)"))
            with patch.object(database, 'engine', legacy):
                database.init_schema()
            cols = {c['name'] for c in inspect(legacy).get_columns('polleras')}
            for expected in ('imagen_url_2', 'imagen_url_3', 'estado', 'fecha_alquiler', 'fecha_devolucion_estimada'):
                self.assertIn(expected, cols)
            with legacy.connect() as conn:
                row = conn.execute(text("SELECT codigo, estado FROM polleras WHERE codigo='LEGACY'")).one()
                self.assertEqual(row, ('LEGACY', 'DISPONIBLE'))
        finally:
            legacy.dispose()


class AutonomiaV1Tests(ApiTests):
    def test_config_autonomia(self):
        resp = self.client.get('/api/config')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('autonomy', data)
        self.assertTrue(data['autonomy']['enabled'])
        self.assertGreaterEqual(data['autonomy']['post_tts_pause_ms'], 300)
        self.assertGreaterEqual(data['autonomy']['farewell_cooldown_seconds'], 15)

    def test_vision_cooldown_endpoint(self):
        self.assertEqual(self.client.post('/api/vision/cooldown?seconds=25').status_code, 401)
        headers = self.login()
        resp = self.client.post('/api/vision/cooldown?seconds=25', headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'cooldown_set')
        self.assertGreater(get_engine().lock_until, time.monotonic() + 15)

    def test_audio_saludo_y_recordatorio(self):
        r_saludo = self.client.get('/api/audio/saludo')
        self.assertEqual(r_saludo.status_code, 200)
        d_saludo = r_saludo.json()
        self.assertEqual(d_saludo['action'], 'greeting')
        self.assertIn('caser', d_saludo['text'].lower())

        r_rec = self.client.get('/api/audio/recordatorio')
        self.assertEqual(r_rec.status_code, 200)
        d_rec = r_rec.json()
        self.assertEqual(d_rec['action'], 'reminder')
        self.assertIn('buscando', d_rec['text'].lower())

    def test_multi_turn_session_context(self):
        # Turn 1: Search for 34TM
        r1 = self.client.post('/api/chat', json={'message': 'muestrame la 34TM'})
        self.assertEqual(r1.status_code, 200)
        d1 = r1.json()
        self.assertEqual(d1['action'], 'show_pollera')
        self.assertEqual(d1['pollera']['codigo'], '34TM')
        ctx = d1['context']
        self.assertEqual(ctx['current_code'], '34TM')
        self.assertIn('34TM', ctx['viewed_codes'])

        # Turn 2: Query price without naming the pollera again (memory test)
        r2 = self.client.post('/api/conversacion', json={
            'message': '¿cuánto cuesta?',
            'codigo': '34TM',
            'context': ctx
        })
        self.assertEqual(r2.status_code, 200)
        d2 = r2.json()
        self.assertIn('80.00 soles', d2['text'])

        # Turn 3: Query size availability
        r3 = self.client.post('/api/conversacion', json={
            'message': '¿tienes en talla L?',
            'codigo': '34TM',
            'context': d2['context']
        })
        self.assertEqual(r3.status_code, 200)
        d3 = r3.json()
        self.assertIn('talla', d3['text'].lower())

        # Turn 4: Farewell
        r4 = self.client.post('/api/conversacion', json={
            'message': 'No, muchas gracias chau',
            'codigo': '34TM',
            'context': d3['context']
        })
        self.assertEqual(r4.status_code, 200)
        d4 = r4.json()
        self.assertEqual(d4['action'], 'farewell')
        self.assertIn('estare si necesitas algo', assistant.normalize(d4['text']))

    def test_saludo_does_not_return_product(self):
        resp = self.client.get('/api/audio/saludo')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['action'], 'greeting')
        self.assertIsNone(data.get('pollera'))
        self.assertIsNone(data.get('imagen_url'))

    def test_chat_greeting_and_general_inquiry_do_not_show_product(self):
        # Greeting should answer warmly without opening a product card
        r_hola = self.client.post('/api/chat', json={'message': 'hola buenas tardes'})
        self.assertEqual(r_hola.status_code, 200)
        d_hola = r_hola.json()
        self.assertEqual(d_hola['action'], 'answer')
        self.assertIsNone(d_hola.get('pollera'))

        # General inquiry should give an overview without selecting arbitrary product
        r_gen = self.client.post('/api/chat', json={'message': '¿qué polleras tienes?'})
        self.assertEqual(r_gen.status_code, 200)
        d_gen = r_gen.json()
        self.assertEqual(d_gen['action'], 'answer')
        self.assertIsNone(d_gen.get('pollera'))
        self.assertIn('polleras', d_gen['text'].lower())

    def test_personality_vocative_rotation_avoids_repetition(self):
        ctx = schemas.ConversationContext()
        vocatives_seen = []
        for _ in range(25):
            voc = personality.get_vocative(ctx)
            vocatives_seen.append(voc)

        # Ensure empty vocative is supported (no appellative in every turn)
        self.assertIn('', vocatives_seen)
        # Ensure variety of vocatives
        non_empty = [v for v in vocatives_seen if v]
        self.assertGreaterEqual(len(set(non_empty)), 3)
        # Ensure consecutive vocatives are never identical when non-empty
        for i in range(len(non_empty) - 1):
            self.assertNotEqual(non_empty[i], non_empty[i + 1])

    def test_celebration_advice_navidad_and_cumpleanos(self):
        # Navidad advice
        r_nav = self.client.post('/api/chat', json={'message': 'Busco una pollera para Navidad'})
        self.assertEqual(r_nav.status_code, 200)
        d_nav = r_nav.json()
        self.assertEqual(d_nav['action'], 'answer')
        self.assertIsNone(d_nav.get('pollera'))
        self.assertIn('navidad', d_nav['text'].lower())
        self.assertEqual(d_nav['context']['celebration_reason'], 'Navidad')

        # Cumpleaños advice
        r_cum = self.client.post('/api/chat', json={'message': 'Quiero una para un cumpleaños'})
        self.assertEqual(r_cum.status_code, 200)
        d_cum = r_cum.json()
        self.assertEqual(d_cum['action'], 'answer')
        self.assertIsNone(d_cum.get('pollera'))
        self.assertIn('especial', d_cum['text'].lower())
        self.assertEqual(d_cum['context']['celebration_reason'], 'cumpleaños')

    def test_price_comments_humor_and_empathy(self):
        # Está barata -> witty response
        r_barata = self.client.post('/api/chat', json={'message': 'Está muy barata'})
        self.assertEqual(r_barata.status_code, 200)
        d_barata = r_barata.json()
        self.assertEqual(d_barata['action'], 'answer')
        self.assertIn('todavía no te he mostrado', d_barata['text'].lower())
        self.assertEqual(d_barata['context']['presupuesto'], 'económico')

        # Está cara -> empathetic response
        r_cara = self.client.post('/api/chat', json={'message': 'Está muy cara'})
        self.assertEqual(r_cara.status_code, 200)
        d_cara = r_cara.json()
        self.assertEqual(d_cara['action'], 'answer')
        self.assertIn('presupuesto', d_cara['text'].lower())
        self.assertEqual(d_cara['context']['presupuesto'], 'ajustado')

    def test_casual_chit_chat_and_jokes(self):
        # Joke inquiry
        r_joke = self.client.post('/api/chat', json={'message': 'Cuéntame un chiste'})
        self.assertEqual(r_joke.status_code, 200)
        d_joke = r_joke.json()
        self.assertEqual(d_joke['action'], 'answer')
        self.assertIsNone(d_joke.get('pollera'))
        self.assertIn('pollera', d_joke['text'].lower())

        # Weather / friendly comment
        r_cold = self.client.post('/api/chat', json={'message': 'Qué frío hace hoy'})
        self.assertEqual(r_cold.status_code, 200)
        d_cold = r_cold.json()
        self.assertEqual(d_cold['action'], 'answer')
        self.assertIn('zapateando', d_cold['text'].lower())

    def test_multi_turn_coherence_with_celebration_and_memory(self):
        # Turn 1: Customer asks about wedding occasion
        r1 = self.client.post('/api/chat', json={'message': 'Busco algo para una boda'})
        self.assertEqual(r1.status_code, 200)
        ctx1 = r1.json()['context']
        self.assertEqual(ctx1['celebration_reason'], 'boda')

        # Turn 2: Customer asks to see pollera 34TM
        r2 = self.client.post('/api/chat', json={'message': '34TM', 'context': ctx1})
        self.assertEqual(r2.status_code, 200)
        d2 = r2.json()
        self.assertEqual(d2['action'], 'show_pollera')
        self.assertEqual(d2['pollera']['codigo'], '34TM')
        ctx2 = d2['context']
        self.assertEqual(ctx2['current_code'], '34TM')
        self.assertEqual(ctx2['celebration_reason'], 'boda')

        # Turn 3: Customer asks what is included in this pollera
        r3 = self.client.post('/api/conversacion', json={
            'codigo': '34TM',
            'message': '¿qué incluye?',
            'context': ctx2
        })
        self.assertEqual(r3.status_code, 200)
        d3 = r3.json()
        self.assertIn('sombrero', d3['text'].lower())
        ctx3 = d3['context']
        self.assertEqual(ctx3['celebration_reason'], 'boda')

        # Turn 4: Customer comments that it is cheap
        r4 = self.client.post('/api/conversacion', json={
            'codigo': '34TM',
            'message': 'está barata',
            'context': ctx3
        })
        self.assertEqual(r4.status_code, 200)
        d4 = r4.json()
        self.assertIn('todavía no te he mostrado', d4['text'].lower())
        ctx4 = d4['context']
        self.assertEqual(ctx4['celebration_reason'], 'boda')
        self.assertEqual(ctx4['presupuesto'], 'económico')

    def test_occasion_followup_and_presentation(self):
        # 1. Customer expresses occasion from hero screen: "lo quería para un cumpleaños"
        r1 = self.client.post('/api/chat', json={'message': 'lo quería para un cumpleaños'})
        self.assertEqual(r1.status_code, 200)
        d1 = r1.json()
        self.assertEqual(d1['action'], 'show_pollera')
        self.assertIsNotNone(d1['pollera'])
        self.assertIn('cumpleaños', d1['text'].lower())
        self.assertEqual(d1['context']['celebration_reason'], 'cumpleaños')

        # 2. While in product view, customer asks about another occasion: "y para Halloween?"
        r2 = self.client.post('/api/conversacion', json={
            'codigo': d1['pollera']['codigo'],
            'message': '¿y para Halloween qué tienes?',
            'context': d1['context']
        })
        self.assertEqual(r2.status_code, 200)
        d2 = r2.json()
        # Does NOT kick customer out with farewell, responds or presents pollera
        self.assertIn(d2['action'], ('show_pollera', 'answer'))
        self.assertIn('halloween', d2['text'].lower())
        self.assertEqual(d2['context']['celebration_reason'], 'Halloween')


