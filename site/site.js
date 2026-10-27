/* Every page: the About menu closes on an outside click or Escape, and the header clock shows UTC with the viewer's
   own zone beside it (the zone and 12/24-hour clock come from the Time button, tic-time.js). */
(function () {
  "use strict";
  var menu = document.querySelector("details.menu");
  if (menu) {
    document.addEventListener("click", function (ev) { if (menu.open && !menu.contains(ev.target)) menu.removeAttribute("open"); });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && menu.open) { menu.removeAttribute("open"); menu.querySelector("summary").focus(); }
    });
  }
  var clock = document.getElementById("clock");
  if (!clock) return;
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function tick() {
    var d = new Date(), t = pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes()) + " UTC";
    if (window.TicTime && window.TicTime.zone() !== "UTC") t += " · " + window.TicTime.format(d, { date: false });
    clock.textContent = t;
  }
  tick();
  setInterval(tick, 30000);
  if (window.TicTime) window.TicTime.onChange(tick);
})();
