'use strict';
const status=document.getElementById('device-status');
const button=document.getElementById('disconnect');
const confirmation=document.getElementById('confirm-disconnect');
confirmation.addEventListener('change',()=>{button.disabled=!confirmation.checked;});
fetch('/api/device',{credentials:'same-origin',cache:'no-store'}).then(r=>{
 status.textContent=r.ok?'This browser is connected.':'This browser needs a private connection or recovery link.';
}).catch(()=>{status.textContent='Connection could not be checked. Your saved entries remain on this phone.';});
button.addEventListener('click',async()=>{
 if(!confirmation.checked)return;
 button.disabled=true;
 try{
  const response=await fetch('/api/device/disconnect',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:'{}'});
  if(!response.ok)throw new Error('unavailable');
  // Only forget account metadata. Never erase pending IndexedDB entries.
  localStorage.removeItem('clear-sky-alert-owner-v1');
  status.textContent='Disconnected. Your saved entries remain on this phone. Use a private link to reconnect.';
 }catch(_){status.textContent='Could not confirm disconnection. Reconnect and try again.';button.disabled=false;}
});
