from app.database import SessionLocal, init_schema
from app import models

def populate():
    init_schema()
    db = SessionLocal()
    
    # Check if we already have data
    if db.query(models.Pollera).count() > 0:
        print("La base de datos ya tiene información.")
        db.close()
        return

    polleras_mock = [
        models.Pollera(
            codigo="34TM",
            nombre="Pollera de Gala Andina",
            descripcion="Hermosa pollera bordada con hilos de oro y plata, ideal para fiestas patronales.",
            talla="M",
            precio_base=130.00,
            incluye_sombrero=True,
            incluye_manta=False,
            imagen_url="/static/img/default.svg"
        ),
        models.Pollera(
            codigo="12CR",
            nombre="Pollera de Carnaval",
            descripcion="Pollera colorida y ligera, perfecta para danzas de carnaval.",
            talla="S",
            precio_base=85.00,
            incluye_sombrero=False,
            incluye_manta=True,
            imagen_url="/static/img/default.svg"
        ),
        models.Pollera(
            codigo="99XL",
            nombre="Pollera Matrimonial",
            descripcion="Pollera elegante de novia andina, con detalles en perlas.",
            talla="L",
            precio_base=250.00,
            incluye_sombrero=True,
            incluye_manta=True,
            imagen_url="/static/img/default.svg"
        )
    ]

    db.add_all(polleras_mock)
    db.commit()
    print("Base de datos poblada con éxito.")
    db.close()

if __name__ == "__main__":
    populate()
