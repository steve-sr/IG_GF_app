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


# ---------------------------------------------------------------------------
# Importación controlada de direcciones de grupos familiares
# Fuente estructurada desde "Grupos Familiares.xlsx".
# Uso recomendado: ejecutar una vez en Render Shell:
#   flask import-group-addresses
# ---------------------------------------------------------------------------
GROUP_ADDRESS_IMPORT_DATA = [
    {
        "name": "GRADELI DUARTE",
        "source_name": "Gradeli",
        "username": "gradeli.duarte",
        "password": "85880490!",
        "phone": "8588-0490",
        "barrio": "La Guaria",
        "address": "barrio la Guaria 1 200 este del salón comunal de Imas",
        "day": "Lunes",
        "time": "Por definir",
        "cell_name": "Célula Gradeli Duarte"
    },
    {
        "name": "JANNET MIRANDA",
        "source_name": "Jannet Miranda Celula de niños y adolescentes",
        "username": "jannet.miranda",
        "password": "60010329!",
        "phone": "6001-0329",
        "barrio": "INVU 2",
        "address": "Invu #2",
        "day": "Sábado",
        "time": "Por definir",
        "cell_name": "Célula Jannet Miranda"
    },
    {
        "name": "MARITZA UGARTE",
        "source_name": "Maritza Ugarte",
        "username": "maritza.ugarte",
        "password": "85939497!",
        "phone": "8593-9497",
        "barrio": "La Guaria",
        "address": "Guaria 2 del antiguo danto300 norte y 75 al este",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Maritza Ugarte"
    },
    {
        "name": "ERIKA ACEVEDO",
        "source_name": "Ericka",
        "username": "erika.acevedo",
        "password": "87029708!",
        "phone": "8702-9708",
        "barrio": "Moracia",
        "address": "150 noreste de la entrada de emergencias Moracia",
        "day": "Lunes",
        "time": "Por definir",
        "cell_name": "Célula Erika Acevedo"
    },
    {
        "name": "JOSE ANGEL SALAZAR",
        "source_name": "José Ángel",
        "username": "jose.salazar",
        "password": "84436772!",
        "phone": "8443-6772",
        "barrio": "Residencial Del Río",
        "address": "500 norte y 25 este de la entrada principal del residencial Río",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Jose Angel Salazar"
    },
    {
        "name": "LEONARDO ALVAREZ",
        "source_name": "Leonardo",
        "username": "leonardo.alvarez",
        "password": "85506266!",
        "phone": "8550-6266",
        "barrio": "Moracia",
        "address": "Moracia, a la par de MH Partes",
        "day": "Lunes",
        "time": "Por definir",
        "cell_name": "Célula Leonardo Alvarez"
    },
    {
        "name": "ROYMAN VALENCIA",
        "source_name": "Royman",
        "username": "royman.valencia",
        "password": "64864275!",
        "phone": "6486-4275",
        "barrio": "Brasilia",
        "address": "75 norte del salón brasilia contigo a la bomba de agua",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Royman Valencia"
    },
    {
        "name": "KENNETH CENTENO",
        "source_name": "Kennet",
        "username": "kenneth.centeno",
        "password": "86665560!",
        "phone": "8666-1528",
        "barrio": "Pueblo Nuevo",
        "address": "Pueblo Nuevo, del salon comunal 100 sur y 100 al este",
        "day": "Lunes",
        "time": "Por definir",
        "cell_name": "Célula Kenneth Centeno"
    },
    {
        "name": "GIOCONDA DE LA SEGURA LOPEZ",
        "source_name": "Gioconda",
        "username": "gioconda.lopez",
        "password": "84247460!",
        "phone": "8424-7460",
        "barrio": "San Roque",
        "address": "barrio san Roque 300 este iglesia católica",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Gioconda De La Segura Lopez"
    },
    {
        "name": "ROBERT TALAVERA",
        "source_name": "Robert Talabera",
        "username": "robert.talavera",
        "password": "60432882!",
        "phone": "6043-2882",
        "barrio": "Santa Luisa",
        "address": "Barrio Santa Luisa casa 459",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Robert Talavera"
    },
    {
        "name": "LINETH RUBIO",
        "source_name": "Lineth Rubio",
        "username": "lineth.rubio",
        "password": "88447735!",
        "phone": "8844-7735",
        "barrio": "La Guaria",
        "address": "Barrio la Guaria 2",
        "day": "Por definir",
        "time": "Por definir",
        "cell_name": "Célula Lineth Rubio"
    },
    {
        "name": "JONATHAN MORENO",
        "source_name": "Jonathan Moreno",
        "username": "jonathan.moreno",
        "password": "83287691!",
        "phone": "8328-7691",
        "barrio": "La Gallera",
        "address": "Barrio La Gallera, 300 mts oeste del taller Rosales",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Jonathan Moreno"
    },
    {
        "name": "ROLAND GARCIA",
        "source_name": "Roland García",
        "username": "roland.garcia",
        "password": "87879497!",
        "phone": "8787-9497",
        "barrio": "Moracia",
        "address": "B° Moracia 300 Mts, este de la panadería Sánchez.",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Roland Garcia"
    },
    {
        "name": "GILBERTH ORDONEZ",
        "source_name": "Gilberth Ordóñez",
        "username": "gilberth.ordonez",
        "password": "88260133!",
        "phone": "8826-0133",
        "barrio": "Corazón de Jesús",
        "address": "Corazón de Jesús / San Antonio",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Gilberth Ordonez"
    },
    {
        "name": "HECTOR CABALCETA",
        "source_name": "Héctor Cabalceta",
        "username": "hector.cabalceta",
        "password": "72909807!",
        "phone": "7290-9807",
        "barrio": "La Guaria",
        "address": "B° La Guaria Del Salón Comunal de Imas 150 mts Esté",
        "day": "Lunes",
        "time": "Por definir",
        "cell_name": "Célula Hector Cabalceta"
    },
    {
        "name": "SOBEIDA OBANDO",
        "source_name": "Sobeida Obando",
        "username": "sobeida.obando",
        "password": "85252228!",
        "phone": "8525-2228",
        "barrio": "Los Ángeles",
        "address": "Los Ángeles",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Sobeida Obando"
    },
    {
        "name": "LUIS CHAVES",
        "source_name": "Luis Chaves",
        "username": "luis.chaves",
        "password": "88266293!",
        "phone": "8826-6293",
        "barrio": "Felipe Pérez",
        "address": "Felipe Perez Frente al play de la segunda etapa de Felipe Perez",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Luis Chaves"
    },
    {
        "name": "WENDY SANDOVAL",
        "source_name": "Wendy Sandoval",
        "username": "wendy.sandoval",
        "password": "72253984!",
        "phone": "7225-3984",
        "barrio": "Daniel Oduber",
        "address": "B° Daniel Oduber, 100 m. Oeste y 300 Sur del Minisuper Chema #3.",
        "day": "Lunes",
        "time": "Por definir",
        "cell_name": "Célula Wendy Sandoval"
    },
    {
        "name": "VANESSA TORRES",
        "source_name": "Vanessa Torres",
        "username": "vanessa.torres",
        "password": "86776468!",
        "phone": "8677-6468",
        "barrio": "Residencial Del Río",
        "address": "Residencial Del Río",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Vanessa Torres"
    },
    {
        "name": "GUSTAVO CASTILLO",
        "source_name": "Gustavo Castillo",
        "username": "gustavo.castillo",
        "password": "88118073!",
        "phone": "8811-8073",
        "barrio": "Moracia",
        "address": "B° Moracia 300 mts. Esté y 75 mts Norte del IPEC",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Gustavo Castillo"
    },
    {
        "name": "ANDREI CASTRO",
        "source_name": "Andrei Castro",
        "username": "andrei.castro",
        "password": "87608356!",
        "phone": "8760-8356",
        "barrio": "La Carreta",
        "address": "La Carreta Condominios La Carreta",
        "day": "Lunes",
        "time": "Por definir",
        "cell_name": "Célula Andrei Castro"
    },
    {
        "name": "RANDALL CORTES",
        "source_name": "Randall Cortes",
        "username": "randall.cortes",
        "password": "70460451!",
        "phone": "7046-0451",
        "barrio": "El Peloncito",
        "address": "B° El Peloncito De la Escuela del Peloncito 300 mts. Sur última casa mano derecha.",
        "day": "Por definir",
        "time": "Por definir",
        "cell_name": "Célula Randall Cortes"
    },
    {
        "name": "DAVID HERNANDEZ",
        "source_name": "David Hernadez Dodero",
        "username": "david.hernandez",
        "password": "84134946!",
        "phone": "8413-4946",
        "barrio": "La Gallera",
        "address": "Barrio la Victoria, De la antigua gallera 200 sur",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula David Hernandez"
    },
    {
        "name": "YORHANY RAMIREZ",
        "source_name": "Yorhany Ramírez",
        "username": "yorhany.ramirez",
        "password": "89416174!",
        "phone": "8941-6174",
        "barrio": "Los Almendrales",
        "address": "Los Almendrales",
        "day": "Lunes",
        "time": "Por definir",
        "cell_name": "Célula Yorhany Ramirez"
    },
    {
        "name": "ANGELICA PEREZ",
        "source_name": "Angélica Pérez Tenorio",
        "username": "angelica.perez",
        "password": "72879236!",
        "phone": "7287-9236",
        "barrio": "Felipe Pérez",
        "address": "Felipe Pérez, etapa1 Del Colegio, 100m sur y 150 oeste, en el callejón sin salida. Ante ante penúltima casa ,a mano derecha, verjas negras",
        "day": "Lunes",
        "time": "Por definir",
        "cell_name": "Célula Angelica Perez"
    },
    {
        "name": "JEREMY PINA",
        "source_name": "Jeremy Peña",
        "username": "jeremy.pina",
        "password": "87549785!",
        "phone": "8754-9785",
        "barrio": "El Peloncito",
        "address": "Barrio Peloncito, del súper mercado Spiti 100 mtrs este y 25 norte",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Jeremy Pina"
    },
    {
        "name": "ISTELYN MARCHENA",
        "source_name": "Istelyn Marchena",
        "username": "istelyn.marchena",
        "password": "87209378!",
        "phone": "8720-9378",
        "barrio": "La Victoria",
        "address": "Barrio la Victoria 50m este y 50m sur del súper económico",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Istelyn Marchena"
    },
    {
        "name": "RICHARD SANTANA",
        "source_name": "Richard Santana",
        "username": "richard.santana",
        "password": "84953414!",
        "phone": "8495-3414",
        "barrio": "Pedro Hernández",
        "address": "Urbanización Pedro Hernández, quinta entrada mano izq, 2da casa",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Richard Santana"
    },
    {
        "name": "DANILO GUTIERREZ",
        "source_name": "Danilo Gutiérrez",
        "username": "danilo.gutierrez",
        "password": "60795230!",
        "phone": "6079-5230",
        "barrio": "Nazareth",
        "address": "Nazaret",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Danilo Gutierrez"
    },
    {
        "name": "ANGELICA QUINTERO",
        "source_name": "Angelica Quintero",
        "username": "angelica.quintero",
        "password": "72623899!",
        "phone": "7262-3899",
        "barrio": "La Guaria",
        "address": "Barrio la Guaria 200 mtr este del salón comunal del IMAS",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Angelica Quintero"
    },
    {
        "name": "SARA SALAZAR",
        "source_name": "Sara Salazar",
        "username": "sara.salazar",
        "password": "88847731!",
        "phone": "8884-7731",
        "barrio": "Felipe Pérez",
        "address": "Felipe Perez Del colegio artistico 100 sur y 25",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Sara Salazar"
    },
    {
        "name": "CRISTOPHER CASTILLO",
        "source_name": "Cristopher Castillo.",
        "username": "cristopher.castillo",
        "password": "72981478!",
        "phone": "7298-1478",
        "barrio": "Moracia",
        "address": "Moracia Del liceo nocturno 200 este y 25 al sur, casa mano derecha.",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Cristopher Castillo"
    },
    {
        "name": "ABIGAIL VARGAS",
        "source_name": "Abi Vargas",
        "username": "abigail.vargas",
        "password": "85845351!",
        "phone": "8584-5351",
        "barrio": "Felipe Pérez",
        "address": "Felipe Perez Del colegio artistico 200 sur y 75 este",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Abigail Vargas"
    },
    {
        "name": "CECI RODRIGUEZ",
        "source_name": "Ceci Rodríguez Viales",
        "username": "ceci.rodriguez",
        "password": "63279935!",
        "phone": "6327-9935",
        "barrio": "Pueblo Nuevo",
        "address": "Pueblo Nuevo, detrás de Pulp. Las palmeras",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Ceci Rodriguez"
    },
    {
        "name": "FERNANDA FONSECA",
        "source_name": "Fernanda Fonseca",
        "username": "fernanda.fonseca",
        "password": "61231307!",
        "phone": "6123-1307",
        "barrio": "San Roque",
        "address": "Frente a la iglesia Ebenezer (San Roque)",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Fernanda Fonseca"
    },
    {
        "name": "PAUL DE TRINIDAD",
        "source_name": "Paul Detrinidad",
        "username": "paul.trinidad",
        "password": "60572369!",
        "phone": "6057-2369",
        "barrio": "Cañas",
        "address": "Cañas Guanacaste, Barrio las Palmas #1",
        "day": "Miércoles",
        "time": "Por definir",
        "cell_name": "Célula Paul De Trinidad"
    },
    {
        "name": "ALLISON CAMPOS",
        "source_name": "Allison Campos",
        "username": "allison.campos",
        "password": "83251664!",
        "phone": "8325-1664",
        "barrio": "Chorotega",
        "address": "B. chorotega",
        "day": "Miércoles",
        "time": "Por definir",
        "cell_name": "Célula Allison Campos"
    },
    {
        "name": "MAYELA CHAVARRIA",
        "source_name": "Mayela Chavarria",
        "username": "mayela.chavarria",
        "password": "87326608!",
        "phone": "8732-6608",
        "barrio": "San Roque",
        "address": "San Roque",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Mayela Chavarria"
    },
    {
        "name": "ANGELA LOPEZ",
        "source_name": "Angela López",
        "username": "angela.lopez",
        "password": "71426027!",
        "phone": "7142-6027",
        "barrio": "El Cambalache",
        "address": "Barrio El Cambalache",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Angela Lopez"
    },
    {
        "name": "CHRISTOPHER",
        "source_name": "Christopher",
        "username": "christopher",
        "password": "70859427!",
        "phone": "7085-9427",
        "barrio": "Corazón de Jesús",
        "address": "Barrio Corazón de Jesús, casa contiguo del abastecedor Susy",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Christopher"
    },
    {
        "name": "NICOLE",
        "source_name": "Nicole",
        "username": "nicole",
        "password": "72714430!",
        "phone": "7271-4430",
        "barrio": "Moracia",
        "address": "Iglesia Hosanna (Barrio Moracia)",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Nicole"
    },
    {
        "name": "Joset vilchez",
        "source_name": "Joset vilchez",
        "username": "joset.vilchez",
        "password": "71332646!",
        "phone": "7133-2646",
        "barrio": "Corazón de Jesús",
        "address": "Corazon de jesus",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Joset vilchez"
    },
    {
        "name": "JOHN ESPINOSA",
        "source_name": "John",
        "username": "john.espinosa",
        "password": "89462702!",
        "phone": "8946-2702",
        "barrio": "Felipe Pérez",
        "address": "Barrio Felipe Pérez, del Colegio Artístico 700m Este y 75m Sur",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula John Espinosa"
    },
    {
        "name": "OLGER CORTES",
        "source_name": "Olger Cortés",
        "username": "olger.cortes",
        "password": "62066042!",
        "phone": "6206-6042",
        "barrio": "Linda Vista",
        "address": "Barrio linda vista",
        "day": "Lunes",
        "time": "Por definir",
        "cell_name": "Célula Olger Cortes"
    },
    {
        "name": "SOFIA ALVAREZ",
        "source_name": "Sofía",
        "username": "sofia.alvarez",
        "password": "62122133!",
        "phone": "6212-2133",
        "barrio": "Moracia",
        "address": "Barrio Moracia, casa contiguo a repuestos MH Partes",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Sofia Alvarez"
    },
    {
        "name": "CARLOS BERMUDEZ",
        "source_name": "Carlos Bermudes",
        "username": "carlos.bermudez",
        "password": "",
        "phone": "",
        "barrio": "La Hulera",
        "address": "Antigua Hulera",
        "day": "Por definir",
        "time": "Por definir",
        "cell_name": "Célula Carlos Bermudez"
    },
    {
        "name": "FABIAN PRENDAS",
        "source_name": "Fabian Prendas",
        "username": "fabian.prendas",
        "password": "64003113!",
        "phone": "6400-3113",
        "barrio": "La Cruz",
        "address": "Barrio La Cruz",
        "day": "Sábado",
        "time": "Por definir",
        "cell_name": "Célula Fabian Prendas"
    },
    {
        "name": "VICTORIA REYES",
        "source_name": "Victoria Reyes Medina",
        "username": "victoria.reyes",
        "password": "83885904!",
        "phone": "8388-5904",
        "barrio": "El Gallo",
        "address": "Barrio el Gallo 200 este y 300 norte de la iglesia evangelica",
        "day": "Por definir",
        "time": "Por definir",
        "cell_name": "Célula Victoria Reyes"
    },
    {
        "name": "MINOR TALAVERA",
        "source_name": "Minor Talavera",
        "username": "minor.talavera",
        "password": "89104270!",
        "phone": "8910-4270",
        "barrio": "Pijije",
        "address": "Pijije",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Minor Talavera"
    },
    {
        "name": "ELI MENDEZ",
        "source_name": "Elí Méndez Barrientos",
        "username": "eli.mendez",
        "password": "83722747!",
        "phone": "8372-2747",
        "barrio": "Loma Bonita de Belén",
        "address": "Barrio: Loma Bonita de Belén Del puente 100 N 3ra casa derecha color blanca",
        "day": "Por definir",
        "time": "Por definir",
        "cell_name": "Célula Eli Mendez"
    },
    {
        "name": "MARJORIE BUSTOS",
        "source_name": "Marjorie Bustos",
        "username": "marjorie.bustos",
        "password": "87794327!",
        "phone": "8779-4327",
        "barrio": "Santa Cruz",
        "address": "Santa Cruz del salon comunal 850 m noroeste casa amono derecha",
        "day": "Sábado",
        "time": "Por definir",
        "cell_name": "Célula Marjorie Bustos"
    },
    {
        "name": "JEISON ROJAS",
        "source_name": "Jeison Rojas",
        "username": "jeison.rojas",
        "password": "89714837!",
        "phone": "8971-4837",
        "barrio": "La Guaria",
        "address": "La Guaria, a la del antiguo Danto",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Jeison Rojas"
    },
    {
        "name": "YENIER ORTIZ",
        "source_name": "Yenier Ortiz",
        "username": "yenier.ortiz",
        "password": "70437674!",
        "phone": "7043-7674",
        "barrio": "Otro",
        "address": "Dirección por definir",
        "day": "Viernes",
        "time": "Por definir",
        "cell_name": "Célula Yenier Ortiz"
    },
    {
        "name": "ELIAS AGUILAR",
        "source_name": "Elias Aguilar",
        "username": "elias.aguilar",
        "password": "63238586!",
        "phone": "6323-8586",
        "barrio": "La Gallera",
        "address": "La Gallera",
        "day": "Lunes",
        "time": "Por definir",
        "cell_name": "Célula Elias Aguilar"
    }
]

