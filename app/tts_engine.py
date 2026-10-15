import asyncio
import hashlib
import logging
import os
import re
import time
import uuid

import edge_tts
from . import config

logger = logging.getLogger(__name__)
_slots = asyncio.Semaphore(2)


def normalize_for_tts(text: str, provider: str = 'edge') -> str:
    """Normalize vocal hesitations and interjections to sound natural rather than spelled-out (e.g. M, M, M)."""
    if not text:
        return ''
    def _replace_mmm(match):
        if provider == 'piper':
            return 'A ver... '
        return 'A ver... '

    def _sub_token(match):
        token = match.group(1)
        start = match.start()
        prefix = text[:start].rstrip()
        if prefix and prefix[-1].isdigit() and token.lower() == 'mm':
            return match.group(0)
        return _replace_mmm(match)

    cleaned = re.sub(r'\b([mM]{2,})\b([.,…\s]*)', _sub_token, text)
    cleaned = re.sub(r'(?:A ver\.\.\.\s*){2,}', 'A ver... ', cleaned)
    return cleaned.strip()


def cleanup_audio():
    """Only manage generated audio in the dedicated cache directory."""
    now = time.time()
    files = []
    for path in config.AUDIO_DIR.glob('*'):
        if path.is_file() and path.suffix in ('.mp3', '.wav', '.tmp'):
            try:
                files.append((path.stat().st_mtime, path))
            except FileNotFoundError:
                pass
    for index, (modified, path) in enumerate(sorted(files, reverse=True)):
        if now - modified > config.AUDIO_RETENTION_SECONDS or (index >= 256 and now - modified > 600):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning('No se pudo limpiar un audio vencido.')


async def _piper(text, target):
    normalized = normalize_for_tts(text, provider='piper')
    process = await asyncio.create_subprocess_exec(
        config.PIPER_BIN, '--model', str(config.PIPER_MODEL), '--output_file', str(target),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(process.communicate(normalized.encode('utf-8')), timeout=config.TTS_TIMEOUT)
        if process.returncode or not target.exists() or target.stat().st_size == 0:
            raise RuntimeError('Piper no generó audio.')
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def generate_audio(speech_or_text) -> str | None:
    """Return cached speech or None; a voice outage must not hide the response text."""
    if hasattr(speech_or_text, 'voice_segments'):
        raw_segments = speech_or_text.voice_segments()
        segments = [(normalize_for_tts(t, provider='edge'), p) for t, p in raw_segments]
        text = normalize_for_tts(speech_or_text.text, provider='edge')
        raw_key = '|'.join(f'{t}:{p.get("rate")}:{p.get("pitch")}:{p.get("volume")}' for t, p in segments)
        digest = hashlib.sha256(f'{config.VOICE_EDGE}|{config.PIPER_MODEL}|{raw_key}'.encode()).hexdigest()
    else:
        text = normalize_for_tts(str(speech_or_text or ''), provider='edge')
        segments = [(text, {})] if text else []
        digest = hashlib.sha256(f'{config.VOICE_EDGE}|{config.PIPER_MODEL}|{text}'.encode()).hexdigest()

    if not text or len(text) > 2000:
        return None
    config.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    for extension in ('.wav', '.mp3'):
        cached = config.AUDIO_DIR / (digest + extension)
        try:
            if cached.stat().st_size > 0:
                return '/audio/' + cached.name
        except FileNotFoundError:
            pass
    try:
        await asyncio.wait_for(_slots.acquire(), timeout=0.1)
    except TimeoutError:
        return None
    temporary = config.AUDIO_DIR / f'{uuid.uuid4().hex}.tmp'
    try:
        if config.PIPER_MODEL.is_file():
            try:
                await _piper(text, temporary)
                target = config.AUDIO_DIR / (digest + '.wav')
                os.replace(temporary, target)
                return '/audio/' + target.name
            except (OSError, RuntimeError, TimeoutError):
                logger.warning('Piper no está disponible; se intentará la voz en línea.')
        if len(segments) <= 1:
            seg_text, prosody = segments[0] if segments else (text, {})
            kwargs = {}
            if prosody.get('rate'): kwargs['rate'] = prosody['rate']
            if prosody.get('pitch'): kwargs['pitch'] = prosody['pitch']
            if prosody.get('volume'): kwargs['volume'] = prosody['volume']
            communicate = edge_tts.Communicate(seg_text, config.VOICE_EDGE, **kwargs)
            await asyncio.wait_for(communicate.save(str(temporary)), timeout=config.TTS_TIMEOUT)
        else:
            buffers = []
            for seg_text, prosody in segments:
                kwargs = {}
                if prosody.get('rate'): kwargs['rate'] = prosody['rate']
                if prosody.get('pitch'): kwargs['pitch'] = prosody['pitch']
                if prosody.get('volume'): kwargs['volume'] = prosody['volume']
                communicate = edge_tts.Communicate(seg_text, config.VOICE_EDGE, **kwargs)
                chunk_bytes = b''.join([chunk['data'] async for chunk in communicate.stream() if chunk['type'] == 'audio'])
                if chunk_bytes:
                    buffers.append(chunk_bytes)
            if not buffers:
                raise RuntimeError('Audio vacío.')
            temporary.write_bytes(b''.join(buffers))
        if temporary.stat().st_size == 0:
            raise RuntimeError('Audio vacío.')
        target = config.AUDIO_DIR / (digest + '.mp3')
        os.replace(temporary, target)
        return '/audio/' + target.name
    except Exception:
        logger.warning('La voz no está disponible; la respuesta se mostrará en pantalla.')
        return None
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            logger.warning('No se pudo eliminar un audio temporal; se reintentará en la limpieza.')
        _slots.release()
