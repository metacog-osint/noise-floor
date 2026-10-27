/* Noisefloor GEO board: /data/geo.json (built at deploy by tools/geo.py from the daily CelesTrak snapshots). */
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
    var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    var day = function (s) { return +s.slice(8, 10) + " " + MON[+s.slice(5, 7) - 1] + " " + s.slice(0, 4); };
    var at = new Date(g.at_utc.replace(/Z$/, "") + "Z"), atText = g.at_utc.slice(11, 16) + " UTC" +
      (window.TicTime && window.TicTime.zone() !== "UTC" ? " (" + window.TicTime.format(at, { date: false }) + ")" : "") + " on " + day(g.at_utc);
    $("geo-status").innerHTML = "<strong>" + c.objects + "</strong> active objects at " + esc(atText) + ": " + c["station-kept"] + " station-kept, " +
      c.inclined + " inclined, " + c.drifting + " drifting. Elements from the snapshot of " + esc(day(g.snapshot_day)) + " (" + g.snapshots + " snapshot" + (g.snapshots === 1 ? "" : "s") + " so far).";
    $("geo-close").innerHTML = g.close_other_owner.length ? table(["Separation", "Object", "Owner", "Near", "Owner", "Longitude", "What the roles say"], g.close_other_owner.map(function (p) {
      return '<tr><td class="num">' + p.km + " km</td><td>" + esc(p.a[1]) + role(p.a[3]) + "</td><td>" + esc(p.a[2]) + "</td><td>" + esc(p.b[1]) + role(p.b[3]) + "</td><td>" + esc(p.b[2]) +
        '</td><td class="num">' + lon(p.lon) + "</td><td>" + esc(p.kind || "") + (p.age_days > 3 ? " (elements " + Math.round(p.age_days) + " days old)" : "") + "</td></tr>";
    })) + '<p class="small">' + g.close_same_owner_count + " more pairs within 100 km share an owner code (often a country, and often co-located on purpose) and aren't listed; a pair with a listed role is always listed.</p>" : "<p>None within 100 km.</p>";
    // orbit changes: the rarer kind first, routine station-keeping folded below
    var KIND = { "started drifting": "Started drifting", "stopped drifting": "Stopped drifting", "drift rate changed": "Drift rate changed",
                 "inclined orbit changed": "Inclination changed on an inclined orbit" };
    var ep = function (s) { return +s.slice(8, 10) + " " + MON[+s.slice(5, 7) - 1] + " " + s.slice(11, 16) + " UTC"; };
    function between(m) {             // the change happened somewhere between the two element sets: give the dates
      var a = m.between[0], b = m.between[1], da = +a.slice(8, 10), db = +b.slice(8, 10), ma = MON[+a.slice(5, 7) - 1], mb = MON[+b.slice(5, 7) - 1];
      var txt = a.slice(0, 10) === b.slice(0, 10) ? day(b) : ma === mb ? da + "–" + db + " " + mb + " " + b.slice(0, 4) : da + " " + ma + " – " + db + " " + mb + " " + b.slice(0, 4);
      return '<td title="Orbital elements of ' + esc(ep(a)) + " and " + esc(ep(b)) + '">' + esc(txt) + "</td>";
    }
    function rates(a, b) {            // "4.18° → 3.78° a day west", or "0.008° a day west → 0.015° a day east"
      var f = function (x) { var v = Math.abs(x); return v.toFixed(v < 0.1 ? 3 : 2) + "°"; }, wa = a < 0 ? "west" : "east", wb = b < 0 ? "west" : "east";
      return wa === wb ? f(a) + " → " + f(b) + " a day " + wa : f(a) + " a day " + wa + " → " + f(b) + " a day " + wb;
    }
    function changed(m) {
      var c = m.changed || [], out = [];
      if (c.indexOf("drift") >= 0) out.push("drift " + rates(m.drift[0], m.drift[1]));
      if (c.indexOf("inclination") >= 0) out.push("inclination " + m.inc[0].toFixed(m.inc[0] < 1 ? 3 : 2) + "° → " + m.inc[1].toFixed(m.inc[1] < 1 ? 3 : 2) + "°");
      if (c.indexOf("longitude") >= 0) out.push(Math.abs(m.dlon).toFixed(2) + "° " + (m.dlon > 0 ? "east" : "west") + " of where its earlier orbit put it");
      var t = out.join("; ");
      return t ? t.charAt(0).toUpperCase() + t.slice(1) + "." : m.what || "";
    }
    function manRows(list, withKind) {
      return list.slice().sort(function (x, y) { return x.between[1] < y.between[1] ? 1 : x.between[1] > y.between[1] ? -1 : x.name < y.name ? -1 : 1; }).map(function (m) {
        return "<tr>" + between(m) + "<td>" + esc(m.name) + "</td><td>" + esc(m.owner) + '</td><td class="num">' + lon(m.lon) + "</td><td>" +
          (withKind ? "<strong>" + esc(KIND[m.kind] || m.kind) + ".</strong> " : "") + esc(changed(m)) + "</td></tr>";
      });
    }
    var mans = g.manoeuvres || [], rare = mans.filter(function (m) { return m.kind && m.kind !== "station-keeping"; }),
        keep = mans.filter(function (m) { return !m.kind || m.kind === "station-keeping"; }), head = ["Between", "Object", "Owner", "Longitude", "What changed"];
    $("geo-man").innerHTML = g.snapshots < 2 ? '<p class="small">None yet: changes need two snapshots, and snapshots began on 26 Oct 2026.</p>' :
      '<h3 id="relocations">Relocations and other changes</h3>' +
      (rare.length ? table(head, manRows(rare, true), "geo-man") : "<p>None this week." + (keep.length ? " Every flagged change was routine station-keeping." : "") + "</p>") +
      (keep.length ? '<details class="table-view"><summary>Routine station-keeping (' + keep.length + " this week)</summary>" + table(head, manRows(keep, false), "geo-man") + "</details>" : "");
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
