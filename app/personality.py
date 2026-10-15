"""Robot personality: expressive states, voice prosody and phrasing.

Each emotion maps to a voice prosody (edge-tts rate/pitch/volume) and to a
face mood rendered by the kiosk (CSS class ``mood-<emotion>``). A ``Speech``
is a sequence of segments, so one answer can go from a thoughtful "Mmm..." to
an excited "¡mira nomás!".

Commercial facts (names, prices, sizes, extras) always come from the
catalogue; this module only decides HOW they are said.
"""
import random
from dataclasses import dataclass, field

EMOTIONS = {
    'amable':       {'rate': '+0%',  'pitch': '+0Hz',  'volume': '+0%'},
    'alegre':       {'rate': '+6%',  'pitch': '+10Hz', 'volume': '+5%'},
    'entusiasmada': {'rate': '+10%', 'pitch': '+18Hz', 'volume': '+10%'},
    'curiosa':      {'rate': '-4%',  'pitch': '+8Hz',  'volume': '+0%'},
    'pensativa':    {'rate': '-22%', 'pitch': '-6Hz',  'volume': '-10%'},
    'empatica':     {'rate': '-8%',  'pitch': '-3Hz',  'volume': '-5%'},
    'despedida':    {'rate': '-4%',  'pitch': '+6Hz',  'volume': '+0%'},
}
DEFAULT = 'amable'


@dataclass
class Speech:
    segments: list = field(default_factory=list)  # [(emotion, text)]
    mood: str | None = None

    def add(self, emotion, text):
        text = ' '.join(str(text).split())
        if not text:
            return self
        if emotion not in EMOTIONS:
            emotion = DEFAULT
        if self.segments and self.segments[-1][0] == emotion:
            self.segments[-1] = (emotion, f'{self.segments[-1][1]} {text}')
        else:
            self.segments.append((emotion, text))
        return self

    @property
    def text(self):
        return ' '.join(text for _, text in self.segments)

    @property
    def main_mood(self):
        if self.mood:
            return self.mood
        if not self.segments:
            return DEFAULT
        return max(self.segments, key=lambda segment: len(segment[1]))[0]

    def voice_segments(self):
        return [(text, EMOTIONS[emotion]) for emotion, text in self.segments]

    def timeline(self):
        return [{'emotion': emotion, 'text': text} for emotion, text in self.segments]


def money(value):
    return f'{float(value):.2f}'


def _has_discount(product):
    return float(product.precio_final) < float(product.precio_base)


def _extras(product):
    extras = []
    if product.incluye_sombrero:
        extras.append('sombrero')
    if product.incluye_manta:
        extras.append('manta')
    return extras


def presentation(product, opener=None, invite=True):
    """Full product presentation shown after a search."""
    speech = Speech()
    speech.add('entusiasmada', opener or random.choice([
        '¡A ver, a ver, mira nomás!', '¡Uy, esta te va a encantar!', '¡Ay, qué linda, caserita!',
    ]))
    speech.add('alegre', f'Te presento {product.nombre}, en talla {product.talla}, '
                         f'a {money(product.precio_final)} soles por alquiler.')
    if _has_discount(product):
        speech.add('entusiasmada', f'¡Y está rebajadita, antes costaba {money(product.precio_base)} soles!')
    speech.add('amable', product.descripcion)
    extras = _extras(product)
    if extras:
        speech.add('alegre', f"Viene completita, incluye {' y '.join(extras)}.")
    speech.add('amable', 'Consulta disponibilidad y condiciones por WhatsApp.')
    if invite:
        speech.add('curiosa', '¿Tienes alguna consulta sobre esta pollera? Pregúntame nomás, te escucho.')
    return speech


def offer(product, educate=True):
    """Short attraction pitch for a detected passer-by; teaches how to use the mic."""
    speech = Speech()
    price = money(product.precio_final)
    speech.add('entusiasmada', random.choice([
        '¡Hola, caserita! ¿Buscas pollera para tu fiesta?', '¡Pase, pase, casera!', '¡Mira qué linda pollera tenemos!',
    ]))
    speech.add('alegre', f'Conoce {product.nombre}, en talla {product.talla}, a {price} soles por alquiler.')
    if educate:
        speech.add('amable', random.choice([
            'Si quieres ver más polleras, mantén presionado el botón del micrófono y dime qué buscas.',
            'Aprieta el botón del micrófono sin soltarlo, dime el código o el color que buscas, y suéltalo.',
            'Para preguntarme, mantén presionado el micrófono mientras hablas. ¡Así de fácil!',
        ]))
    else:
        speech.add('amable', 'Acércate y consulta los detalles.')
    return speech


def not_found():
    return (Speech()
            .add('pensativa', 'A ver...')
            .add('empatica', 'no encontré una pollera con eso, caserita.')
            .add('amable', 'Dime qué color, código o qué fiesta buscas, te escucho.'))


def empty_catalog():
    return Speech().add('empatica', 'Casera, aún no hay polleras registradas en el catálogo.')


