/* Noise Floor GEO board: /data/geo.json (built at deploy by tools/geo.py from the daily CelesTrak snapshots). */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  if (!$("geo-table")) return;
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function lon(x) { return Math.abs(x).toFixed(2) + "°" + (x < 0 ? "W" : "E"); }
  var ROLE = { inspection: "inspection-capable", servicing: "servicing" };
  function role(r) { return r ? ' <span class="geo-role geo-role-' + esc(r) + '">' + esc(ROLE[r] || r) + "</span>" : ""; }
  function table(head, rows, cls) {
    return '<div class="tw"><table class="' + (cls || "") + '"><thead><tr>' + head.map(function (h) { return "<th>" + esc(h) + "</th>"; }).join("") +
      "</tr></thead><tbody>" + rows.join("") + "</tbody></table></div>";
  }
  function strip(objs) {                 // the belt from 180W to 180E, one tick per object, coloured by class
    var W = 1000, H = 84, x = function (l) { return ((l + 180) / 360 * W).toFixed(1); };
    var cls = { "station-kept": "geo-kept", inclined: "geo-inc", drifting: "geo-drift" };
    var ticks = objs.map(function (o) {
      var y = o["class"] === "drifting" ? 12 : o["class"] === "inclined" ? 30 : 48;
      return '<line class="' + (cls[o["class"]] || "geo-kept") + '" x1="' + x(o.lon) + '" x2="' + x(o.lon) + '" y1="' + y + '" y2="' + (y + 12) + '"><title>' +
        esc(o.name + " (" + (o.owner || "?") + ") " + lon(o.lon)) + "</title></line>";
    }).join("");
    var axis = [-180, -120, -60, 0, 60, 120, 180].map(function (l) {
      return '<text x="' + x(l) + '" y="80" text-anchor="middle">' + (l === 0 ? "0°" : Math.abs(l) + "°" + (l < 0 ? "W" : "E")) + "</text>";
    }).join("");
    return '<svg class="geo-strip" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Longitude of every active GEO object, by class">' + ticks + axis +
      '</svg><p class="small"><span class="geo-key geo-drift"></span> drifting · <span class="geo-key geo-inc"></span> inclined · <span class="geo-key geo-kept"></span> station-kept. Hover a tick for its name.</p>';
  }
  fetch("/data/geo.json", { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (g) {
    if (!g) { $("geo-status").textContent = "The GEO data could not be loaded."; return; }
    var c = g.counts;
    $("geo-status").innerHTML = "<strong>" + c.objects + "</strong> active objects at " + esc(g.at_utc.replace("T", " ").replace("Z", "")) + " UTC: " + c["station-kept"] + " station-kept, " +
      c.inclined + " inclined, " + c.drifting + " drifting. Elements from the snapshot of " + esc(g.snapshot_day) + " (" + g.snapshots + " snapshot" + (g.snapshots === 1 ? "" : "s") + " so far).";
    $("geo-close").innerHTML = g.close_other_owner.length ? table(["Separation", "Object", "Owner", "Near", "Owner", "Longitude", "What the roles say"], g.close_other_owner.map(function (p) {
      return '<tr><td class="num">' + p.km + " km</td><td>" + esc(p.a[1]) + role(p.a[3]) + "</td><td>" + esc(p.a[2]) + "</td><td>" + esc(p.b[1]) + role(p.b[3]) + "</td><td>" + esc(p.b[2]) +
        '</td><td class="num">' + lon(p.lon) + "</td><td>" + esc(p.kind || "") + (p.age_days > 3 ? " (elements " + Math.round(p.age_days) + " days old)" : "") + "</td></tr>";
    })) + '<p class="small">' + g.close_same_owner_count + " more pairs within 100 km share an owner code (often a country, and often co-located on purpose) and aren't listed; a pair with a listed role is always listed.</p>" : "<p>None within 100 km.</p>";
    $("geo-man").innerHTML = g.manoeuvres.length ? table(["Day", "Object", "Owner", "Longitude", "What changed"], g.manoeuvres.slice().reverse().map(function (m) {
      return "<tr><td>" + esc(m.day) + "</td><td>" + esc(m.name) + "</td><td>" + esc(m.owner) + '</td><td class="num">' + lon(m.lon) + "</td><td>" + esc(m.what) + "</td></tr>";
    })) : '<p class="small">None yet: manoeuvres need two snapshots, and snapshots began on 26 Oct 2026.</p>';
    $("geo-drift").innerHTML = table(["Object", "Owner", "Longitude", "Drift"], g.drifting.map(function (d) {
      return "<tr><td>" + esc(d.name) + role(d.role) + "</td><td>" + esc(d.owner) + '</td><td class="num">' + lon(d.lon) + '</td><td class="num">' + (d.drift > 0 ? "+" : "") + d.drift.toFixed(3) + "°/day " + (d.drift > 0 ? "east" : "west") + "</td></tr>";
    }));
    $("geo-strip").innerHTML = strip(g.objects);
    var rows = g.objects.map(function (o) {
      return { key: (o.name + " " + (o.owner || "") + " " + lon(o.lon) + " " + (ROLE[o.role] || "")).toLowerCase(), html: "<tr><td>" + esc(o.name) + role(o.role) + "</td><td>" + esc(o.owner) + "</td><td>" + esc(o.type || "") +
        '</td><td class="num">' + lon(o.lon) + '</td><td class="num">' + (o.drift > 0 ? "+" : "") + o.drift.toFixed(3) + '</td><td class="num">' + o.i.toFixed(2) + "</td><td>" + esc(o["class"]) + "</td></tr>" };
    });
    function draw() {
      var q = ($("geo-q").value || "").trim().toLowerCase(), show = rows.filter(function (r) { return !q || r.key.indexOf(q) >= 0; });
      $("geo-n").textContent = show.length + " of " + rows.length;
      $("geo-table").innerHTML = table(["Object", "Owner", "Type", "Longitude", "Drift °/day", "Inclination °", "Class"], show.map(function (r) { return r.html; }));
    }
    var rl = Object.keys(g.roles || {}).map(function (k) {
      var r = g.roles[k], o = g.objects.filter(function (x) { return String(x.id) === k; })[0];
      return "<li><strong>" + esc(o ? o.name : k) + "</strong>" + role(r.role) + ": " + esc(r.basis) + ". " + r.sources.map(function (s) {
        return '<a href="' + esc(s[1]) + '">' + esc(s[0]) + "</a>"; }).join(", ") + "</li>";
    });
    if ($("geo-roles")) $("geo-roles").innerHTML = rl.length ? '<ul class="small">' + rl.join("") + "</ul>" : "";
    $("geo-q").addEventListener("input", draw);
    draw();
  });
})();
