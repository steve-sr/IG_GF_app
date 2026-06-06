import os, re, math, secrets, string, csv, unicodedata
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import quote_plus
import requests

from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-change-me')
db_url = os.getenv('DATABASE_URL', 'sqlite:///ig_gf_app.db')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

APP_PUBLIC_URL = os.getenv('APP_BASE_URL') or os.getenv('APP_PUBLIC_URL') or 'https://hosannaigle.com'
APP_PUBLIC_URL = APP_PUBLIC_URL.rstrip('/')

IG_ACCESS_TOKEN = os.getenv('INSTAGRAM_ACCESS_TOKEN') or os.getenv('IG_ACCESS_TOKEN')
IG_POST_LIMIT = int(os.getenv('INSTAGRAM_POST_LIMIT', '8'))
IG_GRAPH_URL = os.getenv('INSTAGRAM_GRAPH_URL', 'https://graph.instagram.com/me/media')

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Iniciá sesión para continuar.'
SESSION_TIMEOUT_MINUTES = int(os.getenv('SESSION_TIMEOUT_MINUTES', '10'))

DAYS = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']
HOURS = [f'{h:02d}:{m:02d}' for h in range(5, 23) for m in (0, 30)]
BARRIOS_LIBERIA = [
    'Nazareth','Condega','Moracia','San Roque','Barrio Los Ángeles','Corazón de Jesús','Curime',
    'La Victoria','El Capulín','Buenos Aires','El Jícaro','Pueblo Nuevo','Llano La Cruz','25 de Julio',
    'La Guaria','Los Cerros','La Carreta','El Gallo','San Miguel','San Judas','El Roble','Daniel Oduber',
    'IMAS','La Cruz','Camarenos','Los Lagos','Santa Ana','El Sitio','Rodeíto','Guardia','Comunidad',
    'Irigaray','Cañas Dulces','Mayorga','Quebrada Grande','Nacascolo','Centro de Liberia','Otro'
]


SECTORS = [f'Sector {i}' for i in range(1, 11)] + ['Sin sector']
CELL_TYPES = [('adultos','Adultos'),('jovenes','Jóvenes'),('ambos','Adultos y jóvenes')]

def normalize_sector(value):
    value = (value or '').strip()
    return value if value in SECTORS and value != 'Sin sector' else None

def user_sector_label(user):
    return getattr(user, 'sector', None) or 'Sin sector'

def cell_sector_label(cell):
    if getattr(cell, 'leader', None) and getattr(cell.leader, 'sector', None):
        return cell.leader.sector
    return 'Sin sector'

def safe_text(value, fallback='Por definir'):
    raw = '' if value is None else str(value).strip()
    if not raw or raw.lower() in ['none','null','nan','undefined','por definir']:
        return fallback
    return raw

def display_barrio(cell):
    other = safe_text(getattr(cell, 'barrio_other', None), '')
    barrio = safe_text(getattr(cell, 'barrio', None), '')
    return other or barrio or 'Barrio por definir'

def status_label(status):
    return {'active':'Activa','paused':'Pausada','full':'Llena'}.get(status or '', 'Pausada')

def cell_type_label(value):
    return {'adultos':'Adultos','jovenes':'Jóvenes','ambos':'Adultos y jóvenes'}.get(value or 'adultos', 'Adultos')

def get_mentor(user):
    if not user or not getattr(user, 'mentor_id', None):
        return None
    return User.query.get(user.mentor_id)

def can_manage_leader(user):
    if current_user.role == 'admin':
        return True
    return current_user.role == 'mentor' and user.role == 'leader' and user.mentor_id == current_user.id

