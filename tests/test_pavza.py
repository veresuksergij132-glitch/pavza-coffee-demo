"""Isolated API integration checks. `pytest -q` from the v4 directory."""
import os, sys, tempfile, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_TEST_DATA=tempfile.TemporaryDirectory(prefix='pavza_test_')
os.environ['PAVZA_DATA_DIR']=_TEST_DATA.name
os.environ['PAVZA_ALLOW_SUBMISSIONS']='0'
os.environ['PAVZA_SITE_ENV']='portfolio_demo'
os.environ['PAVZA_ADMIN_PASSWORD']='S3cureDemoPassphrase!2026'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from fastapi.testclient import TestClient
client=TestClient(server.app)


def test_public_no_real_data():
    assert client.get('/').status_code==200
    assert client.get('/assets/pavza-interior.webp').status_code==200
    assert client.get('/api/health').json()['ok'] is True
    assert client.get('/api/config').json()['allowSubmissions'] is False
    assert client.get('/api/admin/overview').status_code==401
    assert client.get('/.pavza-data/pavza.db').status_code==404
    assert client.get('/api/health').headers['x-robots-tag']=='noindex, nofollow'
    assert client.post('/api/bookings',json={'guestName':'Демо','guestPhone':'+380991234567','visitDate':(datetime.datetime.now(ZoneInfo('Europe/Kyiv'))+datetime.timedelta(days=1)).date().isoformat(),'visitTime':'12:00','guestCount':2}).status_code==403
    assert client.post('/api/reviews',json={'author':'Демо','rating':5,'message':'Test only demo review','consent':True}).status_code==403


def test_admin_and_booking_lifecycle():
    wrong=client.post('/api/admin/login',json={'password':'123bad'})
    assert wrong.status_code==401
    r=client.post('/api/admin/login',json={'password':'S3cureDemoPassphrase!2026'})
    assert r.status_code==200
    csrf=r.json()['csrf']
    assert client.get('/api/admin/overview').status_code==200
    assert client.put('/api/admin/menu',json=[]).status_code==403
    assert client.put('/api/admin/menu',json=[{'id':'safe','name':'Safe coffee','category':'coffee','description':'A local coffee','price':101,'image':'flat-white.webp','badge':''}], headers={'X-PAVZA-CSRF':'bad'}).status_code==403
    assert client.put('/api/admin/menu',json=[{'id':'safe','name':'Safe coffee','category':'coffee','description':'A local coffee','price':101,'image':'flat-white.webp','badge':''}], headers={'X-PAVZA-CSRF':csrf,'Origin':'https://not-our-site.net'}).status_code==403
    headers={'X-PAVZA-CSRF':csrf}
    menu=[{'id':'safe','name':'Safe coffee','category':'coffee','description':'A local coffee','price':101,'image':'flat-white.webp','badge':''}]
    assert client.put('/api/admin/menu',json=menu,headers=headers).status_code==200
    assert client.get('/api/menu').json()['items'][0]['price']==101
    # Demo deliberately refuses public PII, but local integration testing may switch this flag.
    server.ALLOW_SUBMISSIONS=True
    now=datetime.datetime.now(ZoneInfo('Europe/Kyiv'))
    day=(now+datetime.timedelta(days=1)).date().isoformat()
    booking={'guestName':'Test Only','guestPhone':'+380991234567','visitDate':day,'visitTime':'12:00','guestCount':6,'guestNote':''}
    r=client.post('/api/bookings',json=booking)
    assert r.status_code==201,r.text
    booking_id=r.json()['id']
    # Only one six-seat table exists in the demo layout.
    assert client.post('/api/bookings',json=booking).status_code==409
    assert client.patch(f'/api/admin/bookings/{booking_id}',json={'status':'confirmed'},headers=headers).status_code==200
    assert client.post('/api/bookings',json=booking).status_code==409
    assert client.patch(f'/api/admin/bookings/{booking_id}',json={'status':'cancelled'},headers=headers).status_code==200
    assert client.post('/api/bookings',json=booking).status_code==201
    # Another person cannot see private bookings.
    unauthed=TestClient(server.app)
    assert unauthed.get('/api/admin/overview').status_code==401
    # Review submission + moderation + removal.
    rv=client.post('/api/reviews',json={'author':'Test Author','rating':4,'message':'A good demo review for testing','consent':True})
    assert rv.status_code==201
    review_id=rv.json()['id']
    assert client.get('/api/reviews').json()['items']==[]
    assert client.patch(f'/api/admin/reviews/{review_id}',json={'status':'approved'},headers=headers).status_code==200
    assert len(client.get('/api/reviews').json()['items'])==1
    assert client.delete(f'/api/admin/reviews/{review_id}',headers=headers).status_code==200
    assert client.get('/api/reviews').json()['items']==[]
    # Password rotation makes old tokens invalid.
    ch=client.post('/api/admin/change-password',json={'oldPassword':'S3cureDemoPassphrase!2026','newPassword':'N3wS3curePassword!2026'},headers=headers)
    assert ch.status_code==200,ch.text
    assert client.get('/api/admin/overview').status_code==401
    assert client.post('/api/admin/login',json={'password':'S3cureDemoPassphrase!2026'}).status_code==401
    assert client.post('/api/admin/login',json={'password':'N3wS3curePassword!2026'}).status_code==200
    server.ALLOW_SUBMISSIONS=False


def test_metrics_and_privacy():
    assert client.post('/api/events',json={'event':'page_view'}).status_code==200
    assert client.post('/api/events',json={'event':'invalid'}).status_code==422
    assert 'same-origin' not in client.get('/').headers.get('access-control-allow-origin','')
