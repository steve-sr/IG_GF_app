const qs=(s,p=document)=>p.querySelector(s), qsa=(s,p=document)=>[...p.querySelectorAll(s)];
const esc=(v='')=>String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
window.addEventListener('load',()=>{setTimeout(()=>qs('#splash')?.classList.add('hide'),1050)});
function toast(msg,type='success'){const wrap=qs('.toast-wrap')||document.body.appendChild(Object.assign(document.createElement('div'),{className:'toast-wrap'}));const el=document.createElement('div');el.className='toast '+type;el.innerHTML=`<span>${esc(msg)}</span><button type="button" onclick="this.parentElement.remove()">×</button>`;wrap.appendChild(el);setTimeout(()=>el.remove(),5200)}
qsa('.toast').forEach(t=>setTimeout(()=>t.remove(),5500));
qsa('[data-format="phone-cr"]').forEach(input=>{
  const format=()=>{let d=input.value.replace(/\D+/g,''); if(d.startsWith('506')&&d.length>=11)d=d.slice(3); d=d.slice(0,8); input.value=d.length>4?`${d.slice(0,4)}-${d.slice(4)}`:d;};
  input.addEventListener('input',format);
  input.addEventListener('blur',format);
});

qsa('.smart-form').forEach(form=>{form.setAttribute('novalidate','');form.addEventListener('submit',e=>{let bad=[];
  const setBad=(input,msg)=>{bad.push(input);input.classList.add('invalid');input.parentElement.querySelector('.field-error')?.remove();const er=document.createElement('span');er.className='field-error';er.textContent=msg;input.parentElement.appendChild(er)};
  qsa('input,select,textarea',form).forEach(input=>{input.classList.remove('invalid');input.parentElement.querySelector('.field-error')?.remove();});
  qsa('[required]',form).forEach(input=>{if(!String(input.value||'').trim())setBad(input,`${input.dataset.label||'Este campo'} es obligatorio.`)});
  qsa('input[type="email"]',form).forEach(input=>{if(input.value.trim()&&!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(input.value.trim()))setBad(input,'Ingresá un correo válido. Ejemplo: nombre@correo.com')});
  qsa('[data-format="phone-cr"]',form).forEach(input=>{let d=input.value.replace(/\D+/g,''); if(d.startsWith('506')&&d.length>=11)d=d.slice(3); if(input.value.trim() && d.length!==8)setBad(input,'Ingresá un teléfono válido de 8 dígitos. Ejemplo: 8888-8888')});
  qsa('[data-format="username"]',form).forEach(input=>{const v=input.value.trim(); if(v&&!/^[a-zA-Z0-9._-]{3,40}$/.test(v))setBad(input,'Usá 3 a 40 caracteres: letras, números, punto, guion o guion bajo.')});
  if(bad.length){e.preventDefault();toast('Revisá los campos marcados antes de continuar.','danger');bad[0].focus({preventScroll:true});bad[0].scrollIntoView({behavior:'smooth',block:'center'})}
});});
function updateOtherBarrio(){const s=qs('#barrioSelect'), w=qs('#otherBarrioWrap'); if(!s||!w)return; w.classList.toggle('hidden',s.value!=='Otro')} qs('#barrioSelect')?.addEventListener('change',updateOtherBarrio); updateOtherBarrio();
function setLocationInputs(lat,lng){const maps=`https://www.google.com/maps/search/?api=1&query=${lat},${lng}`;const waze=`https://waze.com/ul?ll=${lat},${lng}&navigate=yes`; if(qs('#latInput'))qs('#latInput').value=lat; if(qs('#lngInput'))qs('#lngInput').value=lng; if(qs('#mapsInput'))qs('#mapsInput').value=maps; if(qs('#wazeInput'))qs('#wazeInput').value=waze;}
function getPosition(){return new Promise((resolve,reject)=>{if(!navigator.geolocation)return reject(new Error('Este navegador no soporta ubicación.')); navigator.geolocation.getCurrentPosition(p=>resolve(p.coords),err=>{let m='No se pudo obtener la ubicación.'; if(err.code===1)m='Permiso de ubicación denegado.'; if(err.code===2)m='La ubicación no está disponible.'; if(err.code===3)m='La solicitud de ubicación tardó demasiado.'; reject(new Error(m))},{enableHighAccuracy:true,timeout:12000,maximumAge:0})})}
async function useLocation(btn, save=false){const original=btn.innerHTML;try{btn.disabled=true;btn.innerHTML='<span class="icon location"></span>Obteniendo ubicación...';const c=await getPosition();const lat=c.latitude.toFixed(7), lng=c.longitude.toFixed(7);setLocationInputs(lat,lng); if(save){const id=btn.dataset.cellId;const r=await fetch(`/api/cells/${id}/location`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({latitude:c.latitude,longitude:c.longitude})});const data=await r.json();if(!data.ok)throw new Error(data.message);toast('Ubicación guardada correctamente.')}else{toast('Ubicación cargada en el formulario. Guardá los cambios.')}}catch(e){toast(e.message||'No se pudo obtener la ubicación.','danger')}finally{btn.disabled=false;btn.innerHTML=original}}
qs('#useLocation')?.addEventListener('click',e=>useLocation(e.currentTarget,false)); qs('#saveLeaderLocation')?.addEventListener('click',e=>useLocation(e.currentTarget,true));
qs('#nearBtn')?.addEventListener('click',async e=>{const btn=e.currentTarget,status=qs('#nearStatus'),res=qs('#nearResults'),normal=qs('#normalResults');const original=btn.innerHTML;try{btn.disabled=true;btn.innerHTML='<span class="icon location"></span>Detectando ubicación...';if(status)status.textContent='Solicitando permiso de ubicación...';const c=await getPosition();if(status)status.textContent='Buscando células cercanas...';const r=await fetch(`/api/nearby?lat=${c.latitude}&lng=${c.longitude}`);const data=await r.json();if(!data.ok)throw new Error(data.message);if(normal)normal.style.display='none';if(res){res.innerHTML=data.cells.length?data.cells.map(x=>`<article class="card cell-card"><div class="card-top"><div class="cell-main"><h3>${esc(x.name)}</h3><p class="cell-barrio">${esc(x.barrio)}</p></div><span class="pill status-pill"><span class="status-dot"></span>${esc(x.day)} · ${esc(x.time)}</span></div><p class="distance-line"><span class="icon location"></span>${esc(x.distance_label)} de tu ubicación</p><p class="cell-description">${esc(x.description||'Célula disponible para integrarte.')}</p><div class="meta cell-meta"><span><i class="icon user"></i>${esc(x.leader)}</span><span><i class="icon location"></i>${esc(x.address)}</span></div><div class="card-actions">${x.maps?`<a class="btn small ghost" target="_blank" rel="noopener" href="${esc(x.maps)}"><span class="icon map"></span>Maps</a>`:''}${x.waze?`<a class="btn small ghost" target="_blank" rel="noopener" href="${esc(x.waze)}"><span class="icon location"></span>Waze</a>`:''}${x.whatsapp_url?`<a class="btn small primary contact-btn" target="_blank" rel="noopener" href="${esc(x.whatsapp_url)}"><span class="icon chat"></span>Contactar</a>`:''}</div></article>`).join(''):'<div class="empty">Aún no hay células con ubicación exacta.</div>';}if(status)status.innerHTML=`<span class="distance-badge"><span class="icon location"></span>Resultados ordenados por cercanía</span>`}catch(err){toast(err.message||'No se pudo buscar cerca de vos.','danger');if(status)status.textContent='Podés buscar por barrio manualmente.'}finally{btn.disabled=false;btn.innerHTML=original}});

