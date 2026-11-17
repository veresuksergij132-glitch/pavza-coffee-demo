"""PAVZA v3 — small self-hosted demo with persistent SQLite and authenticated administration.
Run: pip install -r requirements.txt && uvicorn server:app --host 127.0.0.1 --port 8000
Never use demo content as a live cafe listing without real business details and policies.
"""
from __future__ import annotations

import csv
import logging
import threading
from urllib.request import Request as URLRequest, urlopen
from urllib.parse import urlparse
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

from fastapi import Cookie, FastAPI, Header, HTTPException, Request, Response, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

BASE = Path(__file__).resolve().parent
DATA = Path(os.getenv('PAVZA_DATA_DIR', str(BASE / '.pavza-data'))).resolve()
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / 'pavza.db'
LOCAL_ZONE = ZoneInfo(os.getenv('PAVZA_TIMEZONE', 'Europe/Kyiv'))
# Public demos never collect live visitors' phone numbers by default.
ALLOW_SUBMISSIONS = os.getenv('PAVZA_ALLOW_SUBMISSIONS', '0') == '1'
SITE_ENV = os.getenv('PAVZA_SITE_ENV', 'portfolio_demo')
MENU_IMAGES = {'flat-white.webp', 'cappuccino.webp', 'iced-latte.webp', 'croissant.webp'}
MEDIA_DIR = DATA / 'media'
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_LIMITS = {'image': 12 * 1024 * 1024, 'video': 80 * 1024 * 1024}
STATIC_IMAGES = {'assets/pavza-interior.webp','assets/pavza-mobile.webp','assets/pavza-editorial-detail.webp','assets/flat-white.webp','assets/cappuccino.webp','assets/iced-latte.webp','assets/croissant.webp'}
STATIC_VIDEOS = {'assets/pavza-photo-motion.mp4'}
CATEGORIES = {'coffee', 'cold', 'bakery'}
SLOTS = [f'{i:02d}:00' for i in range(9, 20)]
TABLES = [('T1', 2), ('T2', 2), ('T3', 4), ('T4', 4), ('T5', 6)]  # illustrative demo floor plan
RESERVATION_MINUTES = 90
app = FastAPI(title='PAVZA API', docs_url=None, redoc_url=None, openapi_url=None)

# A local password is generated once if setup env is omitted; never hardcode it into source or ZIP.
def save_private(path: Path, value: str):
    path.write_text(value, encoding='utf-8')
    try:
        path.chmod(0o600)
    except OSError:
        pass

SECRET_PATH = DATA / 'session.key'
if os.getenv('PAVZA_SESSION_SECRET'):
    SIGNING_KEY = os.environ['PAVZA_SESSION_SECRET'].encode()
elif SECRET_PATH.exists():
    SIGNING_KEY = SECRET_PATH.read_bytes()
else:
    SIGNING_KEY = secrets.token_bytes(32)
    SECRET_PATH.write_bytes(SIGNING_KEY)
    try:
        SECRET_PATH.chmod(0o600)
    except OSError:
        pass


def db():
    cx = sqlite3.connect(DB_PATH, timeout=5, isolation_level=None)
    cx.row_factory = sqlite3.Row
    cx.execute('PRAGMA journal_mode=WAL')
    cx.execute('PRAGMA busy_timeout=5000')
    cx.execute('PRAGMA foreign_keys=ON')
    return cx


def pbkdf2_hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 260_000).hex()


