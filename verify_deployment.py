#!/usr/bin/env python3
"""Read-only PAVZA smoke test: python verify_deployment.py https://your-domain.up.railway.app"""
import json
import sys
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

if len(sys.argv) != 2:
    raise SystemExit('Використання: python verify_deployment.py https://your-site.up.railway.app')
base = sys.argv[1].rstrip('/')
url = urlparse(base)
if url.scheme != 'https' or not url.netloc or url.username or url.password:
    raise SystemExit('Укажіть повний HTTPS URL без облікових даних.')

def get(path):
    req = Request(base + path, headers={'User-Agent':'PAVZA-ReadOnly-SmokeTest/1.0'})
    try:
        with urlopen(req, timeout=12) as r:
            return r.status, r.headers, r.read(2000000)
    except HTTPError as ex:
        return ex.code, ex.headers, ex.read(2000000)
    except (URLError, TimeoutError) as ex:
        raise RuntimeError(f'Не вдалось відкрити {path}: {ex}') from ex

checks=[]
def ok(what, yes):
    checks.append((what, bool(yes)))
    print(('OK  ' if yes else 'FAIL') + ' ' + what)

try:
    status, headers, body=get('/api/health')
    health=json.loads(body.decode()) if status==200 else {}
    ok('Сервер і база даних', status==200 and health.get('ok') is True)
    status, headers, body=get('/api/config')
    config=json.loads(body.decode()) if status==200 else {}
    ok('Демоформи вимкнені', status==200 and config.get('allowSubmissions') is False)
    ok('Портфоліо-режим', config.get('siteMode')=='portfolio_demo')
    status, headers, body=get('/api/menu')
    menu=json.loads(body.decode()) if status==200 else {}
    ok('Меню завантажується', status==200 and len(menu.get('items',[]))>=1)
    status, headers, body=get('/admin.html')
    ok('Сторінка адміністратора відкривається', status==200 and b'loginForm' in body)
    status, headers, body=get('/api/admin/overview')
    ok('Адміністративні дані захищені', status==401)
    status, headers, body=get('/')
    ok('Головна сторінка відкривається', status==200 and b'PAVZA' in body)
    ok('Демо не індексується', 'noindex' in headers.get('X-Robots-Tag','').lower())
    ok('CSP встановлено', bool(headers.get('Content-Security-Policy')))
    status, headers, body=get('/assets/pavza-interior.webp')
    ok('Фірмовий інтер’єр доступний', status==200 and len(body)>10000)
except Exception as exc:
    print('FAIL: '+str(exc), file=sys.stderr)
    sys.exit(2)
print(f'\nРезультат: {sum(p for _,p in checks)}/{len(checks)}')
sys.exit(0 if all(p for _,p in checks) else 1)
