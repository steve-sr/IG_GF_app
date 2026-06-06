import os, re, math, secrets, string
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

APP_PUBLIC_URL = os.getenv('APP_BASE_URL') or os.getenv('APP_PUBLIC_URL') or 'https://celulas.hosannaigle.com'
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
    patterns = [r'@(-?\d+\.\d+),(-?\d+\.\d+)', r'q=(-?\d+\.\d+),(-?\d+\.\d+)', r'query=(-?\d+\.\d+),(-?\d+\.\d+)']
    for p in patterns:
        m = re.search(p, text)
        if m: return float(m.group(1)), float(m.group(2))
    nums = re.findall(r'-?\d+\.\d+', text)
    if len(nums) >= 2:
        lat, lng = float(nums[0]), float(nums[1])
        if -90 <= lat <= 90 and -180 <= lng <= 180: return lat, lng
    return None, None

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
    return dict(DAYS=DAYS, HOURS=HOURS, BARRIOS_LIBERIA=BARRIOS_LIBERIA, APP_PUBLIC_URL=APP_PUBLIC_URL, wa_link=wa_link, is_admin=is_admin, is_manager=is_manager)


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
        rows.append({'id':c.id,'name':c.name,'barrio':c.barrio_other or c.barrio,'leader':c.leader.name if c.leader else 'Por asignar','day':c.day,'time':c.time,'address':c.address,'phone':c.phone or (c.leader.phone if c.leader else ''),'whatsapp_url':wa_link(c.phone or (c.leader.phone if c.leader else ''), c.name),'maps':c.google_maps_url,'waze':c.waze_url,'description':c.description or 'Célula disponible para integrarte.','distance_km':round(km,2),'distance_label':f'{int(km*1000)} m' if km < 1 else f'{km:.1f} km'})
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
    stats = {'cells':Cell.query.count(),'active':Cell.query.filter_by(status='active').count(),'leaders':User.query.filter_by(role='leader').count(),'requests':LeadRequest.query.count()}
    recent = Cell.query.order_by(Cell.created_at.desc()).limit(6).all()
    return render_template('admin/dashboard.html', stats=stats, recent=recent)

@app.route('/admin/cells')
@login_required
@manager_required
def admin_cells():
    return render_template('admin/cells.html', cells=Cell.query.order_by(Cell.created_at.desc()).all())

@app.route('/admin/cells/new', methods=['GET','POST'])
@login_required
@manager_required
def admin_cell_new():
    leaders = User.query.filter_by(role='leader', active=True).order_by(User.name).all()
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
@admin_required
def admin_cell_edit(cell_id):
    c = Cell.query.get_or_404(cell_id)
    leaders = User.query.filter_by(role='leader', active=True).order_by(User.name).all()
    if request.method == 'POST':
        errors = validate_cell_form(request.form)
        if errors:
            for e in errors: flash(e, 'danger')
            return render_template('admin/cell_form.html', cell=c, leaders=leaders)
        fill_cell(c, request.form); db.session.commit(); flash('Célula actualizada.', 'success')
        return redirect(url_for('admin_cells'))
    return render_template('admin/cell_form.html', cell=c, leaders=leaders)

