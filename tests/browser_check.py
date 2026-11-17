from pathlib import Path
from playwright.sync_api import sync_playwright
from subprocess import Popen
import os, tempfile, time, urllib.request, signal
root=Path(__file__).resolve().parents[1]
tdir=tempfile.TemporaryDirectory(prefix='pavza_browser_')
env=os.environ.copy();env.update(PAVZA_DATA_DIR=tdir.name,PAVZA_ALLOW_SUBMISSIONS='0',PAVZA_SITE_ENV='portfolio_demo',PAVZA_ADMIN_PASSWORD='BrowserQA_Secure123!',PYTHONUNBUFFERED='1')
p=Popen(['python','-m','uvicorn','server:app','--host','127.0.0.1','--port','8751'],cwd=str(root),env=env,stdout=open('/mnt/data/pavza_browser_log.txt','w'),stderr=-2)
try:
 for i in range(60):
  try:
   if urllib.request.urlopen('http://127.0.0.1:8751/api/health', timeout=2).status==200:break
  except Exception: time.sleep(.2)
 else: raise RuntimeError('Server not booted')
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  for name,viewport in [('desktop',{'width':1440,'height':900}),('mobile',{'width':390,'height':844})]:
   page=browser.new_page(viewport=viewport,device_scale_factor=1)
   errors=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto('http://127.0.0.1:8751/',wait_until='networkidle',timeout=30000)
   page.wait_for_timeout(1000)
   assert page.locator('h1').count()==1
   assert page.locator('#demoNotice').is_visible(), 'demo notice missing'
   assert page.locator('#bookingForm button[type="submit"]').is_disabled(), 'booking should be disabled'
   assert page.locator('#openReview').is_disabled(), 'review should be disabled'
   assert page.locator('.menu-card').count()==4, 'menu missing'
   assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth+1'), 'horizontal overflow'
   page.screenshot(path=f'/mnt/data/PAVZA_v4_{name}.png',full_page=(name=='desktop'),animations='disabled')
   if name=='mobile':
    page.locator('#mobileToggle').click()
    assert page.locator('#mobileNav').is_visible(), 'mobile nav hidden'
    page.locator('#mobileNav a[href="#menu"]').click()
    assert not page.locator('#mobileNav').is_visible(), 'nav not closing'
   print(name,'PASSED', 'menu',page.locator('.menu-card').count(),'js_errors',errors)
   assert not errors, f'js errors: {errors}'
   page.close()
  page=browser.new_page(viewport={'width':1360,'height':900})
  page.goto('http://127.0.0.1:8751/admin.html',wait_until='networkidle')
  assert page.locator('#loginPanel').is_visible()
  page.locator('input[name=password]').fill('BrowserQA_Secure123!')
  page.locator('#loginForm button[type=submit]').click()
  page.wait_for_timeout(700)
  assert page.locator('#adminPanel').is_visible(), 'admin panel failed to show'
  assert page.locator('#changePasswordForm').is_visible(), 'password form failed to show'
  page.screenshot(path='/mnt/data/PAVZA_v4_admin.png',full_page=True,animations='disabled')
  print('admin PASSED')
  page.close()
  browser.close()
finally:
 p.terminate()
 try:p.wait(timeout=5)
 except: p.kill()
 tdir.cleanup()
