"use strict";
const button=document.getElementById('create-device-invite'),status=document.getElementById('device-invite-status'),link=document.getElementById('device-invite-link');
let expiry;
function clearLink(){link.hidden=true;link.removeAttribute('href');clearTimeout(expiry);}
button.addEventListener('click',async()=>{
 clearLink();button.disabled=true;status.textContent='Creating private link…';
 try{
  const response=await fetch('/api/device-invites',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name="csrf-token"]').content},body:'{}'});
  if(!response.ok)throw new Error('unavailable');
  const result=await response.json(),url=new URL(result.enrollment_url);
  if(url.origin!==location.origin||url.pathname!=='/survivor/enroll.html'||!url.hash)throw new Error('invalid');
  link.href=url.href;link.textContent=url.href;link.hidden=false;
  status.textContent='Share this link privately with the intended person. It expires in ten minutes.';
  expiry=setTimeout(()=>{clearLink();status.textContent='This link has expired. Create a new one.';},result.expires_in*1000);
 }catch(_){status.textContent='Could not create the link. Refresh and try again.';}finally{button.disabled=false;}
});
window.addEventListener('pagehide',clearLink);