def fill_cell(c, form):
    c.name=form.get('name','').strip(); c.leader_id=int(form.get('leader_id')) if form.get('leader_id') else None
    c.barrio=form.get('barrio','').strip(); c.barrio_other=form.get('barrio_other','').strip() or None
    c.address=form.get('address','').strip(); c.day=form.get('day','').strip(); c.time=form.get('time','').strip()
    c.phone=form.get('phone','').strip(); c.description=form.get('description','').strip(); c.status=form.get('status','active')
    c.google_maps_url=form.get('google_maps_url','').strip(); c.waze_url=form.get('waze_url','').strip()
    lat = form.get('latitude'); lng=form.get('longitude')
    if (not lat or not lng) and c.google_maps_url:
        lat2,lng2=extract_coords(c.google_maps_url); lat = lat or lat2; lng = lng or lng2
    c.latitude=float(lat) if lat not in [None,''] else None
    c.longitude=float(lng) if lng not in [None,''] else None
    if c.latitude is not None and c.longitude is not None:
        c.google_maps_url = c.google_maps_url or maps_url(c.latitude, c.longitude)
        c.waze_url = c.waze_url or waze_url(c.latitude, c.longitude)


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
    if request.method == 'POST':
        name=request.form.get('name','').strip(); username=(request.form.get('username') or '').lower().strip(); email=(request.form.get('email') or '').lower().strip() or None; phone_digits=clean_phone(request.form.get('phone','')); phone=format_cr_phone(phone_digits) if phone_digits else None
        password=request.form.get('password') or random_password()
        if not name:
            flash('Nombre es obligatorio.', 'danger'); return redirect(url_for('admin_leaders'))
        if phone_digits and len(phone_digits) != 8:
            flash('El teléfono debe tener 8 dígitos. Ejemplo: 8888-8888.', 'danger'); return redirect(url_for('admin_leaders'))
        username = slug_username(username) if username else unique_username(name)
        if User.query.filter_by(username=username).first():
            flash('Ya existe un líder con ese nombre de usuario.', 'danger'); return redirect(url_for('admin_leaders'))
        if email and User.query.filter_by(email=email).first():
            flash('Ya existe un usuario con ese correo.', 'danger'); return redirect(url_for('admin_leaders'))
        u=User(name=name,username=username,email=email,phone=phone,role='leader',active=True); u.set_password(password); db.session.add(u); db.session.commit()
        body = build_credentials_message(u, password)
        credentials_whatsapp_url = wa_message_link(phone, body) if phone else ''
        sent=False; sms_msg=''
        if request.form.get('send_sms') == 'on' and phone:
            sent, sms_msg = send_sms(phone, body); flash(sms_msg, 'success' if sent else 'warning')
        generated={'name':name,'username':username,'email':email,'password':password,'phone':phone,'body':body,'sent':sent,'whatsapp_url':credentials_whatsapp_url}
        flash('Líder creado correctamente.', 'success')
    return render_template('admin/leaders.html', leaders=User.query.filter_by(role='leader').order_by(User.created_at.desc()).all(), generated=generated)




@app.route('/admin/leaders/<int:leader_id>/edit', methods=['GET','POST'])
@login_required
@admin_required
def admin_leader_edit(leader_id):
    u = User.query.get_or_404(leader_id)
    if u.role not in ['leader', 'mentor']:
        abort(403)
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        username = slug_username(request.form.get('username',''))
        email = (request.form.get('email') or '').lower().strip() or None
        phone_digits = clean_phone(request.form.get('phone',''))
        phone = format_cr_phone(phone_digits) if phone_digits else None
        role = request.form.get('role') or u.role
        active = request.form.get('active') == 'on'
        password = request.form.get('password') or ''
        if role not in ['leader','mentor']:
            role = 'leader'
        if not name:
            flash('Nombre es obligatorio.', 'danger')
            return redirect(url_for('admin_leader_edit', leader_id=u.id))
        if not username:
            flash('Usuario es obligatorio.', 'danger')
            return redirect(url_for('admin_leader_edit', leader_id=u.id))
        if User.query.filter(User.username == username, User.id != u.id).first():
            flash('Ese usuario ya está en uso.', 'danger')
            return redirect(url_for('admin_leader_edit', leader_id=u.id))
        if email and User.query.filter(User.email == email, User.id != u.id).first():
            flash('Ese correo ya está en uso.', 'danger')
            return redirect(url_for('admin_leader_edit', leader_id=u.id))
        if phone_digits and len(phone_digits) != 8:
            flash('El teléfono debe tener 8 dígitos. Ejemplo: 8888-8888.', 'danger')
            return redirect(url_for('admin_leader_edit', leader_id=u.id))
        u.name = name; u.username = username; u.email = email; u.phone = phone; u.role = role; u.active = active
        if password:
            if len(password) < 8:
                flash('La nueva contraseña debe tener al menos 8 caracteres.', 'danger')
                return redirect(url_for('admin_leader_edit', leader_id=u.id))
            u.set_password(password)
            u.current_session_token = None
        db.session.commit()
        flash('Usuario actualizado correctamente.', 'success')
        return redirect(url_for('admin_leaders'))
    return render_template('admin/leader_edit.html', leader=u)

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
    generated = {
        'name': u.name,
        'username': u.username,
        'email': u.email,
        'password': password,
        'phone': u.phone,
        'body': body,
        'sent': False,
        'whatsapp_url': wa_message_link(u.phone, body) if u.phone else ''
    }
    flash('Credenciales generadas nuevamente. La contraseña anterior fue reemplazada.', 'success')
    leaders = User.query.filter_by(role='leader').order_by(User.created_at.desc()).all()
    return render_template('admin/leaders.html', leaders=leaders, generated=generated)

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
    return render_template('leader/dashboard.html', cell=c)

