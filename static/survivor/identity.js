/* Honest connection state; no account identifiers or private data in the notice. */
(function(){
 'use strict';
 var notice=null;
 async function check(){
  try{
   var headers={};
   if(/^(localhost|127\.0\.0\.1)$/.test(location.hostname))headers['X-Device-Token']=((typeof location !== 'undefined' && /^(localhost|127\.0\.0\.1)$/.test(location.hostname)) ? 'demo-device' : '');
   var response=await fetch('/api/device',{credentials:'same-origin',cache:'no-store',headers:headers});
   if(response.ok){if(notice){notice.remove();notice=null;}return;}
   if(response.status!==401)return;
   if(notice)return;
   notice=document.createElement('aside');notice.setAttribute('role','status');
   notice.style.cssText='padding:12px;background:var(--warm-bg,#f5f2eb);color:var(--text,#293632);border-bottom:1px solid #8a9690';
   var text=document.createElement('span');text.textContent='This device needs a private connection or recovery link. Saved items remain on this phone. ';
   var link=document.createElement('a');link.href='/survivor/device.html';link.textContent='Connection options';
   notice.append(text,link);document.body.prepend(notice);
  }catch(_){}
 }
 window.addEventListener('online',check);check();
})();
