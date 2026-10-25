"use strict";
// Remove the secret before any network call. Never persist it or put it in a URL query.
let token=location.hash.slice(1);
history.replaceState(null,'',location.pathname);
const button=document.getElementById('pair'),status=document.getElementById('status');
if(!token){button.disabled=true;status.textContent='This link is missing or expired. Ask for a new private link.';}
button.addEventListener('click',async()=>{
 button.disabled=true;status.textContent='Connecting…';
 try{
  const response=await fetch('/api/device/enroll',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});
  if(!response.ok){status.textContent=response.status===409?'This browser is already connected. Use its existing account.':'Could not connect. The link may have expired. Ask for a new private link.';return;}
  token='';status.textContent='Device connected. You can now open Clear Sky.';
 }catch(_){button.disabled=false;status.textContent='No connection. Reconnect and try again.';}
});