def initialize():
    with db() as cx:
        cx.executescript('''
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS menu (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
            description TEXT NOT NULL, price INTEGER NOT NULL, image TEXT NOT NULL,
            badge TEXT NOT NULL DEFAULT '', display_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, author TEXT NOT NULL, rating INTEGER NOT NULL,
            message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', consent INTEGER NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guest_name TEXT NOT NULL,
            guest_phone TEXT NOT NULL, guests INTEGER NOT NULL, note TEXT NOT NULL,
            visit_date TEXT NOT NULL, visit_time TEXT NOT NULL, table_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_bookings_time ON bookings(visit_date,visit_time,status,table_id);
        CREATE TABLE IF NOT EXISTS metrics (date TEXT NOT NULL, event TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(date,event));
        ''')
        cx.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('session_epoch','0')")
        if cx.execute('SELECT COUNT(*) FROM menu').fetchone()[0] == 0:
            items = [
                ('flat', 'Flat White', 'coffee', 'Подвійне еспресо, шовковисте молоко · 180 мл', 95, 'flat-white.webp', 'Ніжна класика', 0),
                ('cappuccino', 'Капучино', 'coffee', 'Насичена кава та молочна пінка · 250 мл', 85, 'cappuccino.webp', 'Улюблений', 1),
                ('iced', 'Iced Latte', 'cold', 'Еспресо, холодне молоко та лід · 300 мл', 105, 'iced-latte.webp', 'Освіжає', 2),
                ('croissant', 'Мигдальний круасан', 'bakery', 'Хрустка скоринка, мигдаль та ніжна начинка', 110, 'croissant.webp', 'До кави', 3),
            ]
            cx.executemany('INSERT INTO menu VALUES (?,?,?,?,?,?,?,?)', items)
        if not cx.execute("SELECT 1 FROM settings WHERE key='admin_hash'").fetchone():
            initial_password = os.getenv('PAVZA_ADMIN_PASSWORD', '')
            generated = not initial_password
            if generated:
                initial_password = secrets.token_urlsafe(18)
            if len(initial_password) < 12:
                raise RuntimeError('PAVZA_ADMIN_PASSWORD must be at least 12 characters')
            salt = secrets.token_bytes(16)
            cx.execute("INSERT INTO settings VALUES('admin_salt',?)", (salt.hex(),))
            cx.execute("INSERT INTO settings VALUES('admin_hash',?)", (pbkdf2_hash(initial_password,salt),))
            if generated:
                path = DATA / 'initial-admin-password.txt'
                save_private(path, f'ЛОКАЛЬНИЙ ДЕМО-ДОСТУП PAVZA\nLogin: admin\nPassword: {initial_password}\nOnly for this local instance. Do not publish this file.\n')
                print(f'\nPAVZA: initial admin password saved locally to {path}\n')
        else:
            # Environment password isn't a reset mechanism: this prevents silent credential changes.
            pass

initialize()

# In-memory throttling prevents casual automated requests; use a perimeter rate limiter in production.
RATE_LOCK = Lock()
RATE: dict[str, deque] = defaultdict(deque)

def throttle(request: Request, group: str, count: int, span: int):
    key = f'{group}:{request.client.host if request.client else "unknown"}'
    with RATE_LOCK:
        now = time.monotonic()
        q = RATE[key]
        while q and q[0] < now-span:
            q.popleft()
        if len(q) >= count:
            raise HTTPException(429, detail='Забагато спроб. Повторіть пізніше.')
        q.append(now)


def utcnow() -> str:
    return datetime.now(tz=ZoneInfo('UTC')).isoformat(timespec='seconds')


def table_available(cx, visit_day: str, visit_time: str, guests: int):
    target = datetime.strptime(visit_time, '%H:%M')
    bookings = cx.execute("SELECT visit_time, table_id FROM bookings WHERE visit_date=? AND status IN ('pending','confirmed')", (visit_day,)).fetchall()
    occupied = set()
    for b in bookings:
        old = datetime.strptime(b['visit_time'], '%H:%M')
        if abs((target - old).total_seconds()) < RESERVATION_MINUTES * 60:
            occupied.add(b['table_id'])
    for tid, seats in sorted(TABLES, key=lambda x: x[1]):
        if seats >= guests and tid not in occupied:
            return tid
    return None


def date_valid(day: str, visit_time: str|None = None):
    try:
        d = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(422, detail='Неправильна дата')
    today = datetime.now(LOCAL_ZONE).date()
    if d < today or d > today + timedelta(days=30):
        raise HTTPException(422, detail='Доступні дати: сьогодні й наступні 30 днів')
    if visit_time:
        if visit_time not in SLOTS:
            raise HTTPException(422, detail='Неприпустимий час')
        at = datetime.combine(d, datetime.strptime(visit_time, '%H:%M').time(), tzinfo=LOCAL_ZONE)
        if at < datetime.now(LOCAL_ZONE) + timedelta(minutes=30):
            raise HTTPException(422, detail='Оберіть час щонайменше за 30 хвилин від зараз')
    return d


