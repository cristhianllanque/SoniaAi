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


def get_vocative(context=None, allow_empty=True):
    """Rotates vocatives naturally avoiding repeating the same one."""
    used = getattr(context, 'used_vocatives', []) if context else []
    # 40% empty so we don't spam vocatives on every phrase
    pool = ['caserita', 'amiga', 'joven', 'señorita', 'amigo']
    if allow_empty:
        pool.extend(['', '', ''])
    last = used[-1] if used else None
    available = [v for v in pool if not last or v != last]
    choice = random.choice(available or pool)
    if choice and context and hasattr(context, 'used_vocatives'):
        context.used_vocatives.append(choice)
        if len(context.used_vocatives) > 5:
            context.used_vocatives.pop(0)
    return choice


def presentation(product, opener=None, invite=True, context=None):
    """Full product presentation shown after a search."""
    speech = Speech()
    voc = get_vocative(context)
    voc_suffix = f', {voc}' if voc else ''
    reason = getattr(context, 'celebration_reason', None) if context else None

    if opener:
        first = opener
    elif reason:
        clean_r = str(reason).strip()
        first = random.choice([
            f'¡Ah no, para esa ocasión de {clean_r} en la que tú me dijiste te podría dar esta pollera {product.nombre}!',
            f'¡Para esa ocasión de {clean_r} que me comentaste, mira qué belleza{voc_suffix}!',
            f'¡Justo para tu {clean_r}{voc_suffix}, esta pollera {product.nombre} te va a quedar hermosa!',
            f'¡Para lucirte en tu fiesta de {clean_r}{voc_suffix}, fíjate en esta opción!',
        ])
    else:
        first = random.choice([
            f'¡A ver, a ver, mira nomás{voc_suffix}!',
            f'¡Uy, esta te va a encantar{voc_suffix}!',
            f'¡Fíjate en esta belleza{voc_suffix}!',
            f'¡Qué linda opción tenemos aquí{voc_suffix}!',
            f'¡Mira este modelo tan elegante{voc_suffix}!',
        ])

    speech.add('entusiasmada', first)
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
        speech.add('curiosa', random.choice([
            '¿Tienes alguna consulta sobre esta pollera? Pregúntame nomás, te escucho.',
            '¿Te gustaría saber algo más de este modelo? Con confianza, te escucho.',
            '¿Qué te parece? Pregúntame sobre tallas o lo que gustes, te escucho.',
        ]))
    return speech


def offer(product, educate=True, context=None):
    """Lively attraction pitch offering a pollera with teaser in hand, asking for occasion, color, or code."""
    speech = Speech()
    voc = get_vocative(context)
    voc_prefix = f'¡Hola, {voc}! ' if voc else '¡Hola! '
    voc_suffix = f', {voc}' if voc else ', caserita'
    price = money(product.precio_final)

    intros = [
        f'{voc_prefix}¡Pase adelante! Mire, tengo por ejemplo esta hermosa pollera {product.nombre} en talla {product.talla} a {price} soles.',
        f'¡Pase, pase{voc_suffix}! Tenemos polleras preciosas para alquiler. Mire esta {product.nombre}, viene completita.',
        f'{voc_prefix}¡Mire qué bonita opción tenemos por aquí! Le ofrezco {product.nombre} a {price} soles por alquiler.',
        f'¡Bienvenida{voc_suffix}! Si busca pollera para su evento, mire por ejemplo este modelo {product.nombre} en talla {product.talla}.',
        f'{voc_prefix}¡Qué alegría saludarla! Tenemos trajes de fiesta hermosos, como este {product.nombre} que ve aquí.',
    ]

    invitations = [
        '¿Para qué ocasión o fiesta está buscando? También puede dictarme el color o código que desea y se lo muestro.',
        'Cuénteme para qué fiesta la necesita, o dígame qué color o código prefiere. ¡Dígame nomás, le escucho!',
        '¿Qué modelo o color tiene en mente para su celebración? O si tiene un código en especial, dígamelo, le escucho.',
        '¿Para qué fecha o festividad es su traje? Puede decirme el color que busca o dictarme el código, con confianza.',
    ]

    speech.add('entusiasmada', random.choice(intros))
    speech.add('curiosa', random.choice(invitations))
    return speech