def import_status_for_address(address):
    address = (address or '').strip()
    if not address or address.lower() in ['dirección por definir', 'direccion por definir', 'por definir']:
        return 'paused'
    return 'active'

@app.cli.command('import-group-addresses')
def import_group_addresses():
    """Crea/actualiza células con direcciones y días desde la lista oficial de grupos.
    Idempotente: si se ejecuta otra vez, no duplica; actualiza por usuario/teléfono.
    No borra datos manuales. No sobreescribe coordenadas, Maps ni Waze.
    """
    db.create_all()
    created_users = updated_users = created_cells = updated_cells = skipped = 0

    for row in GROUP_ADDRESS_IMPORT_DATA:
        raw_username = (row.get('username') or row.get('name') or '').strip()
        username = slug_username(raw_username)
        name = (row.get('name') or '').strip().title()
        phone = format_cr_phone(row.get('phone') or '')
        phone_digits = clean_phone(phone)
        password = (row.get('password') or '').strip()
        address = (row.get('address') or 'Dirección por definir').strip()
        barrio = (row.get('barrio') or 'Otro').strip()
        day = (row.get('day') or 'Por definir').strip()
        time = (row.get('time') or 'Por definir').strip()
        cell_name = (row.get('cell_name') or f'Célula {name}').strip()

        if not name or not username:
            skipped += 1
            continue

        user = User.query.filter_by(username=username).first()
        if not user and phone_digits:
            user = User.query.filter(User.phone.like(f'%{phone_digits[:4]}%')).first()

        if not user:
            user = User(
                name=name,
                username=username,
                email=None,
                phone=phone,
                role='leader',
                active=True
            )
            if password:
                user.set_password(password)
            else:
                user.set_password(random_password())
            db.session.add(user)
            db.session.flush()
            created_users += 1
        else:
            user.name = user.name or name
            user.username = user.username or username
            user.phone = phone or user.phone
            user.role = 'leader'
            user.active = True
            updated_users += 1

        cell = Cell.query.filter_by(leader_id=user.id).first()
        if not cell:
            cell = Cell(
                name=cell_name,
                leader_id=user.id,
                barrio=barrio,
                barrio_other=None if barrio != 'Otro' else None,
                address=address,
                day=day,
                time=time,
                phone=phone or user.phone,
                description='Grupo familiar.',
                status=import_status_for_address(address)
            )
            db.session.add(cell)
            created_cells += 1
        else:
            cell.name = cell.name or cell_name
            cell.leader_id = user.id
            cell.barrio = barrio or cell.barrio
            cell.address = address or cell.address or 'Dirección por definir'
            cell.day = day or cell.day or 'Por definir'
            cell.time = time or cell.time or 'Por definir'
            cell.phone = phone or cell.phone or user.phone
            if not cell.description or 'pendiente' in (cell.description or '').lower():
                cell.description = 'Grupo familiar.'
            if address and address.lower() not in ['dirección por definir', 'direccion por definir', 'por definir']:
                cell.status = 'active'
            else:
                cell.status = cell.status or 'paused'
            updated_cells += 1

    db.session.commit()
    print('Importación de direcciones completada.')
    print(f'Líderes creados: {created_users}')
    print(f'Líderes actualizados: {updated_users}')
    print(f'Células creadas: {created_cells}')
    print(f'Células actualizadas: {updated_cells}')
    print(f'Omitidos: {skipped}')

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

