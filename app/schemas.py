from datetime import date
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_serializer, field_validator, model_validator


def effective_price(base, discount):
    base = Decimal(str(base))
    discount = Decimal(str(discount or 0))
    return (discount if 0 < discount < base else base).quantize(Decimal('0.01'))


class PolleraCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    codigo: str = Field(min_length=1, max_length=50, pattern=r'^[A-Za-z0-9_-]+$')
    nombre: str = Field(min_length=1, max_length=100)
    descripcion: str = Field(min_length=1, max_length=500)
    talla: str = Field(min_length=1, max_length=10)
    precio_base: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    rebaja: Decimal = Field(default=Decimal('0'), ge=0, max_digits=12, decimal_places=2)
    incluye_sombrero: bool = False
    incluye_manta: bool = False
    estado: str = Field(default='DISPONIBLE', pattern=r'^(DISPONIBLE|ALQUILADA)$')
    fecha_alquiler: date | None = None
    fecha_devolucion_estimada: date | None = None

    @field_validator('codigo', 'talla')
    @classmethod
    def uppercase(cls, value):
        return value.upper()

    @model_validator(mode='after')
    def valid_discount(self):
        if self.rebaja >= self.precio_base:
            raise ValueError('La rebaja debe ser menor al precio regular; usa 0 si no hay rebaja.')
        return self


class Pollera(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    codigo: str
    nombre: str
    descripcion: str
    talla: str
    precio_base: Decimal
    rebaja: Decimal = Decimal('0')
    incluye_sombrero: bool
    incluye_manta: bool
    imagen_url: str | None = None
    imagen_url_2: str | None = None
    imagen_url_3: str | None = None
    estado: str = 'DISPONIBLE'
    fecha_alquiler: date | None = None
    fecha_devolucion_estimada: date | None = None

    @computed_field
    @property
    def imagenes(self) -> list[str]:
        return [url for url in [self.imagen_url, self.imagen_url_2, self.imagen_url_3] if url]

    @computed_field
    @property
    def precio_final(self) -> float:
        return float(effective_price(self.precio_base, self.rebaja))

    @field_serializer('precio_base', 'rebaja')
    def serialize_money(self, value):
        return float(value)



class ConversationContext(BaseModel):
    model_config = ConfigDict(extra='ignore')
    session_id: str | None = None
    current_code: str | None = None
    last_color: str | None = None
    last_talla: str | None = None
    celebration_reason: str | None = None
    presupuesto: str | None = None
    viewed_codes: list[str] = Field(default_factory=list)
    last_intent: str | None = None
    last_robot_question: str | None = None
    used_vocatives: list[str] = Field(default_factory=list)
    chat_history: list[dict[str, str]] = Field(default_factory=list)


class ConversationalReply(BaseModel):
    model_config = ConfigDict(extra='ignore')
    texto: str = Field(description="Respuesta hablada natural, cálida y sin repeticiones")
    emocion: str = Field(default='alegre', description="Emoción de prosodia")
    codigo_mostrar: str | None = Field(default=None, description="Código de pollera a mostrar o null")
    motivo_detectado: str | None = Field(default=None, description="Motivo de celebración detectado o null")
    presupuesto_detectado: str | None = Field(default=None, description="Percepción de precio o presupuesto o null")
    color_preferido: str | None = Field(default=None, description="Color preferido mencionado o null")
    talla_preferida: str | None = Field(default=None, description="Talla preferida mencionada o null")


class ChatMessage(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=1000)
    codigo_actual: str | None = Field(default=None, max_length=50)
    context: ConversationContext | None = None


class ProductSelection(BaseModel):
    model_config = ConfigDict(extra='ignore')
    codigo_mostrar: str | None = Field(default=None, max_length=50)


class ConversationMessage(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=1000)
    codigo: str = Field(min_length=1, max_length=50)
    context: ConversationContext | None = None


class IntentSelection(BaseModel):
    model_config = ConfigDict(extra='ignore')
    intencion: str | None = Field(default=None, max_length=30)
