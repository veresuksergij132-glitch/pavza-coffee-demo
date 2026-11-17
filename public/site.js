'use strict';
const $ = (s,root=document)=>root.querySelector(s);
const all = (s,root=document)=>Array.from(root.querySelectorAll(s));
const el = (tag,cls,txt)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(txt!==undefined)e.textContent=txt;return e};
const DEFAULT_MENU=[
{id:'flat',name:'Flat White',category:'coffee',description:'Подвійне еспресо, шовковисте молоко · 180 мл',price:95,image:'flat-white.webp',badge:'Ніжна класика'},
{id:'cappuccino',name:'Капучино',category:'coffee',description:'Насичена кава та молочна пінка · 250 мл',price:85,image:'cappuccino.webp',badge:'Улюблений'},
{id:'iced',name:'Iced Latte',category:'cold',description:'Еспресо, холодне молоко та лід · 300 мл',price:105,image:'iced-latte.webp',badge:'Освіжає'},
{id:'croissant',name:'Мигдальний круасан',category:'bakery',description:'Хрустка скоринка, мигдаль та ніжна начинка',price:110,image:'croissant.webp',badge:'До кави'}
];
const images = new Set(['flat-white.webp','cappuccino.webp','iced-latte.webp','croissant.webp']);
let menu=DEFAULT_MENU, category='all', apiLive=false, allowSubmissions=false;
async function loadConfig(){
  try { const c=await api('/api/config');allowSubmissions=!!c.allowSubmissions; }
  catch {allowSubmissions=false; }
  const bookingSubmit=$('#bookingForm button[type="submit"]');
  const reviewSubmit=$('#reviewForm button[type="submit"]');
  if(!allowSubmissions){
    [bookingSubmit,$('#openReview'),reviewSubmit].filter(Boolean).forEach(x=>{x.disabled=true;x.setAttribute('aria-disabled','true')});
    if(bookingSubmit)bookingSubmit.textContent='Демонстрація · бронювання вимкнено';
    const feedback=$('#bookingFeedback');if(feedback)feedback.textContent='Це портфоліо-концепт, а не чинна кав’ярня. Не вводьте справжні особисті дані.';
    const hint=$('#availabilityHint');if(hint)hint.textContent='Система бронювання готова до підключення реального закладу.';
    const notice=$('#demoNotice');if(notice)notice.hidden=false;
  }
}
async function api(path,method='GET',payload){const init={method,headers:{'Accept':'application/json'}};if(payload!==undefined){init.body=JSON.stringify(payload);init.headers['Content-Type']='application/json'}const r=await fetch(path,init);let data={};try{data=await r.json()}catch{};if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:`Помилка ${r.status}`);return data}
function renderMenu(){const rail=$('#menuRail');rail.replaceChildren();const items=menu.filter(m=>category==='all'||category===m.category);if(!items.length)rail.append(el('p','empty-menu','У цій категорії немає позицій.'));items.forEach(m=>{const card=el('article','menu-card'),media=el('div','menu-card-media'),img=el('img');img.src=resolveImage(m.image);img.alt='Фото: '+m.name;img.loading='lazy';img.width=750;img.height=750;media.append(img);if(m.badge)media.append(el('span','menu-card-tag',m.badge));const content=el('div','menu-card-content'),heading=el('div','menu-card-top');heading.append(el('h3','',m.name),el('strong','menu-card-price',String(m.price)+' ₴'));content.append(heading,el('p','',m.description));card.append(media,content);rail.append(card)});rail.scrollLeft=0}
async function loadMenu(){try{const d=await api('/api/menu');menu=d.items;apiLive=true}catch{apiLive=false;$('#serviceStatus')?.classList.add('is-offline')}renderMenu()}
all('[data-category]').forEach(b=>b.addEventListener('click',()=>{category=b.dataset.category;all('[data-category]').forEach(x=>{x.classList.toggle('active',x===b);x.setAttribute('aria-pressed',String(x===b))});renderMenu();track('menu_view')}));
for(const [id,dir] of [['prevMenu',-1],['nextMenu',1]]){$('#'+id)?.addEventListener('click',()=>{const rail=$('#menuRail'),w=rail.querySelector('.menu-card')?.getBoundingClientRect().width||310;rail.scrollBy({left:(w+20)*dir,behavior:window.matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth'})})}
const navToggle=$('#mobileToggle'),mobileNav=$('#mobileNav');navToggle?.addEventListener('click',()=>{const open=navToggle.getAttribute('aria-expanded')!=='true';navToggle.setAttribute('aria-expanded',String(open));mobileNav.hidden=!open});all('a',mobileNav).forEach(a=>a.addEventListener('click',()=>{mobileNav.hidden=true;navToggle.setAttribute('aria-expanded','false')}));
const observe=('IntersectionObserver' in window)?new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add('is-visible');observe.unobserve(entry.target)}}),{threshold:0.12}):null;all('.reveal').forEach(node=>observe?observe.observe(node):node.classList.add('is-visible'));
const motion=$('#heroMotion');if(motion && !window.matchMedia('(prefers-reduced-motion:reduce)').matches && !navigator.connection?.saveData && true){motion.addEventListener('playing',()=>motion.classList.add('is-playing'));motion.addEventListener('error',()=>motion.classList.remove('is-playing'));motion.load();motion.play().catch(()=>{});if('IntersectionObserver' in window){new IntersectionObserver(entries=>entries.forEach(entry=>entry.isIntersecting?motion.play().catch(()=>{}):motion.pause()),{threshold:.05}).observe(motion)}}else motion?.pause();
// Consent defaults to no analytics. No third-party tags are loaded on this demo.
const consentKey='pavza_metrics_consent_v1';let metricsConsent=localStorage.getItem(consentKey);
function renderConsent(){const bar=$('#analyticsConsent');if(bar)bar.hidden=metricsConsent!==null}
function track(event){if(metricsConsent==='yes' && apiLive)fetch('/api/events',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event}),keepalive:true}).catch(()=>{})}
$('#analyticsYes')?.addEventListener('click',()=>{metricsConsent='yes';localStorage.setItem(consentKey,'yes');renderConsent();track('page_view')});
$('#analyticsNo')?.addEventListener('click',()=>{metricsConsent='no';localStorage.setItem(consentKey,'no');renderConsent()});
$('#privacyOptions')?.addEventListener('click',()=>{metricsConsent=null;localStorage.removeItem(consentKey);renderConsent();$('#analyticsConsent').scrollIntoView({behavior:'smooth'})});
renderConsent();
const bookingForm=$('#bookingForm'),feedback=$('#bookingFeedback'),dateInput=$('#visitDate'),timeSelect=bookingForm?.elements.visitTime;
function localDay(){const d=new Date();return [d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-')}
if(dateInput){dateInput.min=localDay();const end=new Date();end.setDate(end.getDate()+30);dateInput.max=[end.getFullYear(),String(end.getMonth()+1).padStart(2,'0'),String(end.getDate()).padStart(2,'0')].join('-')}
const availabilityHint=$('#availabilityHint');
async function refreshAvailability(){if(!allowSubmissions)return;if(!dateInput.value||!timeSelect)return;const chosen=timeSelect.value;timeSelect.disabled=true;availabilityHint.textContent='Перевіряємо вільні години…';try{const d=await api(`/api/availability?visitDate=${encodeURIComponent(dateInput.value)}&guestCount=${encodeURIComponent(bookingForm.elements.guestCount.value)}`);timeSelect.replaceChildren(new Option('Оберіть час',''));d.slots.forEach(s=>{const op=new Option(s.time+(s.available?'':' · зайнято'),s.time);op.disabled=!s.available;timeSelect.append(op)});timeSelect.value=[...timeSelect.options].some(o=>o.value===chosen&&!o.disabled)?chosen:'';availabilityHint.textContent=`Вільні години з урахуванням наявних заявок. Часовий пояс: ${d.timezone}.`}catch(e){timeSelect.value='';availabilityHint.textContent='Немає зв’язку із сервером бронювання. Спробуйте пізніше.'}finally{timeSelect.disabled=false}}
dateInput?.addEventListener('change',refreshAvailability);bookingForm?.elements.guestCount.addEventListener('change',refreshAvailability);
bookingForm?.addEventListener('submit',async e=>{e.preventDefault();if(!allowSubmissions)return;const f=new FormData(bookingForm),data=Object.fromEntries(f.entries()),button=bookingForm.querySelector('button[type=submit]');data.guestCount=Number(data.guestCount);feedback.classList.add('has-result');button.disabled=true;feedback.textContent='Надсилаємо запит…';try{if(!apiLive)throw new Error('Потрібно відкрити сайт через запущений сервер PAVZA, а не як локальний HTML-файл.');const res=await api('/api/bookings','POST',data);feedback.textContent=`№ ${res.id} — запит записано. Це ДЕМО: реальна кав’ярня не підтвердила бронювання. Статус — очікує розгляду.`;track('booking_request');bookingForm.reset();await refreshAvailability()}catch(err){feedback.textContent=err.message}finally{button.disabled=false}});
async function renderReviews(){const root=$('#reviewList');root.replaceChildren();let reviews=[];try{reviews=(await api('/api/reviews')).items}catch{};if(!reviews.length){const empty=el('div','review-empty');empty.append(el('span','empty-icon','✳'));const box=el('div');box.append(el('strong','','Ваші історії — тут.'),el('p','','Опубліковані після модерації відгуки з’являться в цьому блоці. Вигаданих оцінок немає.'));empty.append(box);root.append(empty);return}reviews.slice(0,9).forEach(r=>{const card=el('article','review-item');card.append(el('div','stars','★'.repeat(r.rating)+'☆'.repeat(5-r.rating)),el('blockquote','',r.message),el('cite','',r.author),el('small','','Відгук, перевірений модератором · демопроєкт'));root.append(card)})}
const dialog=$('#reviewDialog');$('#openReview')?.addEventListener('click',()=>{track('review_click');dialog.showModal()});$('#closeReview')?.addEventListener('click',()=>dialog.close());dialog?.addEventListener('click',e=>{if(e.target===dialog)dialog.close()});$('#reviewForm')?.addEventListener('submit',async e=>{e.preventDefault();if(!allowSubmissions)return;const f=new FormData(e.currentTarget),note=$('#reviewNotice'),button=e.currentTarget.querySelector('button[type=submit]');button.disabled=true;try{if(!apiLive)throw new Error('Збереження доступне тільки через сервер PAVZA.');const result=await api('/api/reviews','POST',{author:f.get('author').trim(),rating:Number(f.get('rating')),message:f.get('message').trim(),consent:f.get('consent')==='on'});note.textContent=result.message+'. Дякуємо!';e.currentTarget.reset();await renderReviews()}catch(err){note.textContent=err.message}finally{button.disabled=false}});
all('a[href="#booking"]').forEach(a=>a.addEventListener('click',()=>track('booking_click')));
(async()=>{await loadConfig();await loadContent();await loadMenu();await renderReviews();if(metricsConsent==='yes')track('page_view')})();

function resolveImage(value){return (typeof value==='string' && (value.startsWith('/media/') || value.startsWith('assets/')))?value:'assets/'+(images.has(value)?value:'flat-white.webp')}
async function loadContent(){
  try{
    const data=await api('/api/content');const h=data.hero||{};
    for(const [field,id] of [['eyebrow','heroEyebrow'],['titleTop','heroTitleTop'],['titleAccent','heroTitleAccent'],['description','heroDescription']]){
      const node=$('#'+id);if(node && typeof h[field]==='string')node.textContent=h[field];
    }
    if(h.poster){const poster=$('.hero-poster');if(poster)poster.src=resolveImage(h.poster);if(motion)motion.poster=resolveImage(h.poster)}
    if(h.detailImage){const img=$('#heroDetailImage');if(img)img.src=resolveImage(h.detailImage)}
    if(motion){const source=$('#heroVideoSource');if(source){const target=h.video||'';if(target){source.src=resolveImage(target);source.type=target.endsWith('.webm')?'video/webm':'video/mp4';motion.hidden=false;motion.load();if(!window.matchMedia('(prefers-reduced-motion:reduce)').matches&&!navigator.connection?.saveData)motion.play().catch(()=>{});}else{motion.pause();motion.hidden=true}}}
    const grid=$('#servicesGrid');if(grid){grid.replaceChildren();const services=data.services||[];
      if(!services.length){grid.append(el('p','service-empty','Послуги ще не додано.'));return}
      services.forEach((item,i)=>{const tile=el('article','service-tile'),img=el('img');img.src=resolveImage(item.image);img.alt='';img.loading='lazy';const content=el('div','service-content');content.append(el('small','',`0${i+1} / PAVZA`),el('h3','',item.title),el('p','',item.description));tile.append(img,content);grid.append(tile)});
    }
  }catch(e){const grid=$('#servicesGrid');if(grid)grid.textContent='';}
}
