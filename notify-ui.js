/* Page Ferryman notification panel. Loaded only in the Talebook admin app. */
(() => {
  if (window.__pageFerrymanNotify) return;
  window.__pageFerrymanNotify = true;
  const api = '/api/page-ferryman/notify';
  const text = (s) => document.createTextNode(s);
  const panel = document.createElement('section');
  panel.id = 'page-ferryman-notify-panel';
  panel.style.cssText = 'margin:24px 0;padding:16px;border:1px solid #d8dee4;border-radius:6px;background:#fff';
  panel.innerHTML = '<h3>页渡者错误通知</h3><p>只发送无法自动处理的错误，不发送正常同步消息。</p>';
  const row = (label, el) => { const d=document.createElement('label'); d.style.cssText='display:block;margin:12px 0'; d.append(text(label+' '),el); return d; };
  const enabled=document.createElement('input'); enabled.type='checkbox';
  const type=document.createElement('select'); [['webhook','Webhook'],['telegram','Telegram Bot']].forEach(([v,t])=>{const o=document.createElement('option');o.value=v;o.text=t;type.add(o);});
  const url=document.createElement('input'); url.type='url'; url.style.width='min(520px,100%)';
  const token=document.createElement('input'); token.type='password'; token.style.width='min(520px,100%)';
  const chat=document.createElement('input'); chat.style.width='min(520px,100%)';
  const save=document.createElement('button'); save.textContent='保存';
  const test=document.createElement('button'); test.textContent='发送测试'; test.style.marginLeft='8px';
  const fields=document.createElement('div');
  fields.append(row('启用',enabled),row('通知方式',type),row('Webhook 地址',url),row('Bot Token',token),row('Chat ID',chat));
  const actions=document.createElement('div'); actions.append(save,test); panel.append(fields,actions);
  const sync=()=>{ const tg=type.value==='telegram'; fields.children[2].style.display=tg?'none':''; fields.children[3].style.display=tg?'':'none'; fields.children[4].style.display=tg?'':'none'; };
  type.onchange=sync; sync();
  fetch(api).then(r=>r.json()).then(r=>{const d=r.settings||{};enabled.checked=!!d.enabled;type.value=d.type||'webhook';url.value=d.url||'';token.value=d.bot_token||'';chat.value=d.chat_id||'';sync();}).catch(()=>{});
  save.onclick=()=>fetch(api,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:enabled.checked,type:type.value,url:url.value,bot_token:token.value,chat_id:chat.value})}).then(()=>alert('已保存'));
  test.onclick=()=>fetch(api,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:'页渡者测试消息'})}).then(r=>r.json()).then(r=>alert(r.err==='ok'?'发送成功':'发送失败'));
  const mount=()=>{if(location.pathname.includes('/admin')&&!document.getElementById(panel.id)){const root=document.querySelector('main')||document.body;root.append(panel);}};
  new MutationObserver(mount).observe(document.documentElement,{childList:true,subtree:true}); mount();
})();
