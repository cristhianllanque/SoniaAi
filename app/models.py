from sqlalchemy import Column, Integer, String, Numeric, Boolean, Date
from .database import Base

class Pollera(Base):
    __tablename__ = "polleras"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), unique=True, index=True)
    nombre = Column(String(100))
    descripcion = Column(String(500))
    talla = Column(String(10))
    precio_base = Column(Numeric(12, 2), nullable=False)
    rebaja = Column(Numeric(12, 2), default=0, nullable=False)
    incluye_sombrero = Column(Boolean, default=False)
    incluye_manta = Column(Boolean, default=False)
    imagen_url = Column(String(255), nullable=True)
    imagen_url_2 = Column(String(255), nullable=True)
    imagen_url_3 = Column(String(255), nullable=True)
    estado = Column(String(20), default="DISPONIBLE", nullable=False)
    fecha_alquiler = Column(Date, nullable=True)
    fecha_devolucion_estimada = Column(Date, nullable=True)

class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    hashed_password = Column(String(255))

