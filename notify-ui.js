/* Page Ferryman notification panel. Loaded by the Talebook admin app. */
(() => {
  if (window.__pageFerrymanNotify) return;
  window.__pageFerrymanNotify = true;
  const api = '/api/page-ferryman/notify';
  const css = `
#page-ferryman-notify-panel{box-sizing:border-box;width:calc(100% - 48px);max-width:860px;margin:24px auto;padding:24px;background:#fff;border:1px solid #d9dee7;border-radius:8px;box-shadow:0 2px 8px rgba(20,35,55,.06);color:#253044;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
#page-ferryman-notify-panel.pf-sidebar-safe{margin-left:24px;margin-right:24px}
#page-ferryman-notify-panel *{box-sizing:border-box}
#page-ferryman-notify-panel h3{margin:0 0 6px;font-size:18px;font-weight:600;color:#172033}
#page-ferryman-notify-panel .pf-help{margin:0 0 20px;color:#687386}
#page-ferryman-notify-panel .pf-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px 20px}
#page-ferryman-notify-panel .pf-field{display:flex;flex-direction:column;gap:6px;min-width:0}
#page-ferryman-notify-panel .pf-field.full{grid-column:1/-1}
#page-ferryman-notify-panel .pf-label{font-weight:500;color:#344054}
#page-ferryman-notify-panel input,#page-ferryman-notify-panel select{width:100%;height:36px;padding:7px 10px;border:1px solid #c7ced9;border-radius:5px;background:#fff;color:#1f2937;font:inherit;outline:none}
#page-ferryman-notify-panel input:focus,#page-ferryman-notify-panel select:focus{border-color:#6b8fd6;box-shadow:0 0 0 2px rgba(73,117,201,.14)}
#page-ferryman-notify-panel .pf-switch{display:flex;align-items:center;gap:8px;height:36px}
#page-ferryman-notify-panel .pf-switch input{width:16px;height:16px;padding:0}
#page-ferryman-notify-panel .pf-actions{display:flex;gap:10px;margin-top:22px}
#page-ferryman-notify-panel button{height:34px;padding:0 15px;border:1px solid #c4ccd8;border-radius:5px;background:#fff;color:#344054;font:inherit;cursor:pointer}
#page-ferryman-notify-panel button.primary{border-color:#3d6fc4;background:#3d6fc4;color:#fff}
#page-ferryman-notify-panel button:hover{filter:brightness(.97)}
@media(max-width:680px){#page-ferryman-notify-panel{margin:16px 0;padding:18px}.pf-grid{grid-template-columns:1fr!important}.pf-field.full{grid-column:auto!important}}
`;
  const style = document.createElement('style'); style.textContent = css; document.head.append(style);
  const panel = document.createElement('section'); panel.id = 'page-ferryman-notify-panel';
  panel.innerHTML = '<h3>页渡者错误通知</h3><p class="pf-help">只发送无法自动处理的错误，不发送正常同步消息。</p>';
  const grid = document.createElement('div'); grid.className='pf-grid';
  const field = (label, control, full=false) => { const d=document.createElement('div'); d.className='pf-field'+(full?' full':''); const l=document.createElement('div'); l.className='pf-label'; l.textContent=label; d.append(l,control); return d; };
  const enabled=document.createElement('div'); enabled.className='pf-switch'; const enabledBox=document.createElement('input'); enabledBox.type='checkbox'; enabled.append(enabledBox, document.createTextNode('启用通知'));
  const type=document.createElement('select'); [['webhook','Webhook'],['telegram','Telegram Bot']].forEach(([v,t])=>{const o=document.createElement('option');o.value=v;o.textContent=t;type.append(o);});
  const url=document.createElement('input'); url.type='url'; url.placeholder='https://example.com/webhook';
  const token=document.createElement('input'); token.type='password'; token.placeholder='留空则保留原 Token';
  const chat=document.createElement('input'); chat.placeholder='Telegram Chat ID';
  grid.append(field('通知开关',enabled),field('通知方式',type),field('Webhook 地址',url,true),field('Bot Token',token),field('Chat ID',chat));
  const actions=document.createElement('div'); actions.className='pf-actions'; const save=document.createElement('button'); save.className='primary'; save.textContent='保存设置'; const test=document.createElement('button'); test.textContent='发送测试消息'; actions.append(save,test); panel.append(grid,actions);
  const sync=()=>{const tg=type.value==='telegram';grid.children[2].style.display=tg?'none':'';grid.children[3].style.display=tg?'':'none';grid.children[4].style.display=tg?'':'none';};
  type.onchange=sync; sync();
  fetch(api).then(r=>r.json()).then(r=>{const d=r.settings||{};enabledBox.checked=!!d.enabled;type.value=d.type||'webhook';url.value=d.url||'';token.value=d.bot_token||'';chat.value=d.chat_id||'';sync();}).catch(()=>{});
  save.onclick=()=>fetch(api,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:enabledBox.checked,type:type.value,url:url.value,bot_token:token.value,chat_id:chat.value})}).then(()=>alert('页渡者通知设置已保存'));
  test.onclick=()=>fetch(api,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:'页渡者测试消息'})}).then(r=>r.json()).then(r=>alert(r.err==='ok'?'测试消息已发送':'测试消息发送失败'));
  const mount=()=>{if(location.pathname.includes('/admin')&&!document.getElementById(panel.id)){const root=document.querySelector('main')||document.body;root.append(panel);}};
  new MutationObserver(mount).observe(document.documentElement,{childList:true,subtree:true}); mount();
})();
