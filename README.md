# IAPolleras

Asistente para consultar polleras por código, texto o voz, mostrar precios del catálogo y contactar a la tienda por WhatsApp. El probador virtual fue retirado. La cámara se utiliza exclusivamente para detectar personas y manos; su video solo está disponible para administradores.

## Instalación y arranque (Windows / Python 3.11)

Desde la raíz del proyecto:

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Solo si usarás cámara y gestos:
.\.venv\Scripts\python.exe -m pip install -r requirements-vision.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m app.manage init-db
.\.venv\Scripts\python.exe -m app.manage create-admin --username admin
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
~~~

También puedes utilizar el entorno existente con .\venv\Scripts\python.exe. El comando de administrador solicita la contraseña de forma oculta: no se guarda en el código ni en el historial de la terminal. Debe tener al menos 12 caracteres y como máximo 72 bytes en UTF-8.

Abre http://127.0.0.1:8000/ y /admin/login. **Ya no existe un acceso automático admin/admin.** Para cambiar la contraseña de un administrador existente:

~~~powershell
.\venv\Scripts\python.exe -m app.manage create-admin --username admin --reset
~~~

## Conservar el catálogo existente

**Configura DATABASE_URL antes del primer arranque si quieres seguir usando MySQL.** El código anterior apuntaba a iapollera en MySQL. Ahora, si no configuras una URL, se crea una base local independiente en data/iapolleras.db. No se importan ni reemplazan automáticamente los datos de MySQL o de sql_app.db.

- Para MySQL, configura la URL de un usuario dedicado con contraseña en .env. Codifica caracteres especiales de la contraseña para una URL. La base debe existir y MySQL estar iniciado.
- Para el SQLite antiguo, configura explícitamente su ruta absoluta siguiendo .env.example.
- init-db crea tablas faltantes y agrega rebaja si falta, sin borrar registros. Realiza un respaldo de una base existente antes de actualizarla.
- Las bases nuevas usan importes NUMERIC(12,2). SQLAlchemy no transforma automáticamente columnas existentes. Para convertir precios FLOAT heredados de MySQL, respalda la base y ejecuta python -m app.manage upgrade-prices. El comando se detiene si detecta precios inválidos. SQLite mantiene su esquema anterior y la aplicación normaliza los importes mediante Decimal.
- El script opcional populate_db.py agrega tres productos de demostración únicamente a un catálogo vacío. Las imágenes ausentes se sustituyen visualmente por una imagen local de respaldo.

## Uso

- Escribe un código o una pregunta. Si hay voz disponible, puedes mantener presionado el micrófono. El recuadro inferior con la transcripción está oculto; se mantienen la voz y la ficha del producto.
- El modelo selecciona productos existentes. Los nombres, importes, tallas, accesorios y descripciones se toman del catálogo; no genera afirmaciones sobre existencias, popularidad ni vencimiento de promociones.
- La consulta puede referirse al producto que se está mostrando. Para búsquedas generales se consideran hasta 200 productos; el inventario tiene paginación.
- El panel permite agregar y editar productos. Una imagen vacía al editar conserva la foto actual. Se aceptan JPG, PNG y WebP de hasta 5 MB y 20 megapíxeles; se recodifican y reciben un nombre generado por el servidor.
- En el equipo de la tienda, pulsa **Activar detección**. No se enciende la cámara al cargar la página. Para controlarla desde otro equipo se requiere una sesión administrativa.
- El administrador puede ver el monitor y detener la detección. Un solo hilo procesa los fotogramas para todos los clientes. No se guardan videos.
- Usa **Volver a buscar** o el micrófono para interrumpir la voz. Las respuestas antiguas no sustituyen una consulta posterior.

## Servicios y funcionamiento sin conexión

Ollama es opcional para búsquedas exactas, detalles y saludos sencillos; para consultas generales usa el modelo indicado en .env (llama3 por defecto). El servidor aplica tiempo de espera y un límite de dos generaciones simultáneas.

Piper funciona sin conexión cuando están instalados el ejecutable, el modelo ONNX y su configuración correspondiente. Si no está disponible, se intenta Edge TTS, que necesita internet. Una caída de voz conserva la ficha del producto; la transcripción inferior permanece oculta.

El reconocimiento de voz depende del navegador y sus permisos; puede requerir conexión. Las fuentes, iconos y generación de QR también usan servicios externos. El botón de WhatsApp permanece disponible aunque falle el QR. El número se configura en .env.

La caché nueva de audio está en data/audio, se limpia cada diez minutos y retiene hasta 24 horas. También reduce archivos antiguos cuando supera 256 entradas, preservando los de los últimos diez minutos. Los audios anteriores en app/static/audio se conservan y ya no se generan nuevos allí.

## Seguridad y despliegue

- Las sesiones del navegador utilizan cookies HttpOnly, SameSite=Strict y protección CSRF para operaciones administrativas. No se almacena el token en localStorage. Al abrir login o el panel se elimina el token antiguo si existe.
- En desarrollo se crea una clave aleatoria persistente en data/.session-key. En producción define PRODUCTION=true, COOKIE_SECURE=true, una SECRET_KEY aleatoria propia y HTTPS.
- Ajusta ALLOWED_HOSTS al dominio utilizado. Para un proxy inverso, configura de forma explícita qué proxy puede enviar encabezados de conexión. No confíes en encabezados de cualquier origen.
- Ejecuta **un solo worker** cuando uses cámara. La cámara y los límites de solicitudes están en memoria; varios procesos necesitarían coordinación externa.
- No publiques la carpeta del proyecto como directorio estático. Solo se sirven los recursos de app/static, data/uploads y data/audio.
- Los límites de solicitudes son por dirección de cliente: 5 intentos de acceso por minuto, 20 respuestas de voz por minuto y 10 activaciones de cámara por minuto.
- /api/health comprueba la base de datos. Ollama o la cámara pueden fallar sin impedir consultar productos.
- Mantén copias de seguridad del catálogo, imágenes, configuración y clave de sesión. .gitignore excluye estos archivos, entornos virtuales y audios generados.

## Verificación

~~~powershell
.\venv\Scripts\python.exe -B -m unittest discover -s tests -v
node --test tests/frontend.test.cjs
.\venv\Scripts\python.exe -m pip check
~~~

Las pruebas usan una base de datos temporal y sustitutos de los servicios externos. No utilizan la cámara ni modifican el catálogo de la tienda. Para validar el equipo real, prueba además cámara, voz, QR y permisos del navegador en el puesto.

Con Node 22 o posterior y Chrome instalado puedes ejecutar también `node tests/browser_smoke.cjs`. Comprueba búsqueda, respuesta escrita, ancho móvil, acceso y edición administrativa en un navegador real sin ventana. Usa datos temporales y guarda capturas en artifacts/review. Puedes indicar otra instalación de Chrome mediante CHROME_PATH.

El entorno existente tenía dos dependencias opcionales de Google incompatibles con el protobuf de MediaPipe. Se ajustaron google-api-core a 2.24.2 y grpcio-status a 1.62.3. constraints-legacy.txt conserva esa compatibilidad al instalar los requisitos de visión, sin agregar los SDK de Google a instalaciones nuevas.

## Alcance pendiente

Reservas por fechas, pagos, devolución de prendas, existencias y métricas de conversión quedan para otra etapa. WhatsApp inicia una consulta; la aplicación no confirma una reserva.