def autonomous_greeting():
    """Warm autonomous greeting when camera detects interest.
    Strictly keeps focus on the robot face and invites customer interaction without pushing a specific product.
    """
    speech = Speech()
    speech.add('entusiasmada', random.choice([
        '¡Hola, caserita! Tenemos unas polleras muy bonitas para tus fiestas.',
        '¡Hola, casera! Qué gusto verte, tenemos hermosas polleras.',
        '¡Hola, caserita! Bienvenida a nuestra tienda.',
    ]))
    speech.add('curiosa', random.choice([
        '¿Buscas algún color o código en especial? Te escucho.',
        '¿Qué modelo o color de pollera estás buscando hoy? Dime nomás.',
        'Dime qué color o código necesitas y te lo muestro con gusto.',
    ]))
    return speech


def greeting():
    """Warm verbal reply to a customer greeting without navigating away from the face."""
    speech = Speech()
    speech.add('entusiasmada', random.choice([
        '¡Hola, caserita! Qué gusto tenerte por aquí.',
        '¡Hola, casera! Bienvenida a la tienda.',
        '¡Hola, caserita! ¿Cómo estás?',
    ]))
    speech.add('curiosa', '¿Buscas alguna pollera para tu fiesta? Dime el color o código que estás buscando, te escucho.')
    return speech


def general_inquiry(products=None):
    """Verbal overview for general questions like '¿qué polleras tienes?' without picking an arbitrary product card."""
    speech = Speech()
    speech.add('alegre', 'Tenemos hermosas polleras de fiesta para alquiler en colores como rojo, morado, azul, verde y fucsia.')
    speech.add('curiosa', '¿Tienes en mente algún color, talla o código en especial? Dime y te la muestro, caserita.')
    return speech


def silence_reminder():
    speech = Speech()
    speech.add('amable', random.choice([
        'Puedes decirme el color o código que estás buscando, caserita.',
        '¿Deseas ver algún modelo o color en especial? Dime nomás, te escucho.',
        'Pregúntame sobre precios, tallas o colores, caserita, te escucho.',
    ]))
    return speech


def farewell():
    speech = Speech()
    speech.add('despedida', '¡Gracias a ti, caserita! Que te vaya muy bonito en tu fiesta. ¡Aquí estaré si necesitas algo!')
    return speech


# Short fillers played instantly while the server looks things up.
THINKING_CLIPS = [
    [('pensativa', 'A ver...'), ('curiosa', 'déjame ver...')],
    [('pensativa', 'A ver, a ver...'), ('amable', 'déjame buscar en mi catálogo.')],
    [('curiosa', 'A ver, un segundito,'), ('pensativa', 'ya te lo busco...')],
    [('pensativa', 'Déjame ver...'), ('alegre', '¡a ver qué encontramos para ti!')],
]


def thinking_clip(index):
    speech = Speech()
    for emotion, text in THINKING_CLIPS[index]:
        speech.add(emotion, text)
    return speech


def rented_presentation(product, others=None, today=None):
    """Speech for a specifically requested product that is currently rented out."""
    from datetime import date
    today = today or date.today()
    speech = Speech()
    speech.add('amable', f'¡Ah, sí! Conozco {product.nombre}, con código {product.codigo}. Es un modelo muy bonito, pero ahorita está alquilada, caserita.')
    
    if product.fecha_devolucion_estimada:
        diff = (product.fecha_devolucion_estimada - today).days
        if diff > 1:
            speech.add('pensativa', f'Según nuestro registro, debería regresar en unos {diff} días aproximadamente.')
        elif diff == 1:
            speech.add('pensativa', 'Según nuestro registro, debería regresar mañana aproximadamente.')
        elif diff == 0:
            speech.add('pensativa', 'Según nuestro registro, su fecha estimada de retorno es hoy, pero todavía no se ha confirmado su entrega en tienda.')
        else:
            speech.add('pensativa', 'La fecha estimada de retorno ya venció, pero aún no se ha confirmado su devolución en tienda.')
    else:
        speech.add('pensativa', 'Por ahora no tenemos una fecha estimada de retorno confirmada en el registro.')
    
    available = [p for p in (others or []) if getattr(p, 'estado', 'DISPONIBLE') == 'DISPONIBLE' and p.codigo != product.codigo]
    alt = None
    if available:
        # Search for color match in available
        p_text = f'{product.nombre} {product.descripcion}'.lower()
        colors = ['rosad', 'roj', 'guinda', 'morad', 'lila', 'azul', 'celest', 'verd', 'amarill', 'dorad', 'blanc', 'negr', 'naranj', 'melon']
        matching_colors = [c for c in colors if c in p_text]
        if matching_colors:
            alt = next((p for p in available if any(c in f'{p.nombre} {p.descripcion}'.lower() for c in matching_colors)), None)
        if not alt:
            alt = available[0]

    if alt:
        speech.add('alegre', f'Mientras tanto, puedo mostrarte {alt.nombre} que sí tenemos disponible en tienda, caserita.')
    else:
        speech.add('empatica', 'Por ahora no veo otra alternativa disponible en este modelo, pero puedes consultar por WhatsApp si te la pueden conseguir.')
        
    return speech, alt

