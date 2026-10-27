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
  // links to a page's "How to read this" section scroll there without touching the address: the Map and Sea pages keep
  // their day, view and filters in the hash, and a #howto there would wipe them
  var howto = document.getElementById("howto");
  if (howto) {
    var links = document.querySelectorAll('a[href="#howto"]');
    for (var k = 0; k < links.length; k++) {
      links[k].addEventListener("click", function (ev) {
        ev.preventDefault();
        howto.scrollIntoView({ behavior: "smooth", block: "start" });
        var h = howto.querySelector("h2");
        if (h) { h.setAttribute("tabindex", "-1"); h.focus({ preventScroll: true }); }
      });
    }
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  // a daily UTC time written as <span data-utc-daily="06:00">06:00 UTC</span> gets the viewer's own zone beside it
  var daily = document.querySelectorAll("[data-utc-daily]");
  function dailies() {
    for (var i = 0; i < daily.length; i++) {
      var hm = daily[i].getAttribute("data-utc-daily").split(":"), d = new Date();
      d.setUTCHours(+hm[0], +hm[1], 0, 0);
      daily[i].textContent = pad(+hm[0]) + ":" + pad(+hm[1]) + " UTC" +
        (window.TicTime && window.TicTime.zone() !== "UTC" ? " (" + window.TicTime.format(d, { date: false }) + ")" : "");
    }
  }
  dailies();
  if (window.TicTime) window.TicTime.onChange(dailies);
  var clock = document.getElementById("clock");
  if (!clock) return;
  function tick() {
    var d = new Date(), t = pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes()) + " UTC";
    if (window.TicTime && window.TicTime.zone() !== "UTC") t += " · " + window.TicTime.format(d, { date: false });
    clock.textContent = t;
  }
  tick();
  setInterval(tick, 30000);
  if (window.TicTime) window.TicTime.onChange(tick);
})();