@app.route('/leader/cell/update', methods=['POST'])
@login_required
@leader_required
def leader_cell_update():
    c = Cell.query.filter_by(leader_id=current_user.id).first_or_404()
    allowed = ['address','day','time','phone','description','google_maps_url','waze_url','latitude','longitude']
    for k in allowed:
        if k in request.form:
            val = request.form.get(k)
            if k in ['latitude','longitude']:
                setattr(c,k,float(val) if val else None)
            else: setattr(c,k,val.strip())
    if c.latitude is not None and c.longitude is not None:
        c.google_maps_url = maps_url(c.latitude,c.longitude); c.waze_url = waze_url(c.latitude,c.longitude)
    db.session.commit(); flash('Información actualizada.', 'success'); return redirect(url_for('leader_dashboard'))

@app.route('/api/cells/<int:cell_id>/location', methods=['POST'])
@login_required
def api_update_location(cell_id):
    c = Cell.query.get_or_404(cell_id)
    if current_user.role != 'admin' and c.leader_id != current_user.id: abort(403)
    data = request.get_json(silent=True) or {}
    try: lat=float(data.get('latitude')); lng=float(data.get('longitude'))
    except Exception: return jsonify({'ok':False,'message':'Ubicación inválida.'}),400
    c.latitude=lat; c.longitude=lng; c.google_maps_url=maps_url(lat,lng); c.waze_url=waze_url(lat,lng); db.session.commit()
    return jsonify({'ok':True,'message':'Ubicación guardada.','maps':c.google_maps_url,'waze':c.waze_url})

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
        else:
            cols = [r[1] for r in conn.execute(text('PRAGMA table_info(user)')).fetchall()]
            if 'current_session_token' not in cols:
                conn.execute(text('ALTER TABLE user ADD COLUMN current_session_token VARCHAR(120)'))
            if 'last_seen_at' not in cols:
                conn.execute(text('ALTER TABLE user ADD COLUMN last_seen_at TIMESTAMP'))
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


