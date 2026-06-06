# IG_GF_app — Plataforma Hosanna

Rutas principales:

- `/` landing informativa de Hosanna.
- `/celulas` buscador público de células/grupos familiares.
- `/login` acceso admin, mentor y líderes.
- `/admin` panel administrativo.
- `/leader` panel del líder.

## Local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask init-db
flask ensure-admin
flask run
```

## Render

Start Command recomendado:

```bash
flask upgrade-db && flask migrate-usernames && flask ensure-admin && gunicorn app:app
```

Variables mínimas:

```env
SECRET_KEY=...
DATABASE_URL=...
APP_BASE_URL=https://hosannaigle.com
ADMIN_USERNAME=admin
ADMIN_PASSWORD=H0sann4!!!
ADMIN_NAME=Administrador Hosanna
SESSION_TIMEOUT_MINUTES=10
```

Para crear mentor:

```env
MENTOR_USERNAME=mentor
MENTOR_PASSWORD=H0sann4Mentor!!!
MENTOR_NAME=Mentor Hosanna
```

## Dominio

En Render agregar custom domain:

```text
hosannaigle.com
www.hosannaigle.com
```

En DNS, usar los registros indicados por Render. Para dominio raíz, Render permite ANAME/ALIAS hacia el subdominio `.onrender.com`; si el proveedor no soporta eso, usar A record `216.24.57.1`.