function openConfirmModal(title,message,onConfirm,opts={}){
  let overlay=document.createElement('div'); overlay.className='modal-overlay';
  const type=opts.type||'danger';
  const okText=opts.okText||(type==='danger'?'Eliminar':'Generar');
  const okClass=type==='danger'?'btn danger':'btn primary';
  const icon=type==='danger'?'trash':(opts.icon||'key');
  overlay.innerHTML=`<div class="confirm-modal ${type==='danger'?'':'action-modal'}"><div class="modal-icon ${type==='danger'?'danger-icon':'action-icon'}"><span class="icon ${icon}"></span></div><h2>${esc(title||'Confirmar acción')}</h2><p>${esc(message||'Confirmá para continuar.')}</p><div class="modal-actions"><button type="button" class="btn ghost" data-cancel>Cancelar</button><button type="button" class="${okClass}" data-ok>${esc(okText)}</button></div></div>`;
  document.body.appendChild(overlay);
  requestAnimationFrame(()=>overlay.classList.add('show'));
  overlay.querySelector('[data-cancel]').addEventListener('click',()=>overlay.remove());
  overlay.addEventListener('click',e=>{if(e.target===overlay)overlay.remove()});
  overlay.querySelector('[data-ok]').addEventListener('click',()=>{overlay.remove(); onConfirm&&onConfirm();});
}
qsa('form[data-confirm]').forEach(form=>{form.addEventListener('submit',e=>{if(form.dataset.confirmed==='1')return; e.preventDefault(); openConfirmModal(form.dataset.confirm,form.dataset.confirmMessage,()=>{form.dataset.confirmed='1'; form.submit();},{type:form.dataset.confirmType||'danger',okText:form.dataset.confirmOk,icon:form.dataset.confirmIcon});});});


