import io
import uuid
import warnings

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from . import config


def save_image(upload):
    if not upload or not upload.filename:
        return None
    data = upload.file.read(config.MAX_IMAGE_BYTES + 1)
    if len(data) > config.MAX_IMAGE_BYTES:
        raise HTTPException(413, 'La imagen no debe superar 5 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ('JPEG', 'PNG', 'WEBP') or image.width * image.height > 20_000_000:
                    raise HTTPException(422, 'Usa JPG, PNG o WebP de hasta 20 megapíxeles.')
                image.load()
                clean = image.convert('RGB')
                clean.thumbnail((2000, 2000))
                filename = f'{uuid.uuid4().hex}.jpg'
                config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                clean.save(config.UPLOAD_DIR / filename, 'JPEG', quality=90)
        return f'/media/{filename}'
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(422, 'El archivo no contiene una imagen válida.') from exc


def discard_image(url):
    if url and url.startswith('/media/'):
        path = (config.UPLOAD_DIR / url.removeprefix('/media/')).resolve()
        if path.parent == config.UPLOAD_DIR.resolve():
            path.unlink(missing_ok=True)