def can_manage_cell(cell):
    if current_user.role == 'admin':
        return True
    return current_user.role == 'mentor' and cell.leader and cell.leader.mentor_id == current_user.id

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(180), unique=True, nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='leader') # admin, leader, member-reserved
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    current_session_token = db.Column(db.String(120), nullable=True)
    last_seen_at = db.Column(db.DateTime, nullable=True)
    sector = db.Column(db.String(40), nullable=True)
    mentor_id = db.Column(db.Integer, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Cell(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    leader_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    leader = db.relationship('User', backref='cells')
    barrio = db.Column(db.String(120), nullable=False)
    barrio_other = db.Column(db.String(120), nullable=True)
    address = db.Column(db.String(255), nullable=False)
    day = db.Column(db.String(20), nullable=False)
    time = db.Column(db.String(10), nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    description = db.Column(db.Text, nullable=True)
    google_maps_url = db.Column(db.Text, nullable=True)
    waze_url = db.Column(db.Text, nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(20), default='active') # active, paused, full
    cell_type = db.Column(db.String(20), default='adultos') # adultos, jovenes, ambos
    has_children_teacher = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class LeadRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    barrio = db.Column(db.String(120), nullable=True)
    cell_id = db.Column(db.Integer, db.ForeignKey('cell.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ChurchEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    event_date = db.Column(db.String(40), nullable=True)
    event_time = db.Column(db.String(40), nullable=True)
    image_url = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    location = db.Column(db.String(180), nullable=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def roles_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator

admin_required = roles_required('admin')
manager_required = roles_required('admin', 'mentor')
leader_required = roles_required('admin', 'mentor', 'leader')

def is_admin():
    return current_user.is_authenticated and current_user.role == 'admin'

def is_manager():
    return current_user.is_authenticated and current_user.role in ['admin', 'mentor']

def clean_phone(phone):
    return re.sub(r'\D+', '', phone or '')

def format_cr_phone(phone):
    digits = clean_phone(phone)
    if len(digits) == 8:
        return f'{digits[:4]}-{digits[4:]}'
    return (phone or '').strip()

def cr_phone(phone):
    digits = clean_phone(phone)
    if len(digits) == 8: return '+506' + digits
    if digits.startswith('506') and len(digits) == 11: return '+' + digits
    if phone and phone.startswith('+'): return phone
    return phone or ''

def whatsapp_phone_digits(phone):
    digits = clean_phone(phone)
    if len(digits) == 8:
        return '506' + digits
    if digits.startswith('506') and len(digits) == 11:
        return digits
    if phone and str(phone).startswith('+'):
        return clean_phone(phone)
    return digits

def wa_message_link(phone, message):
    digits = whatsapp_phone_digits(phone)
    if not digits:
        return ''
    return f'https://wa.me/{digits}?text={quote_plus(message or "")}'

def wa_link(phone, cell_name=''):
    msg = 'Hola, me interesaría asistir al grupo familiar'
    if cell_name:
        msg += f' {cell_name}'
    msg += '. ¿Me podrías brindar más información?'
    return wa_message_link(phone, msg)

def maps_url(lat, lng):
    return f'https://www.google.com/maps/search/?api=1&query={lat},{lng}'

def waze_url(lat, lng):
    return f'https://waze.com/ul?ll={lat},{lng}&navigate=yes'

def extract_coords(text):
    if not text: return None, None
    text = str(text)
    patterns = [
        r'@(-?\d+\.\d+),(-?\d+\.\d+)',
        r'[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)',
        r'[?&]query=(-?\d+\.\d+),(-?\d+\.\d+)',
        r'[?&]ll=(-?\d+\.\d+),(-?\d+\.\d+)',
        r'!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)',
        r'%213d(-?\d+\.\d+)%214d(-?\d+\.\d+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            lat, lng = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
    nums = re.findall(r'-?\d+\.\d+', text)
    for i in range(0, max(0, len(nums)-1)):
        lat, lng = float(nums[i]), float(nums[i+1])
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            return lat, lng
    return None, None


def resolve_google_maps_link(raw_url):
    """Intenta extraer coordenadas desde links normales o cortos de Google Maps."""
    raw_url = (raw_url or '').strip()
    lat, lng = extract_coords(raw_url)
    if lat is not None and lng is not None:
        return lat, lng, raw_url

    if not raw_url.startswith(('http://', 'https://')):
        raise ValueError('Pegá un link válido de Google Maps.')

    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(raw_url, allow_redirects=True, timeout=10, headers=headers)
    final_url = response.url or raw_url

    lat, lng = extract_coords(final_url)
    if lat is not None and lng is not None:
        return lat, lng, final_url

    # Algunas respuestas incluyen las coordenadas dentro del HTML inicial.
    lat, lng = extract_coords(response.text[:250000])
    if lat is not None and lng is not None:
        return lat, lng, final_url

    raise ValueError('No pude detectar coordenadas en ese link. Probá abrirlo en Google Maps y copiar el enlace completo.')

def distance_km(lat1, lon1, lat2, lon2):
    r = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2-lat1)
    dl = math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.atan2(math.sqrt(a), math.sqrt(1-a))

def random_password():
    alphabet = string.ascii_letters + string.digits
    return 'Hosanna-' + ''.join(secrets.choice(alphabet) for _ in range(7))



def slug_username(value):
    value = (value or '').strip().lower()
    replacements = {'á':'a','é':'e','í':'i','ó':'o','ú':'u','ñ':'n'}
    for a,b in replacements.items():
        value = value.replace(a,b)
    value = re.sub(r'[^a-z0-9._-]+', '.', value)
    value = re.sub(r'\.+', '.', value).strip('.')
    return value[:40] or 'lider'

def unique_username(base):
    base = slug_username(base)
    candidate = base
    i = 2
    while User.query.filter_by(username=candidate).first():
        suffix = str(i)
        candidate = (base[: max(1, 80-len(suffix))] + suffix)
        i += 1
    return candidate



def admin_seed_credentials():
    """Lee credenciales iniciales desde variables de entorno.
    No se deben escribir contraseñas reales en el código ni en GitHub.
    """
    username = os.getenv('ADMIN_USERNAME', 'admin').strip().lower()
    name = os.getenv('ADMIN_NAME', 'Administrador Hosanna').strip() or 'Administrador Hosanna'
    email = (os.getenv('ADMIN_EMAIL', '') or '').strip().lower() or None
    phone = (os.getenv('ADMIN_PHONE', '') or '').strip() or None
    password = os.getenv('ADMIN_PASSWORD')
    return username, name, email, phone, password

def ensure_admin_user(reset_password=False):
    username, name, email, phone, password = admin_seed_credentials()
    if not password:
        raise RuntimeError('Falta ADMIN_PASSWORD en variables de entorno. No se creará/actualizará el admin sin contraseña segura.')
    admin = User.query.filter_by(username=username).first()
    if not admin:
        admin = User(name=name, username=username, email=email, phone=phone, role='admin', active=True)
        admin.set_password(password)
        db.session.add(admin)
    else:
        admin.name = admin.name or name
        admin.role = 'admin'
        admin.active = True
        if email and admin.email != email:
            admin.email = email
        if phone and admin.phone != phone:
            admin.phone = phone
        if reset_password:
            admin.set_password(password)
    db.session.commit()
    return admin

def ensure_mentor_user(reset_password=False):
    username = (os.getenv('MENTOR_USERNAME', 'mentor') or 'mentor').strip().lower()
    password = os.getenv('MENTOR_PASSWORD')
    if not password:
        return None
    name = (os.getenv('MENTOR_NAME', 'Mentor Hosanna') or 'Mentor Hosanna').strip()
    email = (os.getenv('MENTOR_EMAIL', '') or '').strip().lower() or None
    phone = (os.getenv('MENTOR_PHONE', '') or '').strip() or None
    mentor = User.query.filter_by(username=username).first()
    if not mentor:
        mentor = User(name=name, username=username, email=email, phone=phone, role='mentor', active=True)
        mentor.set_password(password)
        db.session.add(mentor)
    else:
        mentor.name = mentor.name or name
        mentor.role = 'mentor'
        mentor.active = True
        if email and mentor.email != email:
            mentor.email = email
        if phone and mentor.phone != phone:
            mentor.phone = phone
        if reset_password:
            mentor.set_password(password)
    db.session.commit()
    return mentor


def send_sms(to, body):
    sid = os.getenv('TWILIO_ACCOUNT_SID')
    token = os.getenv('TWILIO_AUTH_TOKEN')
    from_number = os.getenv('TWILIO_FROM_NUMBER')
    if not all([sid, token, from_number]):
        return False, 'Twilio no está configurado. El líder fue creado correctamente.'
    try:
        from twilio.rest import Client
        client = Client(sid, token)
        msg = client.messages.create(body=body, from_=from_number, to=cr_phone(to))
        return True, f'SMS enviado. ID: {msg.sid}'
    except Exception as e:
        return False, f'No se pudo enviar SMS: {e}'



def fetch_instagram_posts():
    """Trae publicaciones reales de Instagram usando el token oficial de Meta.
    Si no hay token o la API falla, devuelve lista vacía para no romper el home.
    """
    token = os.getenv('INSTAGRAM_ACCESS_TOKEN') or os.getenv('IG_ACCESS_TOKEN')
    if not token:
        return []
    try:
        fields = 'id,caption,media_type,media_url,thumbnail_url,permalink,timestamp'
        response = requests.get(
            os.getenv('INSTAGRAM_GRAPH_URL', 'https://graph.instagram.com/me/media'),
            params={
                'fields': fields,
                'limit': int(os.getenv('INSTAGRAM_POST_LIMIT', '8')),
                'access_token': token,
            },
            timeout=8,
        )
        response.raise_for_status()
        items = response.json().get('data', [])
        posts = []
        for item in items:
            media_type = item.get('media_type', '')
            image_url = item.get('thumbnail_url') if media_type == 'VIDEO' else item.get('media_url')
            if not image_url:
                image_url = item.get('media_url')
            if not image_url or not item.get('permalink'):
                continue
            caption = (item.get('caption') or '').strip()
            posts.append({
                'caption': caption,
                'title': caption.split('\n')[0][:92] if caption else 'Publicación de Instagram',
                'image_url': image_url,
                'permalink': item.get('permalink'),
                'media_type': media_type,
                'timestamp': item.get('timestamp'),
            })
        return posts
    except Exception as exc:
        app.logger.warning('No se pudieron cargar publicaciones de Instagram: %s', exc)
        return []

def validate_cell_form(form):
    errors = []
    required = {'name':'Nombre de la célula','barrio':'Barrio','address':'Dirección','day':'Día','time':'Hora'}
    for k, label in required.items():
        if not (form.get(k) or '').strip(): errors.append(f'{label} es obligatorio.')
    if form.get('day') and form.get('day') not in DAYS: errors.append('Seleccioná un día válido.')
    return errors

@app.context_processor
def inject_globals():
    return dict(DAYS=DAYS, HOURS=HOURS, BARRIOS_LIBERIA=BARRIOS_LIBERIA, SECTORS=SECTORS, CELL_TYPES=CELL_TYPES, APP_PUBLIC_URL=APP_PUBLIC_URL, wa_link=wa_link, is_admin=is_admin, is_manager=is_manager, display_barrio=display_barrio, status_label=status_label, cell_type_label=cell_type_label, get_mentor=get_mentor, cell_sector_label=cell_sector_label, user_sector_label=user_sector_label)


@app.before_request
def enforce_session_security():
    if not current_user.is_authenticated:
        return
    now = datetime.utcnow()
    last_raw = session.get('last_activity_at')
    if last_raw:
        try:
            last = datetime.fromisoformat(last_raw)
            if now - last > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
                current_user.current_session_token = None
                db.session.commit()
                logout_user()
                session.clear()
                flash('Tu sesión se cerró por inactividad.', 'warning')
                return redirect(url_for('login'))
        except Exception:
            session.clear()
            logout_user()
            flash('Tu sesión expiró. Iniciá sesión nuevamente.', 'warning')
            return redirect(url_for('login'))
    token = session.get('session_token')
    if not token or current_user.current_session_token != token:
        logout_user()
        session.clear()
        flash('Esta cuenta inició sesión en otro dispositivo. Por seguridad se cerró esta sesión.', 'warning')
        return redirect(url_for('login'))
    session['last_activity_at'] = now.isoformat()
    current_user.last_seen_at = now
    db.session.commit()

@app.route('/')
def public_home():
    events = ChurchEvent.query.filter_by(active=True).order_by(ChurchEvent.created_at.desc()).limit(6).all()
    instagram_posts = fetch_instagram_posts()
    return render_template('home.html', events=events, instagram_posts=instagram_posts)


@app.route('/gratitud')
def gratitude():
    return render_template('gratitude.html')

@app.route('/celulas')
def public_cells():
    q = (request.args.get('q') or '').strip()
    cells = Cell.query.filter_by(status='active')
    if q:
        like = f'%{q}%'
        cells = cells.filter(db.or_(Cell.barrio.ilike(like), Cell.barrio_other.ilike(like), Cell.name.ilike(like), Cell.address.ilike(like), Cell.day.ilike(like)))
    cells = cells.order_by(Cell.name.asc()).all()
    return render_template('public_cells.html', cells=cells, q=q)

@app.route('/api/nearby')
def api_nearby():
    try:
        lat = float(request.args.get('lat'))
        lng = float(request.args.get('lng'))
    except Exception:
        return jsonify({'ok': False, 'message': 'Ubicación inválida.'}), 400
    rows=[]
    for c in Cell.query.filter_by(status='active').all():
        if c.latitude is None or c.longitude is None: continue
        km = distance_km(lat, lng, c.latitude, c.longitude)
        rows.append({'id':c.id,'name':c.name,'barrio':display_barrio(c),'leader':c.leader.name if c.leader else 'Por asignar','day':c.day,'time':c.time,'address':c.address,'phone':c.phone or (c.leader.phone if c.leader else ''),'whatsapp_url':wa_link(c.phone or (c.leader.phone if c.leader else ''), c.name),'maps':c.google_maps_url,'waze':c.waze_url,'description':c.description or 'Célula disponible para integrarte.','distance_km':round(km,2),'distance_label':f'{int(km*1000)} m' if km < 1 else f'{km:.1f} km'})
    rows.sort(key=lambda x:x['distance_km'])
    return jsonify({'ok': True, 'cells': rows[:12]})

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').lower().strip()
        password = request.form.get('password') or ''
        user = User.query.filter_by(username=username).first()
        if not user or not user.active or not user.check_password(password):
            flash('Credenciales incorrectas o usuario inactivo.', 'danger')
            return redirect(url_for('login'))
        token = secrets.token_urlsafe(32)
        user.current_session_token = token
        user.last_seen_at = datetime.utcnow()
        db.session.commit()
        session.clear()
        session['session_token'] = token
        session['last_activity_at'] = datetime.utcnow().isoformat()
        login_user(user)
        if user.role in ['admin', 'mentor']: return redirect(url_for('admin_dashboard'))
        return redirect(url_for('leader_dashboard'))
    return render_template('auth/login.html')

@app.route('/logout')
@login_required
def logout():
    if current_user.is_authenticated:
        current_user.current_session_token = None
        db.session.commit()
    logout_user(); session.clear(); flash('Sesión cerrada correctamente.', 'success'); return redirect(url_for('public_home'))


@app.route('/account/password', methods=['GET','POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current = request.form.get('current_password') or ''
        new = request.form.get('new_password') or ''
        confirm = request.form.get('confirm_password') or ''
        if not current_user.check_password(current):
            flash('La contraseña actual no coincide.', 'danger')
            return redirect(url_for('change_password'))
        if len(new) < 8:
            flash('La nueva contraseña debe tener al menos 8 caracteres.', 'danger')
            return redirect(url_for('change_password'))
        if new != confirm:
            flash('La confirmación no coincide.', 'danger')
            return redirect(url_for('change_password'))
        current_user.set_password(new)
        db.session.commit()
        flash('Contraseña actualizada correctamente.', 'success')
        return redirect(url_for('admin_dashboard') if current_user.role in ['admin','mentor'] else url_for('leader_dashboard'))
    return render_template('account/change_password.html')

@app.route('/admin')
@login_required
@manager_required
def admin_dashboard():
    if current_user.role == 'mentor':
        leader_ids = [u.id for u in User.query.filter_by(role='leader', mentor_id=current_user.id).all()]
        cell_query = Cell.query.filter(Cell.leader_id.in_(leader_ids)) if leader_ids else Cell.query.filter(db.text('1=0'))
        leader_count = len(leader_ids)
    else:
        cell_query = Cell.query
        leader_count = User.query.filter_by(role='leader').count()
    stats = {'cells':cell_query.count(),'active':cell_query.filter_by(status='active').count(),'leaders':leader_count,'requests':LeadRequest.query.count()}
    recent = cell_query.order_by(Cell.created_at.desc()).limit(6).all()
    return render_template('admin/dashboard.html', stats=stats, recent=recent)

@app.route('/admin/cells')
@login_required
@manager_required
def admin_cells():
    q = (request.args.get('q') or '').strip().lower()
    sector_filter = (request.args.get('sector') or '').strip()
    status_filter = (request.args.get('status') or '').strip()
    type_filter = (request.args.get('cell_type') or '').strip()
    sort = (request.args.get('sort') or 'sector').strip()
    direction = (request.args.get('dir') or 'asc').strip()

    if current_user.role == 'mentor':
        leader_ids = [u.id for u in User.query.filter_by(role='leader', mentor_id=current_user.id).all()]
        cells = Cell.query.filter(Cell.leader_id.in_(leader_ids)).all() if leader_ids else []
    else:
        cells = Cell.query.all()

    def matches(c):
        if q:
            haystack = ' '.join([
                safe_text(c.name, ''), safe_text(display_barrio(c), ''), safe_text(c.address, ''),
                safe_text(c.day, ''), safe_text(c.time, ''), safe_text(c.status, ''),
                safe_text(c.leader.name if c.leader else '', ''), safe_text(cell_sector_label(c), '')
            ]).lower()
            if q not in haystack:
                return False
        if sector_filter and sector_filter != 'Todos' and cell_sector_label(c) != sector_filter:
            return False
        if status_filter and status_filter != 'Todos' and c.status != status_filter:
            return False
        if type_filter and type_filter != 'Todos' and (c.cell_type or 'adultos') != type_filter:
            return False
        return True

    cells = [c for c in cells if matches(c)]

    def sort_key(c):
        keys = {
            'name': safe_text(c.name, '').lower(),
            'barrio': safe_text(display_barrio(c), '').lower(),
            'leader': safe_text(c.leader.name if c.leader else '', '').lower(),
            'status': safe_text(c.status, '').lower(),
            'type': safe_text(c.cell_type, '').lower(),
            'day': f'{safe_text(c.day, '')} {safe_text(c.time, '')}',
            'sector': cell_sector_label(c),
        }
        return keys.get(sort, keys['sector'])

    cells = sorted(cells, key=sort_key, reverse=(direction == 'desc'))

    grouped = {}
    for sector in SECTORS:
        grouped[sector] = []
    for c in cells:
        grouped.setdefault(cell_sector_label(c), []).append(c)
    grouped = {k:v for k,v in grouped.items() if v}

    sector_generated = None
    if session.get('sector_credentials_message'):
        sector_generated = {
            'sector': session.pop('sector_credentials_sector', ''),
            'body': session.pop('sector_credentials_message', ''),
            'whatsapp_url': session.pop('sector_credentials_whatsapp', '')
        }

    return render_template('admin/cells.html', cells=cells, grouped_cells=grouped, q=q, sector_filter=sector_filter, status_filter=status_filter, type_filter=type_filter, sort=sort, direction=direction, sector_generated=sector_generated)

@app.route('/admin/cells/new', methods=['GET','POST'])
@login_required
@manager_required
def admin_cell_new():
    leaders = User.query.filter_by(role='leader', active=True).order_by(User.name).all()
    if current_user.role == 'mentor':
        leaders = User.query.filter_by(role='leader', active=True, mentor_id=current_user.id).order_by(User.name).all()
    if request.method == 'POST':
        errors = validate_cell_form(request.form)
        if errors:
            for e in errors: flash(e, 'danger')
            return render_template('admin/cell_form.html', cell=None, leaders=leaders)
        c = Cell()
        fill_cell(c, request.form)
        db.session.add(c); db.session.commit()
        flash('Célula creada correctamente.', 'success')
        return redirect(url_for('admin_cells'))
    return render_template('admin/cell_form.html', cell=None, leaders=leaders)

@app.route('/admin/cells/<int:cell_id>/edit', methods=['GET','POST'])
@login_required
@manager_required
def admin_cell_edit(cell_id):
    c = Cell.query.get_or_404(cell_id)
    if not can_manage_cell(c):
        abort(403)
    leaders = User.query.filter_by(role='leader', active=True).order_by(User.name).all()
    if current_user.role == 'mentor':
        leaders = User.query.filter_by(role='leader', active=True, mentor_id=current_user.id).order_by(User.name).all()
    if request.method == 'POST':
        errors = validate_cell_form(request.form)
        if errors:
            for e in errors: flash(e, 'danger')
            return render_template('admin/cell_form.html', cell=c, leaders=leaders)
        fill_cell(c, request.form); db.session.commit(); flash('Célula actualizada.', 'success')
        return redirect(url_for('admin_cells'))
    return render_template('admin/cell_form.html', cell=c, leaders=leaders)

def fill_cell(c, form):
    c.name = form.get('name','').strip()
    c.leader_id = int(form.get('leader_id')) if form.get('leader_id') else None
    c.barrio = safe_text(form.get('barrio',''), '') or 'Otro'
    c.barrio_other = safe_text(form.get('barrio_other',''), '') or None
    c.address = form.get('address','').strip()
    c.day = form.get('day','').strip()
    c.time = form.get('time','').strip()
    c.status = form.get('status','active')
    c.cell_type = form.get('cell_type','adultos') or 'adultos'
    c.has_children_teacher = form.get('has_children_teacher') == 'on'
    # Teléfono y descripción permanecen en base por compatibilidad, pero ya no se usan en la UI.
    c.phone = None
    c.description = None
    c.google_maps_url = form.get('google_maps_url','').strip()
    c.waze_url = form.get('waze_url','').strip()
    lat = form.get('latitude'); lng = form.get('longitude')
    if (not lat or not lng) and c.google_maps_url:
        lat2, lng2 = extract_coords(c.google_maps_url)
        lat = lat or lat2
        lng = lng or lng2
    c.latitude = float(lat) if lat not in [None,''] else None
    c.longitude = float(lng) if lng not in [None,''] else None
    if c.latitude is not None and c.longitude is not None:
        c.google_maps_url = c.google_maps_url or maps_url(c.latitude, c.longitude)
        c.waze_url = c.waze_url or waze_url(c.latitude, c.longitude)


@app.route('/admin/sectors/<path:sector>/credentials', methods=['POST'])
@login_required
@admin_required
def admin_sector_credentials(sector):
    sector = sector if sector in SECTORS else 'Sin sector'
    leaders = User.query.filter_by(role='leader', sector=sector, active=True).order_by(User.name.asc()).all()
    mentor = User.query.filter_by(role='mentor', sector=sector, active=True).order_by(User.name.asc()).first()

    if not leaders:
        flash(f'No hay líderes activos en {sector}.', 'danger')
        return redirect(url_for('admin_cells', sector=sector if sector != 'Sin sector' else ''))

    lines = []
    for leader in leaders:
        digits = clean_phone(leader.phone)
        password = (digits or 'H0sann4') + '!'
        leader.set_password(password)
        leader.current_session_token = None
        lines.append(f'{leader.name}\nUsuario: {leader.username}\nContraseña: {password}')

    db.session.commit()

    mentor_intro = mentor.name.title() if mentor else 'mentor'
    body = (
        f'Hola {mentor_intro}. Bendiciones.\n\n'
        f'Te comparto los accesos actualizados de los líderes de {sector}. '
        f'Por favor ayudanos a hacerlos llegar a cada líder para que pueda ingresar y completar la información de su célula.\n\n'
        f'Acceso: {APP_PUBLIC_URL}/login\n\n'
        + '\n\n'.join(lines) +
        '\n\nMuchas gracias por servir con excelencia.'
    )

    session['sector_credentials_sector'] = sector
    session['sector_credentials_message'] = body
    session['sector_credentials_whatsapp'] = wa_message_link(mentor.phone, body) if mentor and mentor.phone else ''
    flash(f'Mensaje de accesos generado para {sector}. Las contraseñas de esos líderes fueron actualizadas.', 'success')
    return redirect(url_for('admin_cells', sector=sector if sector != 'Sin sector' else ''))


@app.route('/admin/cells/<int:cell_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_cell_delete(cell_id):
    c = Cell.query.get_or_404(cell_id)
    db.session.delete(c)
    db.session.commit()
    flash('Célula eliminada correctamente.', 'success')
    return redirect(url_for('admin_cells'))


@app.route('/admin/leaders', methods=['GET','POST'])
@login_required
@manager_required
def admin_leaders():
    generated = None
    mentors = User.query.filter_by(role='mentor', active=True).order_by(User.name).all() if current_user.role == 'admin' else []
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        username = (request.form.get('username') or '').lower().strip()
        email = (request.form.get('email') or '').lower().strip() or None
        phone_digits = clean_phone(request.form.get('phone',''))
        phone = format_cr_phone(phone_digits) if phone_digits else None
        password = request.form.get('password') or random_password()
        mentor_id = None
        sector = None
        if current_user.role == 'mentor':
            mentor_id = current_user.id
            sector = current_user.sector
        elif request.form.get('mentor_id'):
            mentor = User.query.filter_by(id=int(request.form.get('mentor_id')), role='mentor').first()
            if mentor:
                mentor_id = mentor.id
                sector = mentor.sector
        if not name:
            flash('Nombre es obligatorio.', 'danger'); return redirect(url_for('admin_leaders'))
        if phone_digits and len(phone_digits) != 8:
            flash('El teléfono debe tener 8 dígitos. Ejemplo: 8888-8888.', 'danger'); return redirect(url_for('admin_leaders'))
        username = slug_username(username) if username else unique_username(name)
        if User.query.filter_by(username=username).first():
            flash('Ya existe un usuario con ese nombre de usuario.', 'danger'); return redirect(url_for('admin_leaders'))
        if email and User.query.filter_by(email=email).first():
            flash('Ya existe un usuario con ese correo.', 'danger'); return redirect(url_for('admin_leaders'))
        u = User(name=name, username=username, email=email, phone=phone, role='leader', active=True, sector=sector, mentor_id=mentor_id)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        body = build_credentials_message(u, password)
        generated = {'name':name,'username':username,'email':email,'password':password,'phone':phone,'body':body,'sent':False,'whatsapp_url':wa_message_link(phone, body) if phone else ''}
        if request.form.get('send_sms') == 'on' and phone:
            sent, sms_msg = send_sms(phone, body)
            generated['sent'] = sent
            flash(sms_msg, 'success' if sent else 'warning')
        flash('Líder creado correctamente.', 'success')

    q = (request.args.get('q') or '').strip().lower()
    sector_filter = (request.args.get('sector') or '').strip()
    mentor_filter = request.args.get('mentor_id') or ''
    sort = (request.args.get('sort') or 'name').strip()
    direction = (request.args.get('dir') or 'asc').strip()
    leaders = User.query.filter_by(role='leader').all()
    if current_user.role == 'mentor':
        leaders = [u for u in leaders if u.mentor_id == current_user.id]

    def matches(u):
        if q:
            haystack = ' '.join([safe_text(u.name,''), safe_text(u.username,''), safe_text(u.phone,''), safe_text(u.email,''), safe_text(u.sector,''), safe_text(get_mentor(u).name if get_mentor(u) else '', '')]).lower()
            if q not in haystack:
                return False
        if sector_filter and sector_filter != 'Todos' and user_sector_label(u) != sector_filter:
            return False
        if mentor_filter and str(u.mentor_id or '') != mentor_filter:
            return False
        return True
    leaders = [u for u in leaders if matches(u)]
    def sort_key(u):
        keys = {
            'name': safe_text(u.name,'').lower(),
            'username': safe_text(u.username,'').lower(),
            'sector': user_sector_label(u),
            'mentor': safe_text(get_mentor(u).name if get_mentor(u) else '', '').lower(),
            'phone': safe_text(u.phone,'').lower(),
            'status': '1' if u.active else '0'
        }
        return keys.get(sort, keys['name'])
    leaders = sorted(leaders, key=sort_key, reverse=(direction == 'desc'))
    return render_template('admin/leaders.html', leaders=leaders, mentors=mentors, generated=generated, q=q, sector_filter=sector_filter, mentor_filter=mentor_filter, sort=sort, direction=direction)

@app.route('/admin/leaders/<int:leader_id>/edit', methods=['GET','POST'])
@login_required
@manager_required
def admin_leader_edit(leader_id):
    u = User.query.get_or_404(leader_id)
    if not can_manage_leader(u) or u.role != 'leader':
        abort(403)
    mentors = User.query.filter_by(role='mentor', active=True).order_by(User.name).all() if current_user.role == 'admin' else []
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        username = slug_username(request.form.get('username',''))
        email = (request.form.get('email') or '').lower().strip() or None
        phone_digits = clean_phone(request.form.get('phone',''))
        phone = format_cr_phone(phone_digits) if phone_digits else None
        mentor_id = u.mentor_id
        sector = u.sector
        if current_user.role == 'admin':
            if request.form.get('mentor_id'):
                mentor = User.query.filter_by(id=int(request.form.get('mentor_id')), role='mentor').first()
                mentor_id = mentor.id if mentor else None
                sector = mentor.sector if mentor else None
            else:
                mentor_id = None
                sector = None
        active = request.form.get('active') == 'on'
        password = request.form.get('password') or ''
        if not name:
            flash('Nombre es obligatorio.', 'danger'); return redirect(url_for('admin_leader_edit', leader_id=u.id))
        if not username:
            flash('Usuario es obligatorio.', 'danger'); return redirect(url_for('admin_leader_edit', leader_id=u.id))
        if User.query.filter(User.username == username, User.id != u.id).first():
            flash('Ese usuario ya está en uso.', 'danger'); return redirect(url_for('admin_leader_edit', leader_id=u.id))
        if email and User.query.filter(User.email == email, User.id != u.id).first():
            flash('Ese correo ya está en uso.', 'danger'); return redirect(url_for('admin_leader_edit', leader_id=u.id))
        if phone_digits and len(phone_digits) != 8:
            flash('El teléfono debe tener 8 dígitos. Ejemplo: 8888-8888.', 'danger'); return redirect(url_for('admin_leader_edit', leader_id=u.id))
        u.name = name; u.username = username; u.email = email; u.phone = phone; u.active = active; u.mentor_id = mentor_id; u.sector = sector
        if password:
            if len(password) < 8:
                flash('La nueva contraseña debe tener al menos 8 caracteres.', 'danger'); return redirect(url_for('admin_leader_edit', leader_id=u.id))
            u.set_password(password); u.current_session_token = None
        db.session.commit()
        flash('Líder actualizado correctamente.', 'success')
        return redirect(url_for('admin_leaders'))
    return render_template('admin/leader_edit.html', leader=u, mentors=mentors)

@app.route('/admin/leaders/<int:leader_id>/credentials', methods=['POST'])
@login_required
@admin_required
def admin_leader_credentials(leader_id):
    u = User.query.get_or_404(leader_id)
    if u.role != 'leader':
        abort(403)
    password = random_password()
    u.set_password(password)
    db.session.commit()
    body = build_credentials_message(u, password)
    generated = {'name':u.name,'username':u.username,'email':u.email,'password':password,'phone':u.phone,'body':body,'sent':False,'whatsapp_url':wa_message_link(u.phone, body) if u.phone else ''}
    flash('Credenciales generadas nuevamente. La contraseña anterior fue reemplazada.', 'success')
    leaders = User.query.filter_by(role='leader').order_by(User.created_at.desc()).all()
    mentors = User.query.filter_by(role='mentor', active=True).order_by(User.name).all()
    return render_template('admin/leaders.html', leaders=leaders, mentors=mentors, generated=generated, q='', sector_filter='', mentor_filter='', sort='name', direction='asc')

@app.route('/admin/leaders/<int:leader_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_leader_delete(leader_id):
    u = User.query.get_or_404(leader_id)
    if u.role != 'leader':
        abort(403)
    Cell.query.filter_by(leader_id=u.id).update({'leader_id': None})
    db.session.delete(u)
    db.session.commit()
    flash('Líder eliminado correctamente. Sus células quedaron sin líder asignado.', 'success')
    return redirect(url_for('admin_leaders'))

@app.route('/admin/mentors', methods=['GET','POST'])
@login_required
@admin_required
def admin_mentors():
    generated = None
    if request.method == 'POST':
        action = request.form.get('action') or 'assign'
        if action == 'create':
            name = request.form.get('name','').strip()
            username = (request.form.get('username') or '').lower().strip()
            email = (request.form.get('email') or '').lower().strip() or None
            phone_digits = clean_phone(request.form.get('phone',''))
            phone = format_cr_phone(phone_digits) if phone_digits else None
            sector = normalize_sector(request.form.get('sector'))
            password = request.form.get('password') or random_password()
            if not name:
                flash('Nombre del mentor es obligatorio.', 'danger'); return redirect(url_for('admin_mentors'))
            if phone_digits and len(phone_digits) != 8:
                flash('El teléfono debe tener 8 dígitos. Ejemplo: 8888-8888.', 'danger'); return redirect(url_for('admin_mentors'))
            username = slug_username(username) if username else unique_username(name)
            if User.query.filter_by(username=username).first():
                flash('Ya existe un usuario con ese nombre de usuario.', 'danger'); return redirect(url_for('admin_mentors'))
            if email and User.query.filter_by(email=email).first():
                flash('Ya existe un usuario con ese correo.', 'danger'); return redirect(url_for('admin_mentors'))
            mentor = User(name=name, username=username, email=email, phone=phone, role='mentor', active=True, sector=sector)
            mentor.set_password(password)
            db.session.add(mentor); db.session.commit()
            body = build_credentials_message(mentor, password)
            generated = {'name':name,'username':username,'email':email,'password':password,'phone':phone,'body':body,'sent':False,'whatsapp_url':wa_message_link(phone, body) if phone else ''}
            flash('Mentor creado correctamente.', 'success')
        else:
            mentor_id = request.form.get('mentor_id')
            leader_ids = request.form.getlist('leader_ids')
            if not leader_ids:
                flash('Seleccioná al menos un líder.', 'danger'); return redirect(url_for('admin_mentors'))
            leaders = User.query.filter(User.id.in_([int(x) for x in leader_ids]), User.role == 'leader').all()
            if mentor_id:
                mentor = User.query.filter_by(id=int(mentor_id), role='mentor').first_or_404()
                for leader in leaders:
                    leader.mentor_id = mentor.id
                    leader.sector = mentor.sector
                flash(f'{len(leaders)} líder(es) asignados a {mentor.name}.', 'success')
            else:
                for leader in leaders:
                    leader.mentor_id = None
                    leader.sector = None
                flash(f'{len(leaders)} líder(es) quedaron sin mentor y sin sector.', 'success')
            db.session.commit()
            return redirect(url_for('admin_mentors'))

    q = (request.args.get('q') or '').strip().lower()
    sector_filter = (request.args.get('sector') or '').strip()
    mentor_filter = request.args.get('mentor_id') or ''
    sort = (request.args.get('sort') or 'sector').strip()
    direction = (request.args.get('dir') or 'asc').strip()
    mentors = User.query.filter_by(role='mentor').order_by(User.name.asc()).all()
    leaders = User.query.filter_by(role='leader').all()
    def matches(u):
        if q:
            haystack = ' '.join([safe_text(u.name,''), safe_text(u.username,''), safe_text(u.phone,''), safe_text(u.sector,''), safe_text(get_mentor(u).name if get_mentor(u) else '', '')]).lower()
            if q not in haystack: return False
        if sector_filter and sector_filter != 'Todos' and user_sector_label(u) != sector_filter: return False
        if mentor_filter and str(u.mentor_id or '') != mentor_filter: return False
        return True
    leaders = [u for u in leaders if matches(u)]
    def sort_key(u):
        keys = {'name':safe_text(u.name,'').lower(),'username':safe_text(u.username,'').lower(),'sector':user_sector_label(u),'mentor':safe_text(get_mentor(u).name if get_mentor(u) else '', '').lower(),'cell':safe_text(u.cells[0].name if u.cells else '', '').lower()}
        return keys.get(sort, keys['sector'])
    leaders = sorted(leaders, key=sort_key, reverse=(direction == 'desc'))
    grouped = {}
    for leader in leaders:
        grouped.setdefault(user_sector_label(leader), []).append(leader)
    mentor_counts = {m.id: User.query.filter_by(role='leader', mentor_id=m.id).count() for m in mentors}
    return render_template('admin/mentors.html', mentors=mentors, leaders=leaders, grouped_leaders=grouped, mentor_counts=mentor_counts, generated=generated, q=q, sector_filter=sector_filter, mentor_filter=mentor_filter, sort=sort, direction=direction)

@app.route('/admin/mentors/<int:mentor_id>/edit', methods=['GET','POST'])
@login_required
@admin_required
def admin_mentor_edit(mentor_id):
    mentor = User.query.get_or_404(mentor_id)
    if mentor.role != 'mentor': abort(403)
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        username = slug_username(request.form.get('username',''))
        email = (request.form.get('email') or '').lower().strip() or None
        phone_digits = clean_phone(request.form.get('phone',''))
        phone = format_cr_phone(phone_digits) if phone_digits else None
        sector = normalize_sector(request.form.get('sector'))
        active = request.form.get('active') == 'on'
        password = request.form.get('password') or ''
        if not name or not username:
            flash('Nombre y usuario son obligatorios.', 'danger'); return redirect(url_for('admin_mentor_edit', mentor_id=mentor.id))
        if User.query.filter(User.username == username, User.id != mentor.id).first():
            flash('Ese usuario ya está en uso.', 'danger'); return redirect(url_for('admin_mentor_edit', mentor_id=mentor.id))
        if email and User.query.filter(User.email == email, User.id != mentor.id).first():
            flash('Ese correo ya está en uso.', 'danger'); return redirect(url_for('admin_mentor_edit', mentor_id=mentor.id))
        if phone_digits and len(phone_digits) != 8:
            flash('El teléfono debe tener 8 dígitos. Ejemplo: 8888-8888.', 'danger'); return redirect(url_for('admin_mentor_edit', mentor_id=mentor.id))
        old_sector = mentor.sector
        mentor.name=name; mentor.username=username; mentor.email=email; mentor.phone=phone; mentor.sector=sector; mentor.active=active
        if password:
            if len(password) < 8:
                flash('La nueva contraseña debe tener al menos 8 caracteres.', 'danger'); return redirect(url_for('admin_mentor_edit', mentor_id=mentor.id))
            mentor.set_password(password); mentor.current_session_token = None
        if old_sector != sector:
            for leader in User.query.filter_by(role='leader', mentor_id=mentor.id).all():
                leader.sector = sector
        db.session.commit()
        flash('Mentor actualizado correctamente.', 'success')
        return redirect(url_for('admin_mentors'))
    return render_template('admin/mentor_edit.html', mentor=mentor)

@app.route('/admin/mentors/<int:mentor_id>/credentials', methods=['POST'])
@login_required
@admin_required
def admin_mentor_credentials(mentor_id):
    mentor = User.query.get_or_404(mentor_id)
    if mentor.role != 'mentor': abort(403)
    password = random_password()
    mentor.set_password(password)
    db.session.commit()
    body = build_credentials_message(mentor, password)
    generated = {'name':mentor.name,'username':mentor.username,'email':mentor.email,'password':password,'phone':mentor.phone,'body':body,'sent':False,'whatsapp_url':wa_message_link(mentor.phone, body) if mentor.phone else ''}
    flash('Credenciales del mentor generadas nuevamente.', 'success')
    mentors = User.query.filter_by(role='mentor').order_by(User.name.asc()).all()
    leaders = User.query.filter_by(role='leader').all()
    mentor_counts = {m.id: User.query.filter_by(role='leader', mentor_id=m.id).count() for m in mentors}
    return render_template('admin/mentors.html', mentors=mentors, leaders=leaders, grouped_leaders={}, mentor_counts=mentor_counts, generated=generated, q='', sector_filter='', mentor_filter='', sort='sector', direction='asc')

@app.route('/admin/mentors/<int:mentor_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_mentor_delete(mentor_id):
    mentor = User.query.get_or_404(mentor_id)
    if mentor.role != 'mentor': abort(403)
    for leader in User.query.filter_by(role='leader', mentor_id=mentor.id).all():
        leader.mentor_id = None
        leader.sector = None
    db.session.delete(mentor)
    db.session.commit()
    flash('Mentor eliminado. Sus líderes quedaron sin mentor y sin sector.', 'success')
    return redirect(url_for('admin_mentors'))

@app.route('/admin/events', methods=['GET','POST'])
@login_required
@admin_required
def admin_events():
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        if not title:
            flash('El nombre del evento es obligatorio.', 'danger')
            return redirect(url_for('admin_events'))
        event = ChurchEvent(
            title=title,
            event_date=(request.form.get('event_date') or '').strip(),
            event_time=(request.form.get('event_time') or '').strip(),
            image_url=(request.form.get('image_url') or '').strip(),
            description=(request.form.get('description') or '').strip(),
            location=(request.form.get('location') or '').strip(),
            active=request.form.get('active') == 'on'
        )
        db.session.add(event)
        db.session.commit()
        flash('Evento creado correctamente.', 'success')
        return redirect(url_for('admin_events'))
    events = ChurchEvent.query.order_by(ChurchEvent.created_at.desc()).all()
    return render_template('admin/events.html', events=events)

@app.route('/admin/events/<int:event_id>/edit', methods=['GET','POST'])
@login_required
@admin_required
def admin_event_edit(event_id):
    event = ChurchEvent.query.get_or_404(event_id)
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        if not title:
            flash('El nombre del evento es obligatorio.', 'danger')
            return redirect(url_for('admin_event_edit', event_id=event.id))
        event.title = title
        event.event_date = (request.form.get('event_date') or '').strip()
        event.event_time = (request.form.get('event_time') or '').strip()
        event.image_url = (request.form.get('image_url') or '').strip()
        event.description = (request.form.get('description') or '').strip()
        event.location = (request.form.get('location') or '').strip()
        event.active = request.form.get('active') == 'on'
        db.session.commit()
        flash('Evento actualizado correctamente.', 'success')
        return redirect(url_for('admin_events'))
    return render_template('admin/event_edit.html', event=event)

@app.route('/admin/events/<int:event_id>/toggle', methods=['POST'])
@login_required
@admin_required
def admin_event_toggle(event_id):
    event = ChurchEvent.query.get_or_404(event_id)
    event.active = not event.active
    db.session.commit()
    flash('Estado del evento actualizado.', 'success')
    return redirect(url_for('admin_events'))

@app.route('/admin/events/<int:event_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_event_delete(event_id):
    event = ChurchEvent.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    flash('Evento eliminado correctamente.', 'success')
    return redirect(url_for('admin_events'))

@app.route('/leader')
@login_required
@leader_required
def leader_dashboard():
    c = Cell.query.filter_by(leader_id=current_user.id).first() if current_user.role=='leader' else None
    if current_user.role in ['admin','mentor']: return redirect(url_for('admin_dashboard'))
    mentor = get_mentor(current_user)
    return render_template('leader/dashboard.html', cell=c, mentor=mentor)

@app.route('/leader/cell/update', methods=['POST'])
@login_required
@leader_required
def leader_cell_update():
    c = Cell.query.filter_by(leader_id=current_user.id).first_or_404()
    allowed = ['address','day','time','google_maps_url','waze_url','latitude','longitude','cell_type']
    for k in allowed:
        if k in request.form:
            val = request.form.get(k)
            if k in ['latitude','longitude']:
                setattr(c,k,float(val) if val else None)
            else: setattr(c,k,val.strip())
    c.has_children_teacher = request.form.get('has_children_teacher') == 'on'
    if c.latitude is not None and c.longitude is not None:
        c.google_maps_url = maps_url(c.latitude,c.longitude); c.waze_url = waze_url(c.latitude,c.longitude)
    db.session.commit(); flash('Información actualizada.', 'success'); return redirect(url_for('leader_dashboard'))

@app.route('/api/resolve-maps-url', methods=['POST'])
@login_required
def api_resolve_maps_url():
    if current_user.role not in ['admin', 'mentor', 'leader']:
        abort(403)
    data = request.get_json(silent=True) or {}
    raw_url = (data.get('url') or '').strip()
    if not raw_url:
        return jsonify({'ok': False, 'message': 'Pegá primero un link de Google Maps.'}), 400
    try:
        lat, lng, resolved_url = resolve_google_maps_link(raw_url)
    except Exception as exc:
        return jsonify({'ok': False, 'message': str(exc)}), 400
    return jsonify({
        'ok': True,
        'latitude': round(float(lat), 7),
        'longitude': round(float(lng), 7),
        'maps': maps_url(lat, lng),
        'waze': waze_url(lat, lng),
        'resolved_url': resolved_url,
        'message': 'Ubicación extraída del link. Guardá los cambios para aplicarla.'
    })


@app.route('/api/cells/<int:cell_id>/location', methods=['POST'])
@login_required
def api_update_location(cell_id):
    c = Cell.query.get_or_404(cell_id)
    if not (current_user.role == 'admin' or c.leader_id == current_user.id or can_manage_cell(c)): abort(403)
    data = request.get_json(silent=True) or {}
    try: lat=float(data.get('latitude')); lng=float(data.get('longitude'))
    except Exception: return jsonify({'ok':False,'message':'Ubicación inválida.'}),400
    c.latitude=lat; c.longitude=lng; c.google_maps_url=maps_url(lat,lng); c.waze_url=waze_url(lat,lng); db.session.commit()
    return jsonify({'ok':True,'message':'Ubicación guardada.','maps':c.google_maps_url,'waze':c.waze_url})



def _no_accents_upper(value):
    value = safe_text(value, '')
    value = unicodedata.normalize('NFD', value)
    value = ''.join(ch for ch in value if unicodedata.category(ch) != 'Mn')
    return value.upper().strip()

def _norm_key(value):
    value = safe_text(value, '')
    value = unicodedata.normalize('NFD', value)
    value = ''.join(ch for ch in value if unicodedata.category(ch) != 'Mn')
    value = value.upper()
    value = re.sub(r'[^A-Z0-9]+', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()

def _import_username(prefix, name):
    base = slug_username(f'{prefix}.{name}')
    return unique_username(base)

def _find_user_by_phone_or_name(role, name, phone):
    phone_digits = clean_phone(phone)
    users = User.query.filter_by(role=role).all()
    if phone_digits:
        for user in users:
            if clean_phone(user.phone) == phone_digits:
                return user
    target = _norm_key(name)
    if target:
        for user in users:
            if _norm_key(user.name) == target:
                return user
        for user in users:
            existing = _norm_key(user.name)
            if existing and (target in existing or existing in target):
                return user
    return None

def _infer_barrio_from_address(address):
    raw = safe_text(address, '')
    normalized = _norm_key(raw)
    aliases = [
        ('CORAZON DE JESUS', 'Corazón de Jesús'),
        ('LOS ANGELES', 'Barrio Los Ángeles'),
        ('LA GUARIA', 'La Guaria'),
        ('GUARIA', 'La Guaria'),
        ('MORACIA', 'Moracia'),
        ('SAN ROQUE', 'San Roque'),
        ('FELIPE PEREZ', 'Felipe Pérez'),
        ('PELÓNCITO', 'El Peloncito'),
        ('PELONCITO', 'El Peloncito'),
        ('PUEBLO NUEVO', 'Pueblo Nuevo'),
        ('LA VICTORIA', 'La Victoria'),
        ('VICTORIA', 'La Victoria'),
        ('CHOROTEGA', 'Chorotega'),
        ('LA GALLERA', 'La Gallera'),
        ('INVU', 'INVU'),
        ('DANIEL ODUBER', 'Daniel Oduber'),
        ('RIO', 'Residencial Río'),
        ('RESIDENCIAL DEL RIO', 'Residencial Río'),
        ('RESIDENCIAL RIO', 'Residencial Río'),
        ('SANTA LUISA', 'Santa Luisa'),
        ('LOS ALMENDRALES', 'Los Almendrales'),
        ('NAZARET', 'Nazareth'),
        ('NAZARETH', 'Nazareth'),
        ('BARRIO LA CRUZ', 'La Cruz'),
        ('LA CRUZ', 'La Cruz'),
        ('CAMBALACHE', 'El Cambalache'),
        ('LINDA VISTA', 'Linda Vista'),
        ('PIJIJE', 'Pijije'),
        ('CANAS', 'Cañas'),
        ('SANTA CRUZ', 'Santa Cruz'),
        ('BELEN', 'Belén'),
        ('LOMA BONITA', 'Loma Bonita'),
        ('ANTIGUA HULERA', 'Antigua Hulera'),
        ('EL GALLO', 'El Gallo'),
    ]
    for needle, label in aliases:
        if needle in normalized:
            if label in BARRIOS_LIBERIA:
                return label, None, label
            return 'Otro', label, label
    for barrio in BARRIOS_LIBERIA:
        if barrio != 'Otro' and _norm_key(barrio) in normalized:
            return barrio, None, barrio
    return 'Otro', None, 'Barrio por definir'

def _normalize_day(value):
    v = _norm_key(value)
    if 'LUNES' in v: return 'Lunes'
    if 'MARTES' in v: return 'Martes'
    if 'MIERCOLES' in v: return 'Miércoles'
    if 'JUEVES' in v: return 'Jueves'
    if 'VIERNES' in v: return 'Viernes'
    if 'SABADO' in v: return 'Sábado'
    if 'DOMINGO' in v: return 'Domingo'
    return ''

@app.cli.command('import-mentor-sectors')
def import_mentor_sectors():
    """Importación única de mentores, sectores y asignación de líderes/células.
    Lee data/mentor_sector_assignments.csv. No usar init-db en producción.
    """
    data_path = os.path.join(app.root_path, 'data', 'mentor_sector_assignments.csv')
    if not os.path.exists(data_path):
        raise RuntimeError(f'No existe el archivo de importación: {data_path}')

    created_mentors = updated_mentors = created_leaders = updated_leaders = created_cells = updated_cells = 0
    unmatched_without_phone = []

    with open(data_path, newline='', encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))

    for row in rows:
        sector = normalize_sector(row.get('sector'))
        mentor_name = _no_accents_upper(row.get('mentor_name'))
        mentor_phone_digits = clean_phone(row.get('mentor_phone'))
        mentor_phone = format_cr_phone(mentor_phone_digits) if mentor_phone_digits else None
        if not sector or not mentor_name:
            continue

        mentor = _find_user_by_phone_or_name('mentor', mentor_name, mentor_phone_digits)
        if not mentor:
            mentor = User(
                name=mentor_name,
                username=_import_username('mentor', mentor_name),
                email=None,
                phone=mentor_phone,
                role='mentor',
                active=True,
                sector=sector
            )
            mentor.set_password((mentor_phone_digits or 'H0sann4') + '***')
            db.session.add(mentor)
            db.session.flush()
            created_mentors += 1
        else:
            mentor.name = mentor_name
            mentor.phone = mentor.phone or mentor_phone
            mentor.role = 'mentor'
            mentor.active = True
            mentor.sector = sector
            updated_mentors += 1

        leader_name_raw = safe_text(row.get('leader_name'), '')
        leader_phone_digits = clean_phone(row.get('leader_phone'))
        leader_phone = format_cr_phone(leader_phone_digits) if leader_phone_digits else None
        if not leader_name_raw:
            continue

        leader = _find_user_by_phone_or_name('leader', leader_name_raw, leader_phone_digits)
        if not leader:
            leader = User(
                name=_no_accents_upper(leader_name_raw),
                username=_import_username('lider', leader_name_raw),
                email=None,
                phone=leader_phone,
                role='leader',
                active=True,
                sector=sector,
                mentor_id=mentor.id
            )
            leader.set_password((leader_phone_digits or 'H0sann4') + '!')
            db.session.add(leader)
            db.session.flush()
            created_leaders += 1
            if not leader_phone_digits:
                unmatched_without_phone.append(leader_name_raw)
        else:
            leader.mentor_id = mentor.id
            leader.sector = sector
            leader.role = 'leader'
            leader.active = True
            if leader_phone and not leader.phone:
                leader.phone = leader_phone
            updated_leaders += 1

        address = safe_text(row.get('address'), '')
        day = _normalize_day(row.get('day'))
        barrio, barrio_other, barrio_label = _infer_barrio_from_address(address)
        cell_name = f'Célula | {barrio_label}'
        status = 'paused' if not address or not day else None

        cell = Cell.query.filter_by(leader_id=leader.id).order_by(Cell.id.asc()).first()
        if not cell:
            cell = Cell(
                name=cell_name,
                leader_id=leader.id,
                barrio=barrio,
                barrio_other=barrio_other,
                address=address or 'Por definir',
                day=day or 'Por definir',
                time='19:00',
                phone=None,
                description=None,
                status=status or 'paused',
                cell_type='adultos',
                has_children_teacher=False
            )
            db.session.add(cell)
            created_cells += 1
        else:
            cell.name = cell_name
            cell.leader_id = leader.id
            cell.barrio = barrio
            cell.barrio_other = barrio_other
            if address:
                cell.address = address
            if day:
                cell.day = day
            if not cell.time or str(cell.time).lower() in ['none', 'por definir']:
                cell.time = '19:00'
            cell.phone = None
            cell.description = None
            if status:
                cell.status = 'paused'
            updated_cells += 1

    db.session.commit()
    print('Importación de mentores y sectores completada.')
    print(f'Mentores creados: {created_mentors} | actualizados: {updated_mentors}')
    print(f'Líderes creados: {created_leaders} | actualizados/asignados: {updated_leaders}')
    print(f'Células creadas: {created_cells} | actualizadas: {updated_cells}')
    if unmatched_without_phone:
        print('Líderes creados sin teléfono por no poder comparar con usuarios existentes:')
        for name in unmatched_without_phone:
            print(f'- {name}')

@app.cli.command('init-db')
def init_db():
    db.drop_all(); db.create_all(); print('Base reiniciada.')

@app.cli.command('upgrade-db')
def upgrade_db():
    db.create_all()
    from sqlalchemy import text
    engine_name = db.engine.url.get_backend_name()
    with db.engine.begin() as conn:
        if engine_name.startswith('postgresql'):
            conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS current_session_token VARCHAR(120)'))
            conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP'))
            conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS sector VARCHAR(40)'))
            conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS mentor_id INTEGER'))
            conn.execute(text("ALTER TABLE cell ADD COLUMN IF NOT EXISTS cell_type VARCHAR(20) DEFAULT 'adultos'"))
            conn.execute(text('ALTER TABLE cell ADD COLUMN IF NOT EXISTS has_children_teacher BOOLEAN DEFAULT FALSE'))
            conn.execute(text("UPDATE cell SET cell_type='adultos' WHERE cell_type IS NULL"))
            conn.execute(text("UPDATE cell SET has_children_teacher=FALSE WHERE has_children_teacher IS NULL"))
        else:
            cols = [r[1] for r in conn.execute(text('PRAGMA table_info(user)')).fetchall()]
            if 'current_session_token' not in cols:
                conn.execute(text('ALTER TABLE user ADD COLUMN current_session_token VARCHAR(120)'))
            if 'last_seen_at' not in cols:
                conn.execute(text('ALTER TABLE user ADD COLUMN last_seen_at TIMESTAMP'))
            if 'sector' not in cols:
                conn.execute(text('ALTER TABLE user ADD COLUMN sector VARCHAR(40)'))
            if 'mentor_id' not in cols:
                conn.execute(text('ALTER TABLE user ADD COLUMN mentor_id INTEGER'))
            cell_cols = [r[1] for r in conn.execute(text('PRAGMA table_info(cell)')).fetchall()]
            if 'cell_type' not in cell_cols:
                conn.execute(text("ALTER TABLE cell ADD COLUMN cell_type VARCHAR(20) DEFAULT 'adultos'"))
            if 'has_children_teacher' not in cell_cols:
                conn.execute(text('ALTER TABLE cell ADD COLUMN has_children_teacher BOOLEAN DEFAULT 0'))
    print('Base actualizada.')

@app.cli.command('ensure-admin')
def ensure_admin():
    reset = (os.getenv('ADMIN_RESET_ON_DEPLOY', '').lower() in ['1','true','yes','on'])
    ensure_admin_user(reset_password=reset)
    ensure_mentor_user(reset_password=reset)
    print('Admin verificado correctamente.' + (' Contraseña actualizada.' if reset else ''))

@app.cli.command('reset-admin-password')
def reset_admin_password():
    ensure_admin_user(reset_password=True)
    print('Contraseña del admin actualizada desde ADMIN_PASSWORD.')

@app.cli.command('seed')
def seed():
    """Datos mínimos: solo asegura admin. No crea líderes/células demo en producción."""
    ensure_admin_user(reset_password=False)
    ensure_mentor_user(reset_password=False)
    print('Seed mínimo completado: admin/mentor verificados.')


@app.cli.command('migrate-usernames')
def migrate_usernames():
    """Actualiza bases existentes: agrega username y hace email opcional."""
    from sqlalchemy import text
    engine_name = db.engine.url.get_backend_name()
    with db.engine.begin() as conn:
        if engine_name.startswith('postgresql'):
            conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS username VARCHAR(80)'))
            rows = conn.execute(text('SELECT id, name, email, username FROM "user" ORDER BY id')).mappings().all()
            used = set()
            existing = conn.execute(text('SELECT username FROM "user" WHERE username IS NOT NULL')).scalars().all()
            used.update([x for x in existing if x])
            for row in rows:
                if row['username']:
                    continue
                base = slug_username((row['email'] or '').split('@')[0] or row['name'] or f'user{row["id"]}')
                candidate = base
                i = 2
                while candidate in used:
                    candidate = f'{base}{i}'[:80]
                    i += 1
                used.add(candidate)
                conn.execute(text('UPDATE "user" SET username=:username WHERE id=:id'), {'username': candidate, 'id': row['id']})
            conn.execute(text('ALTER TABLE "user" ALTER COLUMN username SET NOT NULL'))
            conn.execute(text('ALTER TABLE "user" ALTER COLUMN email DROP NOT NULL'))
            conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ix_user_username_unique ON "user" (username)'))
        else:
            cols = [r[1] for r in conn.execute(text('PRAGMA table_info(user)')).fetchall()]
            if 'username' not in cols:
                conn.execute(text('ALTER TABLE user ADD COLUMN username VARCHAR(80)'))
            rows = conn.execute(text('SELECT id, name, email, username FROM user ORDER BY id')).mappings().all()
            used = set([r['username'] for r in rows if r['username']])
            for row in rows:
                if row['username']:
                    continue
                base = slug_username((row['email'] or '').split('@')[0] or row['name'] or f'user{row["id"]}')
                candidate = base
                i = 2
                while candidate in used:
                    candidate = f'{base}{i}'[:80]
                    i += 1
                used.add(candidate)
                conn.execute(text('UPDATE user SET username=:username WHERE id=:id'), {'username': candidate, 'id': row['id']})
    print('Migración de usuarios completada.')



# Importación masiva removida después de ejecutar la carga inicial en producción.
# Los datos importados permanecen en PostgreSQL.

@app.errorhandler(403)
def e403(e): return render_template('errors/error.html', code=403, title='Acceso restringido', message='No tenés permiso para entrar a esta sección.'),403
@app.errorhandler(404)
def e404(e): return render_template('errors/error.html', code=404, title='Página no encontrada', message='La ruta que intentaste abrir no existe.'),404
@app.errorhandler(500)
def e500(e): return render_template('errors/error.html', code=500, title='Algo falló', message='El sistema tuvo un error inesperado.'),500

if __name__ == '__main__': app.run(debug=True)

def build_credentials_message(user, password):
    login_link = APP_PUBLIC_URL + url_for('login')
    return (
        f'Hola {user.name}. Bienvenido al equipo de líderes de Iglesia Hosanna.\n\n'
        f'Acceso:\n{login_link}\n\n'
        f'Usuario:\n{user.username}\n\n'
        f'Contraseña:\n{password}'
    )