// Extract coordinates from a pasted Google Maps link, including shared links from WhatsApp.
qs('#resolveMapsBtn')?.addEventListener('click', async (e)=>{
  const btn=e.currentTarget;
  const input=qs('#mapsInput');
  const raw=(input?.value||'').trim();
  const original=btn.innerHTML;
  if(!raw){toast('Pegá primero el link de Google Maps.','danger'); input?.focus(); return;}
  try{
    btn.disabled=true;
    btn.innerHTML='<span class="icon location"></span>Localizando...';
    const r=await fetch('/api/resolve-maps-url',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:raw})});
    const data=await r.json();
    if(!data.ok) throw new Error(data.message||'No se pudo extraer la ubicación.');
    setLocationInputs(String(data.latitude), String(data.longitude));
    if(qs('#mapsInput')) qs('#mapsInput').value = data.maps || raw;
    if(qs('#wazeInput')) qs('#wazeInput').value = data.waze || '';
    toast(data.message || 'Ubicación extraída del link. Guardá los cambios.','success');
  }catch(err){
    toast(err.message || 'No se pudo extraer la ubicación del link.','danger');
  }finally{
    btn.disabled=false;
    btn.innerHTML=original;
  }
});

// Map picker: manually point the cell location on a map.
(function(){
  const openBtn = qs('#openMapPicker');
  const modal = qs('#mapPickerModal');
  const closeBtn = qs('#closeMapPicker');
  const confirmBtn = qs('#confirmMapPicker');
  const pickedText = qs('#mapPickedText');
  const mapEl = qs('#mapPicker');
  if(!openBtn || !modal || !mapEl) return;

  let map = null;
  let marker = null;
  let picked = null;
  const LIBERIA_CENTER = [10.6350, -85.4377];

  function readCurrentCenter(){
    const lat = parseFloat(qs('#latInput')?.value);
    const lng = parseFloat(qs('#lngInput')?.value);
    if(Number.isFinite(lat) && Number.isFinite(lng)) return [lat, lng];
    return LIBERIA_CENTER;
  }

  function setPicked(latlng){
    picked = {lat: Number(latlng.lat), lng: Number(latlng.lng)};
    if(marker) marker.setLatLng(picked); else marker = L.marker(picked).addTo(map);
    if(confirmBtn) confirmBtn.disabled = false;
    if(pickedText) pickedText.textContent = `Punto seleccionado: ${picked.lat.toFixed(7)}, ${picked.lng.toFixed(7)}`;
  }

  function initMap(){
    if(!window.L){
      toast('El mapa aún está cargando. Intentá de nuevo en unos segundos.','warning');
      return false;
    }
    const center = readCurrentCenter();
    if(!map){
      map = L.map(mapEl, {scrollWheelZoom:true}).setView(center, 14);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap'
      }).addTo(map);
      map.on('click', e => setPicked(e.latlng));
    }else{
      map.setView(center, 14);
    }
    if(center !== LIBERIA_CENTER){
      setPicked({lat:center[0], lng:center[1]});
    }else{
      picked = null;
      if(marker){map.removeLayer(marker); marker=null;}
      if(confirmBtn) confirmBtn.disabled = true;
      if(pickedText) pickedText.textContent = 'Tocá el mapa para seleccionar el punto exacto.';
    }
    setTimeout(()=>map.invalidateSize(),120);
    return true;
  }

  function openMap(){
    modal.classList.add('show');
    modal.setAttribute('aria-hidden','false');
    initMap();
  }
  function closeMap(){
    modal.classList.remove('show');
    modal.setAttribute('aria-hidden','true');
  }

  openBtn.addEventListener('click', openMap);
  closeBtn?.addEventListener('click', closeMap);
  modal.addEventListener('click', e=>{ if(e.target===modal) closeMap(); });
  document.addEventListener('keydown', e=>{ if(e.key==='Escape' && modal.classList.contains('show')) closeMap(); });
  confirmBtn?.addEventListener('click', ()=>{
    if(!picked) return;
    setLocationInputs(picked.lat.toFixed(7), picked.lng.toFixed(7));
    toast('Punto del mapa cargado. Guardá los cambios para aplicarlo.','success');
    closeMap();
  });
})();

