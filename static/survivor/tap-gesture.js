/* Pure, bounded tap recognizer. No DOM, storage, location or network authority. */
(function (root) {
  'use strict';
  function create(options) {
    var clock = options.clock, activate = options.activate;
    var taps = [], pointer = null, pointers = new Set(), multiple = false;
    var latched = false, lastTap = -Infinity;
    function reset() { taps = []; pointer = null; pointers.clear(); multiple = false; }
    function invalidate() { taps = []; pointer = null; }
    function moved(event) { return Math.hypot(event.clientX - pointer.x, event.clientY - pointer.y) > 10; }
    return {
      reset:reset,
      down:function (event, allowed) {
        pointers.add(event.pointerId);
        if (pointers.size > 1) { multiple = true; invalidate(); return; }
        if (multiple || !allowed || event.isPrimary === false || event.button !== 0) { invalidate(); return; }
        pointer = {id:event.pointerId,x:event.clientX,y:event.clientY,time:clock()};
      },
      move:function (event) {
        if (pointer && pointer.id === event.pointerId && moved(event)) invalidate();
      },
      cancel:function (event) {
        pointers.delete(event.pointerId); invalidate();
        if (!pointers.size) multiple = false;
      },
      up:function (event, allowed) {
        pointers.delete(event.pointerId);
        if (multiple) { invalidate(); if (!pointers.size) multiple = false; return; }
        var now = clock();
        if (!pointer || pointer.id !== event.pointerId || !allowed || moved(event) || now - pointer.time > 350) { invalidate(); return; }
        pointer = null;
        if (latched && now - lastTap <= 1500) { lastTap = now; taps = []; return; }
        latched = false;
        taps = taps.filter(function (time) { return now - time <= 1500; });
        taps.push(now); lastTap = now;
        if (taps.length === 4) { taps = []; latched = true; activate(); }
      }
    };
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = create;
  else root.CWTapDetector = create;
})(typeof window === 'undefined' ? globalThis : window);
