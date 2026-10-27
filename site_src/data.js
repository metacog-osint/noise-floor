/* Noisefloor data page: list the monthly GNSS releases from the day index (days.json), newest first. */
(function () {
  "use strict";
  var box = document.getElementById("data-months");
  if (!box || !window.fetch) return;
  fetch("/data/gnss/days.json").then(function (r) { return r.ok ? r.json() : null; }).then(function (days) {
    if (!days || !days.length) return;
    var months = {};
    days.forEach(function (d) { var m = d.day.slice(0, 7); months[m] = (months[m] || 0) + 1; });
    var keys = Object.keys(months).sort().reverse();
    box.textContent = "";
    box.appendChild(document.createTextNode("Releases by month (days on the map): "));
    keys.forEach(function (m, i) {
      var a = document.createElement("a");
      a.href = "https://github.com/metacog-osint/noise-floor/releases/tag/pnt-data-" + m;
      a.textContent = m;
      box.appendChild(a);
      box.appendChild(document.createTextNode(" (" + months[m] + ")" + (i < keys.length - 1 ? " · " : ". ")));
    });
    var all = document.createElement("a");
    all.href = "https://github.com/metacog-osint/noise-floor/releases";
    all.textContent = "All releases";
    box.appendChild(all);
    box.appendChild(document.createTextNode("."));
  }).catch(function () { /* the static link stays */ });
})();