class BookingInput(BaseModel):
    guestName: str = Field(min_length=2, max_length=70)
    guestPhone: str = Field(min_length=7, max_length=30)
    visitDate: str
    visitTime: str
    guestCount: int = Field(ge=1, le=6)
    guestNote: str = Field(default='', max_length=120)
    website: str = ''  # honeypot (must remain empty)

    @field_validator('guestPhone')
    @classmethod
    def good_phone(cls, s):
        if not re.fullmatch(r'[+\d\s()\-]{7,30}', s) or len(re.sub(r'\D','',s)) < 7:
            raise ValueError('Вкажіть коректний номер телефону')
        return s


class ReviewInput(BaseModel):
    author: str = Field(min_length=2, max_length=45)
    rating: int = Field(ge=1, le=5)
    message: str = Field(min_length=10, max_length=320)
    consent: bool
    website: str = ''


class MenuInput(BaseModel):
    id: str = Field(min_length=1, max_length=45)
    name: str = Field(min_length=2, max_length=65)
    category: str
    description: str = Field(min_length=2, max_length=150)
    price: int = Field(ge=1, le=99999)
    image: str
    badge: str = Field(default='', max_length=30)

    @field_validator('category')
    @classmethod
    def category_check(cls, s):
        if s not in CATEGORIES:
            raise ValueError('Unknown category')
        return s

    @field_validator('image')
    @classmethod
    def image_check(cls, s):
        if s not in MENU_IMAGES and not is_approved_media(s, 'image'):
            raise ValueError('Unknown image')
        return s

    @field_validator('id')
    @classmethod
    def id_check(cls, s):
        if not re.fullmatch(r'[A-Za-z0-9-]{1,45}', s):
            raise ValueError('Invalid item id')
        return s


DEFAULT_CONTENT = {
    'hero': {
        'eyebrow':'SPECIALTY COFFEE & SLOW DAYS',
        'titleTop':'Усе', 'titleAccent':'почекає.',
        'description':'Крім миті з доброю кавою. Заходь по свій час — повільний, теплий і справжній.',
        'poster':'assets/pavza-interior.webp',
        'video':'assets/pavza-photo-motion.mp4',
        'detailImage':'assets/pavza-editorial-detail.webp'
    },
    'services': [
        {'title':'Specialty кава','description':'Ароматні зерна, точна екстракція та смак із характером.','image':'assets/flat-white.webp'},
        {'title':'Свіжа випічка','description':'Мигдальні круасани й теплі дрібниці до чашки кави.','image':'assets/croissant.webp'},
        {'title':'Кава з собою','description':'Забери свою улюблену паузу з собою в місто.','image':'assets/cappuccino.webp'}
    ]
}

def is_approved_media(value: str, kind: str) -> bool:
    if not isinstance(value,str): return False
    if kind == 'image' and value in STATIC_IMAGES: return True
    if kind == 'video' and value in STATIC_VIDEOS: return True
    if not re.fullmatch(r'/media/[a-zA-Z0-9_-]{8,64}\.(?:webp|jpe?g|png|mp4|webm)',value): return False
    suffix=value.rsplit('.',1)[-1]
    if kind=='image' and suffix not in ('webp','jpg','jpeg','png'): return False
    if kind=='video' and suffix not in ('mp4','webm'): return False
    return (MEDIA_DIR / value.split('/')[-1]).is_file()

class HeroInput(BaseModel):
    eyebrow: str = Field(max_length=75)
    titleTop: str = Field(min_length=1,max_length=25)
    titleAccent: str = Field(min_length=1,max_length=25)
    description: str = Field(min_length=8,max_length=260)
    poster: str
    video: str
    detailImage: str

    @field_validator('poster','detailImage')
    @classmethod
    def image_ok(cls,v):
        if not is_approved_media(v,'image'): raise ValueError('Оберіть доступне фото з медіатеки')
        return v
    @field_validator('video')
    @classmethod
    def video_ok(cls,v):
        if v and not is_approved_media(v,'video'): raise ValueError('Оберіть доступне відео з медіатеки')
        return v

