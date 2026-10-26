/* Noise Floor home: "on the map today" from the latest daily day (days.json, its events file, places.json).
   Each listed event links to the map at that day and place. */
(function () {
  "use strict";
  var sec = document.getElementById("today");
  if (!sec || !window.fetch) return;
  function get(u) { return fetch(u).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }); }
  function km(a, b) {
    var p1 = a[0] * Math.PI / 180, p2 = b[0] * Math.PI / 180, dl = (b[1] - a[1]) * Math.PI / 180;
    var h = Math.pow(Math.sin((p2 - p1) / 2), 2) + Math.cos(p1) * Math.cos(p2) * Math.pow(Math.sin(dl / 2), 2);
    return 12742 * Math.asin(Math.min(1, Math.sqrt(h)));
  }
  function ll2(lat, lon) {
    return Math.abs(lat).toFixed(1) + "°" + (lat >= 0 ? "N" : "S") + " " + Math.abs(lon).toFixed(1) + "°" + (lon >= 0 ? "E" : "W");
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  var TIER = { major: "Major", notable: "Notable", minor: "Minor" };

  get("/data/gnss/days.json").then(function (days) {
    if (!days || !days.length) return;
    var daily = days.filter(function (d) { return d.daily; });
    var today = (daily.length ? daily : days)[(daily.length ? daily : days).length - 1];
    var prior = days.filter(function (d) { return d.day < today.day; }).slice(-30).map(function (d) { return d.jam_hexes; }).sort(function (a, b) { return a - b; });
    var med = prior.length ? prior[Math.floor(prior.length / 2)] : null;
    document.getElementById("today-day").textContent = today.day;
    document.getElementById("today-link").href = "/map#day=" + today.day + "&m=jam";
    var sum = today.jam_hexes.toLocaleString() + " hexes at jamming scale" +
      (med !== null ? " (30-day median " + med.toLocaleString() + ")" : "") + ", out of " + today.hexes.toLocaleString() + " with 5 or more aircraft.";
    document.getElementById("today-sum").textContent = sum;
    sec.hidden = false;
    return Promise.all([get("/data/events/" + today.day + ".json"), get("/data/places.json")]).then(function (res) {
      var ev = res[0], pl = (res[1] && res[1].places || []).filter(function (p) { return p[3] <= 5; });
      var list = document.getElementById("today-list");
      if (!ev) { list.innerHTML = ""; return; }
      var top = ev.anomalies.filter(function (e) { return e.m === "jam" && e.tier !== "minor"; }).slice(0, 4);
      var extra = [];
      if (!top.length) extra.push("No major or notable jamming-scale anomaly events.");
      if (ev.bursts && ev.bursts.length) extra.push(ev.bursts.length + " minute-level bursts.");
      if (ev.tests && ev.tests.length) extra.push(ev.tests.length + " announced US GPS tests.");
      top.forEach(function (e) {
        var near = null, best = 350;
        pl.forEach(function (p) { var d = km([e.lat, e.lon], [p[1], p[2]]); if (d < best) { best = d; near = p[0]; } });
        var li = document.createElement("li"), a = document.createElement("a");
        a.href = "/map#day=" + ev.day + "&m=jam&v=" + e.lat.toFixed(2) + "," + e.lon.toFixed(2) + ",6";
        a.textContent = TIER[e.tier] + ": " + e.peak.toFixed(0) + "% of aircraft degraded around " + ll2(e.lat, e.lon) + (near ? " (near " + near + ")" : "");
        li.appendChild(a);
        li.appendChild(document.createTextNode(", " + pad(e.h0) + ":00–" + pad(e.h1) + ":59Z, " + e.excess.toFixed(0) + " points above usual" +
          (e.hs != null ? "; A350/A380 share " + Math.round(e.hs * 100) + "%" : "") + (e.test ? "; fits announced test " + e.test : "") + "."));
        list.appendChild(li);
      });
      if (extra.length) { var li = document.createElement("li"); li.className = "mut"; li.textContent = extra.join(" "); list.appendChild(li); }
    });
  });
})();
