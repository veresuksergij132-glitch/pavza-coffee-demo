import os, tempfile, importlib, sys, io
from pathlib import Path
from fastapi.testclient import TestClient
from PIL import Image

os.environ['PAVZA_DATA_DIR']=tempfile.mkdtemp(prefix='pavza_studio_')
os.environ['PAVZA_SITE_ENV']='portfolio_demo'
os.environ['PAVZA_ALLOW_SUBMISSIONS']='0'
os.environ['PAVZA_ADMIN_PASSWORD']='S3cureDemoPassphrase!2026'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
client=TestClient(server.app)

def test_media_permissions_and_persistence():
    before=client.get('/api/content').json()
    assert before['hero']['titleTop']=='Усе'
    assert len(before['services'])==3
    assert before['hero']['spaceImage']=='assets/pavza-gallery-wide.webp'
    assert client.get('/assets/pavza-gallery-wide.webp').status_code==200
    assert client.get('/api/admin/media').status_code==401
    assert client.put('/api/admin/hero',json=before['hero']).status_code==401
    auth=client.post('/api/admin/login',json={'password':'S3cureDemoPassphrase!2026'})
    assert auth.status_code==200
    csrf=auth.json()['csrf']
    headers={'X-PAVZA-CSRF':csrf}
    # Forged origin or invalid CSRF token cannot upload.
    pic=io.BytesIO();Image.new('RGB',(10,10),'green').save(pic,format='PNG');raw=pic.getvalue()
    assert client.post('/api/admin/media/upload',files={'file':('photo.png',raw,'image/png')}).status_code==403
    assert client.post('/api/admin/media/upload',files={'file':('photo.png',raw,'image/png')},headers={**headers,'Origin':'https://bad.example'}).status_code==403
    spoof=client.post('/api/admin/media/upload',files={'file':('bad.png',b'<html>not png</html>','image/png')},headers=headers)
    assert spoof.status_code==415
    up=client.post('/api/admin/media/upload',files={'file':('photo.png',raw,'image/png')},headers=headers)
    assert up.status_code==201,up.text
    url=up.json()['url']
    assert url.startswith('/media/')
    assert client.get(url).content==raw
    assert client.get('/media/../session.key').status_code==404
    listing=client.get('/api/admin/media').json()['files']
    assert any(x['url']==url for x in listing)
    newhero={**before['hero'],'titleTop':'Нова','titleAccent':'пауза.','poster':url,'detailImage':url}
    change=client.put('/api/admin/hero',json=newhero,headers=headers)
    assert change.status_code==200,change.text
    assert client.get('/api/content').json()['hero']['titleTop']=='Нова'
    assert client.put('/api/admin/hero',json={**newhero,'poster':'https://evil.com/image.png'},headers=headers).status_code==422
    services=[{'title':'Послуга 1','description':'Опис тестової послуги','image':url}]
    assert client.put('/api/admin/services',json=services,headers=headers).status_code==200
    assert client.get('/api/content').json()['services']==services
    assert client.put('/api/admin/services',json=services*13,headers=headers).status_code==422
    assert client.get('/api/config').json()['allowSubmissions'] is False
    assert client.get('/api/admin/overview').status_code==200