// Password visibility toggle.
qsa('[data-password-toggle]').forEach(btn=>{
  btn.addEventListener('click',()=>{
    const wrap=btn.closest('.password-wrap');
    const input=wrap?.querySelector('input');
    if(!input)return;
    const visible=input.type==='text';
    input.type=visible?'password':'text';
    btn.classList.toggle('is-visible',!visible);
    btn.setAttribute('aria-label',visible?'Mostrar contraseña':'Ocultar contraseña');
    input.focus({preventScroll:true});
  });
});

document.addEventListener('click', async (e)=>{
  const btn=e.target.closest('[data-copy-text]');
  if(!btn) return;
  try{
    await navigator.clipboard.writeText(btn.dataset.copyText || '');
    if(typeof toast==='function') toast('Mensaje copiado.', 'success');
  }catch(err){
    if(typeof toast==='function') toast('No se pudo copiar el mensaje.', 'danger');
  }
});


// Client-side inactivity guard. Server also validates every protected request.
(function(){
  const meta = document.body?.dataset || {};
  const isLogged = document.querySelector('.nav-actions a[href$="/logout"]');
  if(!isLogged) return;
  const timeoutMs = 10 * 60 * 1000;
  let timer;
  const reset=()=>{ clearTimeout(timer); timer=setTimeout(()=>{ window.location.href='/logout?reason=inactive'; }, timeoutMs); };
  ['click','mousemove','keydown','touchstart','scroll'].forEach(evt=>document.addEventListener(evt, reset, {passive:true}));
  reset();
})();