BULK_LEADERS_IMPORT_DATA = [
    {
        "name": "GRADELI DUARTE",
        "barrio": "LA GUARIA",
        "phone": "8588-0490",
        "username": "GRADELI.DUARTE",
        "password": "85880490!",
        "observation": None
    },
    {
        "name": "JANNET MIRANDA",
        "barrio": "INVU 2",
        "phone": "6001-0329",
        "username": "JANNET.MIRANDA",
        "password": "60010329!",
        "observation": None
    },
    {
        "name": "MARITZA UGARTE",
        "barrio": "LA GUARIA",
        "phone": "8593-9497",
        "username": "MARITZA.UGARTE",
        "password": "85939497!",
        "observation": None
    },
    {
        "name": "ERIKA ACEVEDO",
        "barrio": "MORACIA",
        "phone": "8702-9708",
        "username": "ERIKA.ACEVEDO",
        "password": "87029708!",
        "observation": None
    },
    {
        "name": "JOSE ANGEL SALAZAR",
        "barrio": "RESIDENCIAL DEL RIO",
        "phone": "8443-6772",
        "username": "JOSE.SALAZAR",
        "password": "84436772!",
        "observation": None
    },
    {
        "name": "LEONARDO ALVAREZ",
        "barrio": "MORACIA",
        "phone": "8550-6266",
        "username": "LEONARDO.ALVAREZ",
        "password": "85506266!",
        "observation": None
    },
    {
        "name": "ROYMAN VALENCIA",
        "barrio": "BRASILIA",
        "phone": "6486-4275",
        "username": "ROYMAN.VALENCIA",
        "password": "64864275!",
        "observation": None
    },
    {
        "name": "KENNETH CENTENO",
        "barrio": "PUEBLO NUEVO",
        "phone": "8666-5560",
        "username": "KENNETH.CENTENO",
        "password": "86665560!",
        "observation": None
    },
    {
        "name": "GIOCONDA DE LA SEGURA LOPEZ",
        "barrio": "SAN ROQUE",
        "phone": "8424-7460",
        "username": "GIOCONDA.LOPEZ",
        "password": "84247460!",
        "observation": None
    },
    {
        "name": "ROBERT TALAVERA",
        "barrio": "SANTA LUISA",
        "phone": "6043-2882",
        "username": "ROBERT.TALAVERA",
        "password": "60432882!",
        "observation": None
    },
    {
        "name": "LINETH RUBIO",
        "barrio": "LA GUARIA",
        "phone": "8844-7735",
        "username": "LINETH.RUBIO",
        "password": "88447735!",
        "observation": None
    },
    {
        "name": "JONATHAN MORENO",
        "barrio": "LA GALLERA",
        "phone": "8328-7691",
        "username": "JONATHAN.MORENO",
        "password": "83287691!",
        "observation": None
    },
    {
        "name": "ROLAND GARCIA",
        "barrio": "MORACIA",
        "phone": "8787-9497",
        "username": "ROLAND.GARCIA",
        "password": "87879497!",
        "observation": None
    },
    {
        "name": "GILBERTH ORDONEZ",
        "barrio": "CORAZON DE JESUS / SAN ANTONIO",
        "phone": "8826-0133",
        "username": "GILBERTH.ORDONEZ",
        "password": "88260133!",
        "observation": None
    },
    {
        "name": "HECTOR CABALCETA",
        "barrio": "LA GUARIA",
        "phone": "7290-9807",
        "username": "HECTOR.CABALCETA",
        "password": "72909807!",
        "observation": None
    },
    {
        "name": "SOBEIDA OBANDO",
        "barrio": "LOS ANGELES",
        "phone": "8525-2228",
        "username": "SOBEIDA.OBANDO",
        "password": "85252228!",
        "observation": None
    },
    {
        "name": "LUIS CHAVES",
        "barrio": "FELIPE PEREZ",
        "phone": "8826-6293",
        "username": "LUIS.CHAVES",
        "password": "88266293!",
        "observation": None
    },
    {
        "name": "WENDY SANDOVAL",
        "barrio": "DANIEL ODUBER",
        "phone": "7225-3984",
        "username": "WENDY.SANDOVAL",
        "password": "72253984!",
        "observation": None
    },
    {
        "name": "VANESSA TORRES",
        "barrio": "RESIDENCIAL DEL RIO",
        "phone": "8677-6468",
        "username": "VANESSA.TORRES",
        "password": "86776468!",
        "observation": None
    },
    {
        "name": "GUSTAVO CASTILLO",
        "barrio": "MORACIA",
        "phone": "8811-8073",
        "username": "GUSTAVO.CASTILLO",
        "password": "88118073!",
        "observation": None
    },
    {
        "name": "ANDREI CASTRO",
        "barrio": "LA CARRETA",
        "phone": "8760-8356",
        "username": "ANDREI.CASTRO",
        "password": "87608356!",
        "observation": None
    },
    {
        "name": "RANDALL CORTES",
        "barrio": "EL PELONCITO",
        "phone": "7046-0451",
        "username": "RANDALL.CORTES",
        "password": "70460451!",
        "observation": None
    },
    {
        "name": "DAVID HERNANDEZ",
        "barrio": "LA VICTORIA",
        "phone": "8413-4946",
        "username": "DAVID.HERNANDEZ",
        "password": "84134946!",
        "observation": None
    },
    {
        "name": "YORHANY RAMIREZ",
        "barrio": "LOS ALMENDRALES",
        "phone": "8941-6174",
        "username": "YORHANY.RAMIREZ",
        "password": "89416174!",
        "observation": None
    },
    {
        "name": "JEREMY PINA",
        "barrio": "EL PELONCITO",
        "phone": "8754-9785",
        "username": "JEREMY.PINA",
        "password": "87549785!",
        "observation": None
    },
    {
        "name": "ANGELICA PEREZ",
        "barrio": "FELIPE PEREZ",
        "phone": "7287-9236",
        "username": "ANGELICA.PEREZ",
        "password": "72879236!",
        "observation": None
    },
    {
        "name": "ISTELYN MARCHENA",
        "barrio": "LA VICTORIA",
        "phone": "8720-9378",
        "username": "ISTELYN.MARCHENA",
        "password": "87209378!",
        "observation": None
    },
    {
        "name": "RICHARD SANTANA",
        "barrio": "PEDRO HERNANDEZ",
        "phone": "8495-3414",
        "username": "RICHARD.SANTANA",
        "password": "84953414!",
        "observation": None
    },
    {
        "name": "DANILO GUTIERREZ",
        "barrio": "NAZARET",
        "phone": "6079-5230",
        "username": "DANILO.GUTIERREZ",
        "password": "60795230!",
        "observation": None
    },
    {
        "name": "ANGELICA QUINTERO",
        "barrio": "LA GUARIA",
        "phone": "7262-3899",
        "username": "ANGELICA.QUINTERO",
        "password": "72623899!",
        "observation": None
    },
    {
        "name": "SARA SALAZAR",
        "barrio": "FELIPE PEREZ",
        "phone": "8884-7731",
        "username": "SARA.SALAZAR",
        "password": "88847731!",
        "observation": None
    },
    {
        "name": "CRISTOPHER CASTILLO",
        "barrio": "MORACIA",
        "phone": "7298-1478",
        "username": "CRISTOPHER.CASTILLO",
        "password": "72981478!",
        "observation": None
    },
    {
        "name": "ABIGAIL VARGAS",
        "barrio": "FELIPE PEREZ",
        "phone": "8584-5351",
        "username": "ABIGAIL.VARGAS",
        "password": "85845351!",
        "observation": None
    },
    {
        "name": "CECI RODRIGUEZ",
        "barrio": "PUEBLO NUEVO",
        "phone": "6327-9935",
        "username": "CECI.RODRIGUEZ",
        "password": "63279935!",
        "observation": None
    },
    {
        "name": "FERNANDA FONSECA",
        "barrio": "SAN ROQUE",
        "phone": "6123-1307",
        "username": "FERNANDA.FONSECA",
        "password": "61231307!",
        "observation": None
    },
    {
        "name": "PAUL DE TRINIDAD",
        "barrio": "LAS PALMAS 1 CANAS",
        "phone": "6057-2369",
        "username": "PAUL.TRINIDAD",
        "password": "60572369!",
        "observation": None
    },
    {
        "name": "ALLISON CAMPOS",
        "barrio": "CHOROTEGA",
        "phone": "8325-1664",
        "username": "ALLISON.CAMPOS",
        "password": "83251664!",
        "observation": None
    },
    {
        "name": "MAYELA CHAVARRIA",
        "barrio": "SAN ROQUE",
        "phone": "8732-6608",
        "username": "MAYELA.CHAVARRIA",
        "password": "87326608!",
        "observation": None
    },
    {
        "name": "ANGELA LOPEZ",
        "barrio": "EL CAMBALACHE",
        "phone": "7142-6027",
        "username": "ANGELA.LOPEZ",
        "password": "71426027!",
        "observation": None
    },
    {
        "name": "CHRISTOPHER",
        "barrio": "CORAZON DE JESUS",
        "phone": "7085-9427",
        "username": "CHRISTOPHER",
        "password": "70859427!",
        "observation": "REVISAR APELLIDO"
    },
    {
        "name": "ESTEBAN LOPEZ",
        "barrio": "SIN DIRECCION",
        "phone": None,
        "username": "ESTEBAN.LOPEZ",
        "password": "Hosanna2026!",
        "observation": "SIN TELEFONO PARA CONTRASENA"
    },
    {
        "name": "JOHN ESPINOSA",
        "barrio": "FELIPE PEREZ",
        "phone": "8946-2702",
        "username": "JOHN.ESPINOSA",
        "password": "89462702!",
        "observation": None
    },
    {
        "name": "OLGER CORTES",
        "barrio": "LINDA VISTA",
        "phone": "6206-6042",
        "username": "OLGER.CORTES",
        "password": "62066042!",
        "observation": None
    },
    {
        "name": "SOFIA ALVAREZ",
        "barrio": "MORACIA",
        "phone": "6212-2133",
        "username": "SOFIA.ALVAREZ",
        "password": "62122133!",
        "observation": None
    },
    {
        "name": "ELEONORA MOLINA",
        "barrio": "FELIPE PEREZ",
        "phone": "6057-2379",
        "username": "ELEONORA.MOLINA",
        "password": "60572379!",
        "observation": None
    },
    {
        "name": "CARLOS BERMUDEZ",
        "barrio": "LA HULERA",
        "phone": None,
        "username": "CARLOS.BERMUDEZ",
        "password": "Hosanna2026!",
        "observation": "SIN TELEFONO PARA CONTRASENA"
    },
    {
        "name": "FABIAN PRENDAS",
        "barrio": "LA CRUZ",
        "phone": "6400-3113",
        "username": "FABIAN.PRENDAS",
        "password": "64003113!",
        "observation": None
    },
    {
        "name": "VICTORIA REYES",
        "barrio": "EL GALLO",
        "phone": "8388-5904",
        "username": "VICTORIA.REYES",
        "password": "83885904!",
        "observation": None
    },
    {
        "name": "MINOR TALAVERA",
        "barrio": "PIJIJE",
        "phone": "8910-4270",
        "username": "MINOR.TALAVERA",
        "password": "89104270!",
        "observation": None
    },
    {
        "name": "ELI MENDEZ",
        "barrio": "LOMA BONITA DE BELEN",
        "phone": "8372-2747",
        "username": "ELI.MENDEZ",
        "password": "83722747!",
        "observation": None
    },
    {
        "name": "MARJORIE BUSTOS",
        "barrio": "SANTA CRUZ",
        "phone": "8779-4327",
        "username": "MARJORIE.BUSTOS",
        "password": "87794327!",
        "observation": None
    },
    {
        "name": "JEISON ROJAS",
        "barrio": "LA GUARIA",
        "phone": "8971-4837",
        "username": "JEISON.ROJAS",
        "password": "89714837!",
        "observation": None
    },
    {
        "name": "YENIER ORTIZ",
        "barrio": "SIN DIRECCION",
        "phone": "7043-7674",
        "username": "YENIER.ORTIZ",
        "password": "70437674!",
        "observation": None
    },
    {
        "name": "ELIAS AGUILAR",
        "barrio": "LA GALLERA",
        "phone": "6323-8586",
        "username": "ELIAS.AGUILAR",
        "password": "63238586!",
        "observation": None
    }
]