def not_found(context=None):
    voc = get_vocative(context)
    voc_suffix = f', {voc}' if voc else ', caserita'
    return (Speech()
            .add('pensativa', 'A ver...')
            .add('empatica', f'no encontré una pollera con eso{voc_suffix}.')
            .add('amable', 'Dime qué color, código o qué fiesta buscas, te escucho.'))


def empty_catalog():
    return Speech().add('empatica', 'Aún no hay polleras registradas en el catálogo.')


def autonomous_greeting(context=None):
    """Warm autonomous greeting when camera detects interest."""
    speech = Speech()
    options = [
        ('¡Hola, caserita! Pase adelante, tenemos polleras preciosas para sus fiestas.', '¿Para qué fiesta o qué color o código de pollera desea dictarme? Le escucho.'),
        ('¡Hola, casera! Qué gusto saludarla, bienvenida a nuestra tienda.', 'Cuénteme para qué ocasión busca o qué color o código le gustaría ver, dígame nomás.'),
        ('¡Pase adelante, caserita! Tenemos trajes hermosos para todo evento.', '¿Para qué fiesta necesita su pollera, o qué color o código prefiere? Con confianza, le escucho.')
    ]
    g1, g2 = random.choice(options)
    speech.add('entusiasmada', g1)
    speech.add('curiosa', g2)
    return speech


def greeting(context=None):
    """Warm verbal reply to a customer greeting without navigating away from the face."""
    speech = Speech()
    voc = get_vocative(context)
    voc_prefix = f'¡Hola, {voc}! ' if voc else '¡Hola! '
    speech.add('entusiasmada', random.choice([
        f'{voc_prefix}Qué gusto tenerte por aquí.',
        f'{voc_prefix}Bienvenida a la tienda.',
        f'{voc_prefix}¿Cómo estás? ¡Qué alegría saludarte!',
    ]))
    speech.add('curiosa', random.choice([
        '¿Buscas alguna pollera para tu fiesta? Cuéntame qué color o código necesitas, te escucho.',
        '¿Para qué ocasión estás buscando traje hoy? Dime con confianza, te escucho.',
    ]))
    return speech


def general_inquiry(products=None, context=None):
    """Verbal overview for general questions like '¿qué polleras tienes?'."""
    speech = Speech()
    voc = get_vocative(context)
    voc_suffix = f', {voc}' if voc else ''
    speech.add('alegre', f'Tenemos hermosas polleras de fiesta para alquiler en colores como rojo, morado, azul, verde y fucsia{voc_suffix}.')
    speech.add('curiosa', '¿Tienes en mente algún color, talla o qué tipo de fiesta estás planeando? Dime y te muestro las mejores opciones.')
    return speech


def celebration_advice(motive: str, products=None, context=None):
    """Contextual styling advice for specific occasions (Christmas, birthdays, Halloween, weddings, patronal festivals)."""
    speech = Speech()
    voc = get_vocative(context)
    voc_suffix = f', {voc}' if voc else ''
    m = (motive or '').lower()
    if 'halloween' in m:
        speech.add('entusiasmada', f'¡Para Halloween o fiesta temática queda sensacional{voc_suffix}!')
        speech.add('alegre', 'Para esa ocasión te recomendaría una pollera en tonos oscuros o contrastes llamativos, como negro, morado o naranja con bordado brillante.')
        speech.add('curiosa', '¿Te gustaría ver un modelo en esos tonos, o prefieres decirme qué color tienes en mente?')
    elif 'navidad' in m:
        speech.add('entusiasmada', f'¡Qué hermosa ocasión{voc_suffix}!')
        speech.add('alegre', 'Si te gustan los colores clásicos de Navidad, podemos buscar una roja. Aunque una verde también quedaría preciosa.')
        speech.add('curiosa', '¿Cuál prefieres?')
    elif 'cumplean' in m or 'cumple' in m:
        speech.add('entusiasmada', f'¡Para un cumpleaños hay que lucirse con algo especial{voc_suffix}!')
        speech.add('alegre', 'Para esa ocasión que me comentas, si es de día los tonos vivos como fucsia o turquesa quedan preciosos, y si es de noche un azul o morado elegante.')
        speech.add('curiosa', '¿Es una fiesta elegante o más tradicional? Así te recomiendo un modelo que vaya con la ocasión.')
    elif any(k in m for k in ('boda', 'matrimonio', 'casamiento')):
        speech.add('alegre', f'¡Qué linda celebración{voc_suffix}!')
        speech.add('curiosa', 'Para una boda lucen preciosos los tonos palo rosa, crema o un azul distinguido con mantita fina. ¿Qué tono te gustaría lucir?')
    elif any(k in m for k in ('patronal', 'morenada', 'diablada', 'caporal', 'candelaria', 'carnaval', 'tinkus', 'parada', 'concurso')):
        speech.add('entusiasmada', f'¡Para esa fiesta hay que lucirse con todo el brillo{voc_suffix}!')
        speech.add('curiosa', 'Tenemos trajes con bordados muy finos que destacan al bailar. ¿Qué color tienes en mente?')
    elif any(k in m for k in ('graduacion', 'promocion')):
        speech.add('entusiasmada', f'¡Qué gran logro, felicidades{voc_suffix}!')
        speech.add('alegre', 'Para una fiesta de graduación o promoción lucen muy elegantes los trajes en azul noche, vino o dorado con bordado fino.')
        speech.add('curiosa', '¿Qué color te gustaría lucir para tu festejo?')
    else:
        speech.add('alegre', f'¡Qué buen motivo para festejar{voc_suffix}!')
        speech.add('curiosa', f'Para esa ocasión tenemos opciones preciosas. ¿Buscas algún color o estilo en especial?')
    return speech