class ServiceInput(BaseModel):
    title: str = Field(min_length=2,max_length=55)
    description: str = Field(min_length=4,max_length=220)
    image: str
    @field_validator('image')
    @classmethod
    def image_ok(cls,v):
        if not is_approved_media(v,'image'): raise ValueError('Оберіть доступне фото')
        return v

def get_content():
    with db() as cx:
        row=cx.execute("SELECT value FROM settings WHERE key='site_content'").fetchone()
    if row:
        try: return json.loads(row[0])
        except (ValueError,TypeError): pass
    return json.loads(json.dumps(DEFAULT_CONTENT))

def save_content(value):
    with db() as cx:
        cx.execute("INSERT INTO settings(key,value) VALUES('site_content',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(value,ensure_ascii=False),))

@app.get('/api/content')
def public_content():
    return get_content()

@app.get('/media/{filename}')
def serve_media(filename:str):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{8,64}\.(?:webp|jpe?g|png|mp4|webm)',filename):
        raise HTTPException(404,detail='Файл не знайдено')
    path=MEDIA_DIR / filename
    if not path.is_file(): raise HTTPException(404,detail='Файл не знайдено')
    media='video/mp4' if filename.endswith('.mp4') else 'video/webm' if filename.endswith('.webm') else 'image/'+ ('jpeg' if filename.endswith(('.jpg','.jpeg')) else filename.rsplit('.',1)[-1])
    return FileResponse(path,media_type=media,headers={'Cache-Control':'public, max-age=86400'})

@app.get('/api/admin/content')
def admin_content(request:Request):
    require_admin(request)
    return get_content()

@app.put('/api/admin/hero')
def update_hero(data:HeroInput, request:Request):
    require_admin(request,csrf=True)
    content=get_content();content['hero']=data.model_dump();save_content(content)
    return {'ok':True,'hero':content['hero']}

@app.put('/api/admin/services')
def update_services(items:list[ServiceInput], request:Request):
    require_admin(request,csrf=True)
    if len(items)>12: raise HTTPException(422,detail='Максимум 12 послуг')
    content=get_content();content['services']=[x.model_dump() for x in items];save_content(content)
    return {'ok':True,'services':content['services']}

@app.get('/api/admin/media')
def list_media(request:Request):
    require_admin(request)
    files=[]
    for p in sorted(MEDIA_DIR.iterdir(),key=lambda v:v.stat().st_mtime,reverse=True):
        if p.is_file() and re.fullmatch(r'[a-zA-Z0-9_-]{8,64}\.(?:webp|jpe?g|png|mp4|webm)',p.name):
            files.append({'url':'/media/'+p.name,'name':p.name,'kind':'video' if p.suffix in ('.mp4','.webm') else 'image','size':p.stat().st_size})
    return {'files':files[:100]}

@app.post('/api/admin/media/upload',status_code=201)
async def upload_media(request:Request, file:UploadFile=File(...)):
    require_admin(request,csrf=True)
    throttle(request,'media_upload',25,3600)
    original=Path(file.filename or '').suffix.lower()
    image_exts={'.jpg','.jpeg','.png','.webp'}
    video_exts={'.mp4','.webm'}
    if original not in image_exts|video_exts:
        raise HTTPException(415,detail='Лише JPG, PNG, WebP, MP4 або WebM')
    kind='image' if original in image_exts else 'video'
    cap=MEDIA_LIMITS[kind]
    if request.headers.get('content-length') and int(request.headers['content-length'])>cap+4096:
        raise HTTPException(413,detail='Файл завеликий')
    name=secrets.token_hex(14)+original
    dest=MEDIA_DIR/name
    length=0
    head=b''
    try:
        with dest.open('xb') as stream:
            while True:
                chunk=await file.read(512*1024)
                if not chunk: break
                if not head: head=chunk[:24]
                length+=len(chunk)
                if length>cap: raise HTTPException(413,detail='Файл завеликий')
                stream.write(chunk)
        # Reject spoofed content instead of trusting filename or Content-Type.
        valid=(original in ('.jpg','.jpeg') and head.startswith(b'\xff\xd8\xff')) or (original=='.png' and head.startswith(b'\x89PNG\r\n\x1a\n')) or (original=='.webp' and head.startswith(b'RIFF') and head[8:12]==b'WEBP') or (original=='.mp4' and head[4:8]==b'ftyp') or (original=='.webm' and head.startswith(b'\x1a\x45\xdf\xa3'))
        if not valid or length<32: raise HTTPException(415,detail='Формат файла не відповідає розширенню')
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return {'ok':True,'url':'/media/'+name,'kind':kind,'size':length}

# Private, one-shot import of the owner's provided Freepik video.
# The expiring signed URL is an environment variable, never committed to the public repository.
def import_hero_video_once():
    url=os.getenv('PAVZA_IMPORT_HERO_VIDEO_URL','').strip()
    if not url: return
    fixed=MEDIA_DIR/'pavza_hero_import.mp4'
    if not fixed.is_file():
        temp=MEDIA_DIR/'pavza_hero_import.part'
        try:
            parsed=urlparse(url)
            if parsed.scheme!='https' or parsed.hostname!='pikaso.cdnpk.net': raise ValueError('Недозволене джерело відео')
            req=URLRequest(url,headers={'User-Agent':'PAVZA-MediaImport/1.0'})
            with urlopen(req,timeout=35) as response:
                if urlparse(response.url).hostname!='pikaso.cdnpk.net': raise ValueError('Недозволене переспрямування')
                length=0; head=b''
                with temp.open('wb') as fp:
                    while True:
                        chunk=response.read(512*1024)
                        if not chunk: break
                        if not head: head=chunk[:24]
                        length+=len(chunk)
                        if length>MEDIA_LIMITS['video']: raise ValueError('Відео більше 80 МБ')
                        fp.write(chunk)
                if head[4:8]!=b'ftyp' or length<1024: raise ValueError('Отриманий файл не є MP4')
                temp.replace(fixed)
        except Exception as exc:
            logging.warning('PAVZA hero video import unsuccessful: %s',type(exc).__name__)
            temp.unlink(missing_ok=True)
            return
    content=get_content()
    # Do not overwrite a video the owner already selected in admin.
    if content['hero']['video']==DEFAULT_CONTENT['hero']['video']:
        content['hero']['video']='/media/pavza_hero_import.mp4'
        save_content(content)
    logging.info('PAVZA hero video ready on persistent storage')

if os.getenv('PAVZA_IMPORT_HERO_VIDEO_URL'):
    threading.Thread(target=import_hero_video_once,daemon=True).start()

class LoginInput(BaseModel):
    password: str


class StatusInput(BaseModel):
    status: str


class PasswordChangeInput(BaseModel):
    oldPassword: str
    newPassword: str = Field(min_length=12, max_length=200)


def public_menu():
    with db() as cx:
        return [dict(row) for row in cx.execute('SELECT id,name,category,description,price,image,badge FROM menu ORDER BY display_order')]


@app.get('/api/health')
def health():
    try:
        with db() as cx:
            cx.execute('SELECT 1').fetchone()
        return {'ok': True, 'mode': SITE_ENV}
    except sqlite3.Error:
        raise HTTPException(503, detail='База даних недоступна')


@app.get('/api/config')
def config():
    return {'siteMode': SITE_ENV, 'allowSubmissions': ALLOW_SUBMISSIONS,
            'bookingDurationMinutes': RESERVATION_MINUTES, 'timezone': str(LOCAL_ZONE)}


@app.get('/api/menu')
def get_menu():
    return {'items': public_menu()}


@app.get('/api/reviews')
def get_reviews():
    with db() as cx:
        return {'items': [dict(row) for row in cx.execute("SELECT id,author,rating,message,created_at FROM reviews WHERE status='approved' ORDER BY id DESC LIMIT 20")]}


@app.post('/api/reviews', status_code=201)
def create_review(data: ReviewInput, request: Request):
    if not ALLOW_SUBMISSIONS:
        raise HTTPException(403, detail='Це публічне демо. Надсилання відгуків наразі вимкнено.')
    throttle(request, 'review', 4, 3600)
    if data.website or not data.consent:
        raise HTTPException(422, detail='Потрібна згода на публікацію після модерації')
    now = utcnow()
    with db() as cx:
        cur = cx.execute('INSERT INTO reviews(author,rating,message,status,consent,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
            (data.author.strip(),data.rating,data.message.strip(),'pending',1,now,now))
        return {'id':cur.lastrowid,'status':'pending','message':'Відгук надіслано на модерацію'}


@app.get('/api/availability')
def availability(visitDate: str, guestCount: int):
    if guestCount < 1 or guestCount > 6:
        raise HTTPException(422, detail='Кількість гостей: 1–6')
    date_valid(visitDate)
    with db() as cx:
        return {'date':visitDate,'guests':guestCount,'slots':[{'time':t,'available':bool(table_available(cx,visitDate,t,guestCount)) and is_future(visitDate,t)} for t in SLOTS], 'timezone':str(LOCAL_ZONE)}


def is_future(day: str, slot: str):
    return datetime.combine(date.fromisoformat(day),datetime.strptime(slot,'%H:%M').time(),tzinfo=LOCAL_ZONE) >= datetime.now(LOCAL_ZONE)+timedelta(minutes=30)


@app.post('/api/bookings', status_code=201)
def create_booking(data: BookingInput, request: Request):
    if not ALLOW_SUBMISSIONS:
        raise HTTPException(403, detail='Це публічне демо. Надсилання бронювань наразі вимкнено.')
    throttle(request,'booking',5,3600)
    if data.website:
        raise HTTPException(422, detail='Не вдалося обробити запит')
    date_valid(data.visitDate,data.visitTime)
    now = utcnow()
    cx = db()
    try:
        cx.execute('BEGIN IMMEDIATE')
        table_id = table_available(cx, data.visitDate, data.visitTime, data.guestCount)
        if not table_id:
            cx.rollback()
            raise HTTPException(409, detail='На цей час немає вільного столика. Спробуйте інший час.')
        cur = cx.execute('INSERT INTO bookings(guest_name,guest_phone,guests,note,visit_date,visit_time,table_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (data.guestName.strip(), data.guestPhone.strip(),data.guestCount,data.guestNote.strip(),data.visitDate,data.visitTime,table_id,'pending',now,now))
        cx.commit()
        return {'id':cur.lastrowid,'status':'pending','message':'Запит зареєстровано. Це демонстраційний сайт: бронювання не підтверджене реальним закладом.'}
    except:
        if cx.in_transaction:
            cx.rollback()
        raise
    finally:
        cx.close()


@app.post('/api/events')
async def events(request: Request):
    throttle(request,'metrics',90,60)
    body = await request.json()
    event = body.get('event') if isinstance(body,dict) else None
    if event not in {'page_view','menu_view','booking_click','review_click','booking_request'}:
        raise HTTPException(422,detail='Неприпустима подія')
    d = datetime.now(LOCAL_ZONE).date().isoformat()
    with db() as cx:
        cx.execute('INSERT INTO metrics(date,event,count) VALUES(?,?,1) ON CONFLICT(date,event) DO UPDATE SET count=count+1',(d,event))
    return {'ok':True}


def current_session_epoch() -> int:
    with db() as cx:
        return int(cx.execute("SELECT value FROM settings WHERE key='session_epoch'").fetchone()[0])


def create_token():
    expires = int(time.time()) + 3600 * 8
    raw = f'admin:{expires}:{current_session_epoch()}:{secrets.token_hex(12)}'
    sig = hmac.new(SIGNING_KEY, raw.encode(), hashlib.sha256).hexdigest()
    return f'{raw}:{sig}'


def verify_token(token: str | None):
    if not token:
        return False
    parts = token.split(':')
    if len(parts)!=5 or parts[0]!='admin':
        return False
    raw = ':'.join(parts[:4])
    sig = hmac.new(SIGNING_KEY, raw.encode(), hashlib.sha256).hexdigest()
    try:
        return (int(parts[1]) > time.time()
                and int(parts[2]) == current_session_epoch()
                and hmac.compare_digest(sig,parts[4]))
    except (ValueError, sqlite3.Error):
        return False


def csrf_value(token: str):
    return hmac.new(SIGNING_KEY,('csrf:'+token).encode(),hashlib.sha256).hexdigest()


def require_admin(request: Request, csrf: bool = False):
    session = request.cookies.get('pavza_session')
    if not verify_token(session):
        raise HTTPException(401, detail='Увійдіть в адмінпанель')
    if csrf:
        supplied = request.headers.get('X-PAVZA-CSRF','')
        if not hmac.compare_digest(supplied,csrf_value(session)):
            raise HTTPException(403,detail='Неправильний токен захисту')
        # Compare browser Origin hostname with the actual Host: works behind HTTPS ingress
        # without trusting client-controlled X-Forwarded-Proto for CSRF decisions.
        origin = request.headers.get('Origin')
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in ('http','https') or parsed.netloc.lower() != request.headers.get('host','').lower():
                raise HTTPException(403,detail='Невірне походження запиту')


@app.post('/api/admin/login')
def login(data: LoginInput,request: Request,response: Response):
    throttle(request,'login',8,900)
    with db() as cx:
        salt = bytes.fromhex(cx.execute("SELECT value FROM settings WHERE key='admin_salt'").fetchone()[0])
        expected = cx.execute("SELECT value FROM settings WHERE key='admin_hash'").fetchone()[0]
    if not hmac.compare_digest(pbkdf2_hash(data.password,salt),expected):
        raise HTTPException(401,detail='Невірний пароль')
    token = create_token()
    secure = request.url.scheme == 'https' or request.headers.get('x-forwarded-proto') == 'https'
    response.set_cookie('pavza_session',token,httponly=True,secure=secure,samesite='lax',max_age=8*3600,path='/')
    return {'authenticated':True,'csrf':csrf_value(token)}


@app.post('/api/admin/change-password')
def change_password(data: PasswordChangeInput, request: Request, response: Response):
    require_admin(request, csrf=True)
    throttle(request,'password_change',4,900)
    if data.oldPassword == data.newPassword:
        raise HTTPException(422,detail='Новий пароль повинен відрізнятися від старого')
    with db() as cx:
        cx.execute('BEGIN IMMEDIATE')
        salt = bytes.fromhex(cx.execute("SELECT value FROM settings WHERE key='admin_salt'").fetchone()[0])
        expected = cx.execute("SELECT value FROM settings WHERE key='admin_hash'").fetchone()[0]
        if not hmac.compare_digest(pbkdf2_hash(data.oldPassword,salt),expected):
            raise HTTPException(401,detail='Поточний пароль невірний')
        new_salt = secrets.token_bytes(16)
        cx.execute("UPDATE settings SET value=? WHERE key='admin_salt'",(new_salt.hex(),))
        cx.execute("UPDATE settings SET value=? WHERE key='admin_hash'",(pbkdf2_hash(data.newPassword,new_salt),))
        cx.execute("UPDATE settings SET value=CAST(value AS INTEGER)+1 WHERE key='session_epoch'")
        cx.commit()
    # Revoke every previous session after password rotation.
    response.delete_cookie('pavza_session',path='/')
    return {'ok':True,'message':'Пароль змінено. Увійдіть знову.'}


@app.get('/api/admin/session')
def session(request: Request):
    token = request.cookies.get('pavza_session')
    return {'authenticated':verify_token(token),'csrf':csrf_value(token) if verify_token(token) else None}


@app.post('/api/admin/logout')
def logout(request: Request,response: Response):
    require_admin(request,csrf=True)
    response.delete_cookie('pavza_session',path='/')
    return {'ok':True}


@app.get('/api/admin/overview')
def overview(request: Request):
    require_admin(request)
    with db() as cx:
        return {'bookings': [dict(x) for x in cx.execute('SELECT id,guest_name,guest_phone,guests,note,visit_date,visit_time,table_id,status,created_at FROM bookings ORDER BY visit_date DESC, visit_time DESC LIMIT 100')],
            'reviews': [dict(x) for x in cx.execute('SELECT id,author,rating,message,status,created_at FROM reviews ORDER BY id DESC LIMIT 100')],
            'metrics':[dict(x) for x in cx.execute("SELECT event,SUM(count) AS count FROM metrics GROUP BY event ORDER BY event")],
            'menu':public_menu()}


@app.put('/api/admin/menu')
def update_menu(items: list[MenuInput],request: Request):
    require_admin(request,csrf=True)
    if not 1<=len(items)<=30 or len({x.id for x in items})!=len(items):
        raise HTTPException(422,detail='Від 1 до 30 позицій, ID без повторів')
    with db() as cx:
        cx.execute('BEGIN IMMEDIATE')
        cx.execute('DELETE FROM menu')
        cx.executemany('INSERT INTO menu(id,name,category,description,price,image,badge,display_order) VALUES(?,?,?,?,?,?,?,?)',
            [(x.id,x.name.strip(),x.category,x.description.strip(),x.price,x.image,x.badge.strip(),i) for i,x in enumerate(items)])
        cx.commit()
    return {'ok':True}


@app.patch('/api/admin/reviews/{review_id}')
def update_review(review_id:int,data:StatusInput,request:Request):
    require_admin(request,csrf=True)
    if data.status not in {'approved','rejected','pending'}:
        raise HTTPException(422,detail='Невірний статус')
    with db() as cx:
        cur = cx.execute('UPDATE reviews SET status=?,updated_at=? WHERE id=?',(data.status,utcnow(),review_id))
        if not cur.rowcount:
            raise HTTPException(404,detail='Відгук не знайдено')
    return {'ok':True}


@app.delete('/api/admin/reviews/{review_id}')
def delete_review(review_id: int, request: Request):
    require_admin(request, csrf=True)
    with db() as cx:
        cur=cx.execute('DELETE FROM reviews WHERE id=?',(review_id,))
        if not cur.rowcount:
            raise HTTPException(404, detail='Відгук не знайдено')
    return {'ok':True}


@app.patch('/api/admin/bookings/{booking_id}')
def update_booking(booking_id:int,data:StatusInput,request:Request):
    require_admin(request,csrf=True)
    if data.status not in {'confirmed','rejected','cancelled','pending'}:
        raise HTTPException(422,detail='Невірний статус')
    cx = db()
    try:
        cx.execute('BEGIN IMMEDIATE')
        row=cx.execute('SELECT * FROM bookings WHERE id=?',(booking_id,)).fetchone()
        if not row:
            raise HTTPException(404,detail='Запит не знайдено')
        if data.status in {'pending','confirmed'} and row['status'] not in {'pending','confirmed'}:
            tid=table_available(cx,row['visit_date'],row['visit_time'],row['guests'])
            if not tid:
                raise HTTPException(409,detail='Столик на цей час уже зайнятий')
            cx.execute('UPDATE bookings SET table_id=? WHERE id=?',(tid,booking_id))
        cx.execute('UPDATE bookings SET status=?,updated_at=? WHERE id=?',(data.status,utcnow(),booking_id))
        cx.commit()
        return {'ok':True}
    except:
        if cx.in_transaction:
            cx.rollback()
        raise
    finally:
        cx.close()


@app.delete('/api/admin/bookings/{booking_id}')
def delete_booking(booking_id:int, request:Request):
    require_admin(request,csrf=True)
    with db() as cx:
        cur=cx.execute('DELETE FROM bookings WHERE id=?',(booking_id,))
        if not cur.rowcount:
            raise HTTPException(404,detail='Запит не знайдено')
    return {'ok':True}


@app.get('/api/admin/bookings.csv')
def export_booking(request:Request):
    require_admin(request)
    out=io.StringIO()
    writer=csv.writer(out)
    cols=['id','guest_name','guest_phone','guests','visit_date','visit_time','status','note']
    writer.writerow(cols)
    with db() as cx:
        for row in cx.execute('SELECT '+','.join(cols)+' FROM bookings ORDER BY visit_date DESC'):
            writer.writerow(['\''+str(row[k]) if str(row[k]).startswith(('=','+','-','@')) else row[k] for k in cols])
    payload=out.getvalue().encode('utf-8-sig')
    return Response(content=payload,media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="pavza-bookings.csv"','Cache-Control':'no-store'})


@app.middleware('http')
async def privacy_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy']=("default-src 'self'; base-uri 'self'; form-action 'self'; object-src 'none'; "
        "frame-ancestors 'none'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; media-src 'self'; connect-src 'self'")
    response.headers['X-Robots-Tag']='noindex, nofollow' if SITE_ENV=='portfolio_demo' else 'index, follow'
    if request.url.path.startswith('/api/') or request.url.path.startswith('/admin'):
        response.headers['Cache-Control']='no-store'
    return response


# Keep static mount last so /api/* and /api/admin/* always resolve to authenticated endpoints.
app.mount('/',StaticFiles(directory=BASE / 'public',html=True),name='static')