// Responsive navbar
(function(){
  const btn = qs('.nav-toggle');
  const menu = qs('#mainNavMenu');
  if(!btn || !menu) return;
  btn.addEventListener('click',()=>{
    const open = menu.classList.toggle('open');
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  document.addEventListener('click',e=>{
    if(!menu.classList.contains('open')) return;
    if(e.target.closest('.nav')) return;
    menu.classList.remove('open');
    btn.setAttribute('aria-expanded','false');
  });
})();

// Bulk checkbox helpers for mentor assignment.
document.addEventListener('click', (e)=>{
  const btn = e.target.closest('[data-check-all]');
  if(!btn) return;
  const name = btn.getAttribute('data-check-all');
  const boxes = Array.from(document.querySelectorAll(`input[type="checkbox"][name="${name}"]`));
  if(!boxes.length) return;
  const shouldCheck = boxes.some(b=>!b.checked);
  boxes.forEach(b=>{ b.checked = shouldCheck; });
  btn.textContent = shouldCheck ? 'Quitar selección' : 'Seleccionar visibles';
});


// Visual selection feedback for mentor assignment cards.
document.addEventListener('change', (e)=>{
  const box = e.target.closest('.leader-select-card input[type="checkbox"]');
  if(!box) return;
  box.closest('.leader-select-card')?.classList.toggle('is-selected', box.checked);
});
document.querySelectorAll('.leader-select-card input[type="checkbox"]').forEach(box=>{
  box.closest('.leader-select-card')?.classList.toggle('is-selected', box.checked);
});

// Smoothly reveal page sections.
const revealObserver = 'IntersectionObserver' in window ? new IntersectionObserver((entries)=>{
  entries.forEach(entry=>{ if(entry.isIntersecting){ entry.target.classList.add('is-visible'); revealObserver.unobserve(entry.target); } });
},{threshold:.08}) : null;
document.querySelectorAll('.panel,.sector-group,.mentor-mini-card,.cell-card,.table-card').forEach(el=>{
  el.classList.add('ui-reveal');
  if(revealObserver) revealObserver.observe(el); else el.classList.add('is-visible');
});

// Leader dashboard: multiple cells, scoped location/map/link actions.
(function(){
  const setScopedLocationInputs=(card,lat,lng)=>{
    const maps=`https://www.google.com/maps/search/?api=1&query=${lat},${lng}`;
    const waze=`https://waze.com/ul?ll=${lat},${lng}&navigate=yes`;
    card?.querySelector('.latInput')&&(card.querySelector('.latInput').value=lat);
    card?.querySelector('.lngInput')&&(card.querySelector('.lngInput').value=lng);
    card?.querySelector('.mapsInput')&&(card.querySelector('.mapsInput').value=maps);
    card?.querySelector('.wazeInput')&&(card.querySelector('.wazeInput').value=waze);
  };

  document.addEventListener('click', async (e)=>{
    const btn=e.target.closest('.leader-use-location');
    if(!btn) return;
    const card=btn.closest('[data-cell-card]');
    const original=btn.innerHTML;
    try{
      btn.disabled=true;
      btn.innerHTML='<span class="icon location"></span>Obteniendo ubicación...';
      const c=await getPosition();
      const lat=c.latitude.toFixed(7), lng=c.longitude.toFixed(7);
      setScopedLocationInputs(card,lat,lng);
      const id=btn.dataset.cellId;
      const r=await fetch(`/api/cells/${id}/location`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({latitude:c.latitude,longitude:c.longitude})});
      const data=await r.json();
      if(!data.ok)throw new Error(data.message||'No se pudo guardar la ubicación.');
      toast('Ubicación guardada correctamente.','success');
    }catch(err){
      toast(err.message||'No se pudo obtener la ubicación.','danger');
    }finally{
      btn.disabled=false;
      btn.innerHTML=original;
    }
  });

  document.addEventListener('click', async (e)=>{
    const btn=e.target.closest('.leader-resolve-maps');
    if(!btn) return;
    const card=btn.closest('[data-cell-card]');
    const input=card?.querySelector('.mapsInput');
    const raw=(input?.value||'').trim();
    const original=btn.innerHTML;
    if(!raw){toast('Pegá primero el link de Google Maps.','danger'); input?.focus(); return;}
    try{
      btn.disabled=true;
      btn.innerHTML='<span class="icon location"></span>Localizando...';
      const r=await fetch('/api/resolve-maps-url',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:raw})});
      const data=await r.json();
      if(!data.ok) throw new Error(data.message||'No se pudo extraer la ubicación.');
      setScopedLocationInputs(card,String(data.latitude),String(data.longitude));
      toast(data.message || 'Ubicación extraída del link. Guardá los cambios.','success');
    }catch(err){
      toast(err.message || 'No se pudo extraer la ubicación del link.','danger');
    }finally{
      btn.disabled=false;
      btn.innerHTML=original;
    }
  });

  const modal=document.querySelector('#mapPickerModal');
  const mapEl=document.querySelector('#mapPicker');
  const closeBtn=document.querySelector('#closeMapPicker');
  const confirmBtn=document.querySelector('#confirmMapPicker');
  const pickedText=document.querySelector('#mapPickedText');
  if(!modal || !mapEl) return;
  let activeCard=null, map=null, marker=null, picked=null;
  const LIBERIA_CENTER=[10.6350,-85.4377];
  const readCenter=()=>{
    const lat=parseFloat(activeCard?.querySelector('.latInput')?.value);
    const lng=parseFloat(activeCard?.querySelector('.lngInput')?.value);
    if(Number.isFinite(lat)&&Number.isFinite(lng)) return [lat,lng];
    return LIBERIA_CENTER;
  };
  const setPicked=(latlng)=>{
    picked={lat:Number(latlng.lat),lng:Number(latlng.lng)};
    if(marker) marker.setLatLng(picked); else marker=L.marker(picked).addTo(map);
    if(confirmBtn) confirmBtn.disabled=false;
    if(pickedText) pickedText.textContent=`Punto seleccionado: ${picked.lat.toFixed(7)}, ${picked.lng.toFixed(7)}`;
  };
  const initMap=()=>{
    if(!window.L){toast('El mapa aún está cargando. Intentá de nuevo en unos segundos.','warning');return false;}
    const center=readCenter();
    if(!map){
      map=L.map(mapEl,{scrollWheelZoom:true}).setView(center,14);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap'}).addTo(map);
      map.on('click',e=>setPicked(e.latlng));
    }else map.setView(center,14);
    if(Number.isFinite(parseFloat(activeCard?.querySelector('.latInput')?.value))){setPicked({lat:center[0],lng:center[1]});}
    else{picked=null;if(marker){map.removeLayer(marker);marker=null;} if(confirmBtn)confirmBtn.disabled=true; if(pickedText)pickedText.textContent='Tocá el mapa para seleccionar el punto exacto.';}
    setTimeout(()=>map.invalidateSize(),120);
    return true;
  };
  document.addEventListener('click',(e)=>{
    const btn=e.target.closest('.leader-open-map');
    if(!btn)return;
    activeCard=btn.closest('[data-cell-card]');
    modal.classList.add('show');
    modal.setAttribute('aria-hidden','false');
    initMap();
  });
  const close=()=>{modal.classList.remove('show');modal.setAttribute('aria-hidden','true');};
  closeBtn?.addEventListener('click',close);
  modal.addEventListener('click',e=>{if(e.target===modal)close();});
  confirmBtn?.addEventListener('click',()=>{
    if(!picked || !activeCard)return;
    setScopedLocationInputs(activeCard,picked.lat.toFixed(7),picked.lng.toFixed(7));
    toast('Punto del mapa cargado. Guardá los cambios para aplicarlo.','success');
    close();
  });
})();

// Leader dashboard: inline cell name editing from pencil icon.
document.addEventListener('click', (e)=>{
  const btn = e.target.closest('.leader-edit-name');
  if(!btn) return;
  const card = btn.closest('[data-cell-card]');
  const box = card?.querySelector('.inline-name-edit');
  const input = card?.querySelector('.cell-name-input');
  if(!box || !input) return;
  box.classList.toggle('is-hidden');
  if(!box.classList.contains('is-hidden')){
    setTimeout(()=>{ input.focus(); input.select(); }, 80);
  }
});

document.addEventListener('input', (e)=>{
  const input = e.target.closest('.cell-name-input');
  if(!input) return;
  const card = input.closest('[data-cell-card]');
  const title = card?.querySelector('[data-cell-title]');
  if(title) title.textContent = input.value.trim() || 'Nombre de célula';
});

// CR phone formatting for leader/account phone fields
document.querySelectorAll('[data-phone-format]').forEach((input)=>{
  input.addEventListener('input',()=>{
    let d=(input.value||'').replace(/\D/g,'');
    if(d.startsWith('506')) d=d.slice(3);
    d=d.slice(0,8);
    input.value=d.length>4?`${d.slice(0,4)}-${d.slice(4)}`:d;
  });
});
