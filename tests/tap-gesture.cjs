'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const create=require('../static/survivor/tap-gesture.js');

function fixture() {
  let now=0, count=0;
  const detector=create({clock:()=>now,activate:()=>count++});
  const event=(extra={})=>({pointerId:1,clientX:100,clientY:100,button:0,isPrimary:true,...extra});
  return {detector,event,count:()=>count,set:value=>{now=value;},tap:(time,allowed=true)=>{
    now=time; detector.down(event(),allowed); now+=30; detector.up(event(),allowed);
  }};
}
test('four completed taps within rolling 1.5 seconds activate once',()=>{
  const f=fixture(); [0,200,400,600].forEach(t=>f.tap(t)); assert.equal(f.count(),1);
});
test('three taps do not activate',()=>{
  const f=fixture(); [0,200,400].forEach(t=>f.tap(t)); assert.equal(f.count(),0);
});
test('four taps outside the rolling window do not activate',()=>{
  const f=fixture(); [0,600,1200,1800].forEach(t=>f.tap(t)); assert.equal(f.count(),0);
});
test('old taps expire while a later complete rolling window still activates',()=>{
  const f=fixture(); [0,1600,1800,2000,2200].forEach(t=>f.tap(t)); assert.equal(f.count(),1);
});
test('follow-through taps cannot activate twice; quiet period permits a new burst',()=>{
  const f=fixture(); for(let i=0;i<12;i++) f.tap(i*100); assert.equal(f.count(),1);
  [3000,3200,3400,3600].forEach(t=>f.tap(t)); assert.equal(f.count(),2);
});
test('reset clears partial taps but does not defeat an activation latch',()=>{
  const f=fixture(); [0,100,200].forEach(t=>f.tap(t)); f.detector.reset(); f.tap(300); assert.equal(f.count(),0);
  [500,600,700].forEach(t=>f.tap(t)); assert.equal(f.count(),1);
  f.detector.reset(); [800,900,1000,1100].forEach(t=>f.tap(t)); assert.equal(f.count(),1);
});
test('excluded pointer-down or pointer-up resets partial sequences',()=>{
  for(const endOnly of [false,true]) {
    const f=fixture(); [0,100,200].forEach(t=>f.tap(t)); f.set(300);
    f.detector.down(f.event(),endOnly); f.set(330); f.detector.up(f.event(),false); f.tap(400);
    assert.equal(f.count(),0);
  }
});
test('dragging away and returning to start is not a tap',()=>{
  const f=fixture(); [0,100,200].forEach(t=>f.tap(t)); f.set(300); f.detector.down(f.event(),true);
  f.detector.move(f.event({clientX:111})); f.set(330); f.detector.up(f.event(),true); f.tap(400);
  assert.equal(f.count(),0);
});
test('small touch jitter is tolerated',()=>{
  const f=fixture(); for(let i=0;i<4;i++) {
    f.set(i*100); f.detector.down(f.event(),true); f.detector.move(f.event({clientX:105}));
    f.set(i*100+30); f.detector.up(f.event({clientX:105}),true);
  }
  assert.equal(f.count(),1);
});
test('long presses, cancellation, secondary buttons and multi-touch do not activate',()=>{
  for(const kind of ['long','cancel','secondary','multiple']) {
    const f=fixture(); [0,100,200].forEach(t=>f.tap(t)); f.set(300);
    f.detector.down(f.event(kind==='secondary'?{button:2}:{}),true);
    if(kind==='multiple') f.detector.down(f.event({pointerId:2,isPrimary:false}),true);
    f.set(kind==='long'?651:330);
    if(kind==='cancel') f.detector.cancel(f.event()); else f.detector.up(f.event(),true);
    if(kind==='multiple') f.detector.up(f.event({pointerId:2,isPrimary:false}),true);
    f.tap(700); assert.equal(f.count(),0,kind);
  }
});