def price_comment_response(comment_type: str, product=None, context=None):
    """Witty, sympathetic response to budget remarks ('está barata' / 'está cara')."""
    speech = Speech()
    voc = get_vocative(context)
    voc_suffix = f', {voc}' if voc else ''
    if comment_type == 'barata':
        speech.add('alegre', f'¡Y eso que todavía no te he mostrado las otras opciones{voc_suffix}!')
        speech.add('curiosa', 'Hay modelos preciosos para distintos presupuestos. ¿Te gustaría ver otro modelo o te gusta este?')
    else:
        speech.add('empatica', f'Te entiendo perfectamente{voc_suffix}, cada fiesta tiene su presupuesto.')
        speech.add('amable', 'El valor refleja la calidad del bordado y que viene completita, pero también tenemos modelos más económicos. ¿Qué presupuesto tienes en mente?')
    return speech


def casual_chit_chat(text: str, context=None):
    """Spontaneous, warm response for light banter, compliments, or casual questions."""
    import unicodedata
    speech = Speech()
    voc = get_vocative(context)
    voc_suffix = f', {voc}' if voc else ''
    t = unicodedata.normalize('NFKD', text or '').encode('ASCII', 'ignore').decode('utf-8').lower()
    if any(k in t for k in ('chiste', 'gracios', 'broma')):
        speech.add('alegre', f'¡Me encanta la gente con buen humor{voc_suffix}!')
        speech.add('curiosa', 'Dicen que fiesta sin buena pollera es como caldo sin sal. A ver, cuéntame qué estás buscando.')
    elif any(k in t for k in ('linda', 'guapa', 'bonita', 'coqueta', 'guapo')):
        speech.add('entusiasmada', f'¡Ay, qué simpático detalle{voc_suffix}!')
        speech.add('alegre', 'Aquí lo que sobran son polleras hermosas para que tú también brilles en tu evento. ¿Tienes algún color favorito?')
    elif any(k in t for k in ('frio', 'calor', 'clima')):
        speech.add('alegre', f'¡Uy sí, el clima a veces nos sorprende{voc_suffix}!')
        speech.add('curiosa', 'Pero zapateando con una buena pollera se te quita cualquier frío. ¿Para qué fecha es tu fiesta?')
    else:
        speech.add('alegre', f'¡Qué gusto conversar contigo{voc_suffix}!')
        speech.add('curiosa', 'Aquí estoy lista para ayudarte a encontrar el traje ideal. ¿Tienes algún color o modelo en mente?')
    return speech


def silence_reminder(context=None):
    speech = Speech()
    voc = get_vocative(context)
    voc_suffix = f', {voc}' if voc else ', caserita'
    speech.add('amable', random.choice([
        f'Puedes decirme el color o código que estás buscando{voc_suffix}.',
        f'¿Qué modelo o color estás buscando{voc_suffix}? Dime nomás, te escucho.',
        f'Si estás buscando precios, tallas o modelos{voc_suffix}, dime con confianza, te escucho.',
    ]))
    return speech


def farewell(context=None):
    speech = Speech()
    return speech.add('despedida', '¡Gracias a ti, caserita! Que te vaya muy bonito en tu fiesta. ¡Aquí estaré si necesitas algo!')


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

