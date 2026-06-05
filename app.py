import os, re, math, secrets, string
from datetime import datetime
from functools import wraps
from urllib.parse import quote_plus

from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
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

APP_PUBLIC_URL = os.getenv('APP_PUBLIC_URL', 'http://127.0.0.1:5000').rstrip('/')

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Iniciá sesión para continuar.'

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
    email = db.Column(db.String(180), unique=True, nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='leader') # admin, leader, member-reserved
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin': abort(403)
        return fn(*args, **kwargs)
    return wrapper

def leader_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ['admin','leader']: abort(403)
        return fn(*args, **kwargs)
    return wrapper

def clean_phone(phone):
    return re.sub(r'\D+', '', phone or '')

def cr_phone(phone):
    digits = clean_phone(phone)
    if len(digits) == 8: return '+506' + digits
    if digits.startswith('506') and len(digits) == 11: return '+' + digits
    if phone and phone.startswith('+'): return phone
    return phone or ''

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

def validate_cell_form(form):
    errors = []
    required = {'name':'Nombre de la célula','barrio':'Barrio','address':'Dirección','day':'Día','time':'Hora'}
    for k, label in required.items():
        if not (form.get(k) or '').strip(): errors.append(f'{label} es obligatorio.')
    if form.get('day') and form.get('day') not in DAYS: errors.append('Seleccioná un día válido.')
    return errors

@app.context_processor
def inject_globals():
    return dict(DAYS=DAYS, HOURS=HOURS, BARRIOS_LIBERIA=BARRIOS_LIBERIA, APP_PUBLIC_URL=APP_PUBLIC_URL)

@app.route('/')
def public_home():
    q = (request.args.get('q') or '').strip()
    cells = Cell.query.filter_by(status='active')
    if q:
        like = f'%{q}%'
        cells = cells.filter(db.or_(Cell.barrio.ilike(like), Cell.barrio_other.ilike(like), Cell.name.ilike(like), Cell.address.ilike(like), Cell.day.ilike(like)))
    cells = cells.order_by(Cell.name.asc()).all()
    return render_template('public_home.html', cells=cells, q=q)

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
        rows.append({'id':c.id,'name':c.name,'barrio':c.barrio_other or c.barrio,'leader':c.leader.name if c.leader else 'Por asignar','day':c.day,'time':c.time,'address':c.address,'phone':c.phone or (c.leader.phone if c.leader else ''),'maps':c.google_maps_url,'waze':c.waze_url,'description':c.description or 'Célula disponible para integrarte.','distance_km':round(km,2),'distance_label':f'{int(km*1000)} m' if km < 1 else f'{km:.1f} km'})
    rows.sort(key=lambda x:x['distance_km'])
    return jsonify({'ok': True, 'cells': rows[:12]})

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = (request.form.get('email') or '').lower().strip()
        password = request.form.get('password') or ''
        user = User.query.filter_by(email=email).first()
        if not user or not user.active or not user.check_password(password):
            flash('Credenciales incorrectas o usuario inactivo.', 'danger')
            return redirect(url_for('login'))
        login_user(user)
        if user.role == 'admin': return redirect(url_for('admin_dashboard'))
        return redirect(url_for('leader_dashboard'))
    return render_template('auth/login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user(); flash('Sesión cerrada correctamente.', 'success'); return redirect(url_for('public_home'))

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    stats = {'cells':Cell.query.count(),'active':Cell.query.filter_by(status='active').count(),'leaders':User.query.filter_by(role='leader').count(),'requests':LeadRequest.query.count()}
    recent = Cell.query.order_by(Cell.created_at.desc()).limit(6).all()
    return render_template('admin/dashboard.html', stats=stats, recent=recent)

@app.route('/admin/cells')
@login_required
@admin_required
def admin_cells():
    return render_template('admin/cells.html', cells=Cell.query.order_by(Cell.created_at.desc()).all())

@app.route('/admin/cells/new', methods=['GET','POST'])
@login_required
@admin_required
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
@admin_required
def admin_leaders():
    generated = None
    if request.method == 'POST':
        name=request.form.get('name','').strip(); email=request.form.get('email','').lower().strip(); phone=request.form.get('phone','').strip()
        password=request.form.get('password') or random_password()
        if not name or not email:
            flash('Nombre y correo son obligatorios.', 'danger'); return redirect(url_for('admin_leaders'))
        if User.query.filter_by(email=email).first():
            flash('Ya existe un usuario con ese correo.', 'danger'); return redirect(url_for('admin_leaders'))
        u=User(name=name,email=email,phone=phone,role='leader',active=True); u.set_password(password); db.session.add(u); db.session.commit()
        login_link = APP_PUBLIC_URL + url_for('login')
        body=f'Hola {name}. Bienvenido al equipo de líderes de Iglesia Hosanna. Acceso: {login_link} Usuario: {email} Contraseña: {password}'
        sent=False; sms_msg=''
        if request.form.get('send_sms') == 'on' and phone:
            sent, sms_msg = send_sms(phone, body); flash(sms_msg, 'success' if sent else 'warning')
        generated={'name':name,'email':email,'password':password,'phone':phone,'body':body,'sent':sent}
        flash('Líder creado correctamente.', 'success')
    return render_template('admin/leaders.html', leaders=User.query.filter_by(role='leader').order_by(User.created_at.desc()).all(), generated=generated)


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

@app.route('/leader')
@login_required
@leader_required
def leader_dashboard():
    c = Cell.query.filter_by(leader_id=current_user.id).first() if current_user.role=='leader' else None
    if current_user.role == 'admin': return redirect(url_for('admin_dashboard'))
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
    db.create_all(); print('Base actualizada.')

@app.cli.command('seed')
def seed():
    if not User.query.filter_by(email='admin@hosanna.local').first():
        admin=User(name='Administrador Hosanna',email='admin@hosanna.local',role='admin',active=True,phone='')
        admin.set_password('admin123'); db.session.add(admin)
    if not User.query.filter_by(email='lider@hosanna.local').first():
        leader=User(name='Líder Demo',email='lider@hosanna.local',role='leader',active=True,phone='88888888')
        leader.set_password('lider123'); db.session.add(leader); db.session.flush()
        cell=Cell(name='Célula Demo Nazareth',leader_id=leader.id,barrio='Nazareth',address='Liberia, Guanacaste',day='Miércoles',time='19:00',phone='88888888',description='Grupo familiar de prueba.',latitude=10.6350,longitude=-85.4377,status='active')
        cell.google_maps_url=maps_url(cell.latitude,cell.longitude); cell.waze_url=waze_url(cell.latitude,cell.longitude); db.session.add(cell)
    db.session.commit(); print('Datos iniciales creados.')

@app.errorhandler(403)
def e403(e): return render_template('errors/error.html', code=403, title='Acceso restringido', message='No tenés permiso para entrar a esta sección.'),403
@app.errorhandler(404)
def e404(e): return render_template('errors/error.html', code=404, title='Página no encontrada', message='La ruta que intentaste abrir no existe.'),404
@app.errorhandler(500)
def e500(e): return render_template('errors/error.html', code=500, title='Algo falló', message='El sistema tuvo un error inesperado.'),500

if __name__ == '__main__': app.run(debug=True)