def normalize_import_username(value):
    return slug_username(value or '')

def title_name(value):
    return ' '.join([p.capitalize() for p in (value or '').strip().split()])

def normalize_import_barrio(value):
    raw = (value or '').strip()
    if not raw or raw.upper() == 'SIN DIRECCION':
        return 'Otro', 'Por definir'
    # Si existe en la lista oficial, usarlo directo manteniendo formato título.
    for b in BARRIOS_LIBERIA:
        if b.lower() == raw.lower():
            return b, None
    return 'Otro', title_name(raw)

@app.cli.command('import-leaders-cells')
def import_leaders_cells():
    """Importa líderes y crea células esqueleto desde la base inicial.
    Es idempotente: si se ejecuta otra vez, actualiza sin duplicar por usuario/líder.
    """
    db.create_all()
    created_users = updated_users = created_cells = updated_cells = 0
    skipped = []

    for row in BULK_LEADERS_IMPORT_DATA:
        name = title_name(row.get('name'))
        username = normalize_import_username(row.get('username') or name)
        phone = format_cr_phone(row.get('phone')) if row.get('phone') else None
        password = row.get('password') or 'Hosanna2026!'
        barrio, barrio_other = normalize_import_barrio(row.get('barrio'))

        if not name or not username:
            skipped.append(row)
            continue

        user = User.query.filter_by(username=username).first()
        if not user:
            user = User(
                name=name,
                username=username,
                email=None,
                phone=phone,
                role='leader',
                active=True,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            created_users += 1
        else:
            user.name = name
            user.phone = phone
            user.role = 'leader'
            user.active = True
            # Reaplica la contraseña del Excel para que las credenciales queden exactas.
            user.set_password(password)
            updated_users += 1

        cell_name = f'Célula {name}'
        cell = Cell.query.filter_by(leader_id=user.id).first()
        if not cell:
            cell = Cell(
                name=cell_name,
                leader_id=user.id,
                barrio=barrio,
                barrio_other=barrio_other,
                address='Dirección por definir',
                day='Por definir',
                time='Por definir',
                phone=phone,
                description='Grupo familiar pendiente de completar información.',
                status='paused',
            )
            db.session.add(cell)
            created_cells += 1
        else:
            cell.name = cell.name or cell_name
            cell.leader_id = user.id
            cell.barrio = barrio
            cell.barrio_other = barrio_other
            cell.phone = cell.phone or phone
            if not cell.address or cell.address in ['None', '']:
                cell.address = 'Dirección por definir'
            if not cell.day:
                cell.day = 'Por definir'
            if not cell.time:
                cell.time = 'Por definir'
            if not cell.description:
                cell.description = 'Grupo familiar pendiente de completar información.'
            # No sobreescribir status si ya fue activada por admin/líder.
            cell.status = cell.status or 'paused'
            updated_cells += 1

    db.session.commit()
    print(f'Importación completada.')
    print(f'Líderes creados: {created_users}')
    print(f'Líderes actualizados: {updated_users}')
    print(f'Células creadas: {created_cells}')
    print(f'Células actualizadas: {updated_cells}')
    print(f'Omitidos: {len(skipped)}')
    if skipped:
        print(skipped)


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

