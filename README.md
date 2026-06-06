# IG_GF_app

Sistema para búsqueda y gestión de células de Iglesia Hosanna.

## Instalar local

```bash
cd IG_GF_app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask init-db
flask seed
flask run
```

Abrir: http://127.0.0.1:5000

Admin inicial:
- admin
- admin123

## Twilio SMS opcional

Crear archivo `.env` basado en `.env.example` y poner:

```env
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=
```

## Variables importantes en Render

Configura la URL pública para mensajes y credenciales:

```env
APP_BASE_URL=https://celulas.hosannaigle.com
```

El botón de WhatsApp para compartir credenciales usa esta URL y el teléfono del líder.


## Instagram automático

Configurar en Render:

```env
INSTAGRAM_ACCESS_TOKEN=token_de_meta
INSTAGRAM_POST_LIMIT=8
```

El token no debe guardarse en GitHub ni en el código.
