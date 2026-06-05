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
