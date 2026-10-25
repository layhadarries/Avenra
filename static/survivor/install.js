"use strict";
let installPrompt;
const button=document.getElementById('install');
window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();installPrompt=event;button.hidden=false;});
button.addEventListener('click',async()=>{if(!installPrompt)return;await installPrompt.prompt();await installPrompt.userChoice;installPrompt=null;button.hidden=true;});
window.addEventListener('appinstalled',()=>{button.hidden=true;document.getElementById('status').textContent='Clear Sky is installed.';});
if('serviceWorker' in navigator)navigator.serviceWorker.register('/survivor/service-worker.js',{scope:'/survivor/'}).catch(()=>{document.getElementById('status').textContent='Offline setup could not finish. Try again when connected.';});
