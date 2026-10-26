/* imagery.js: satellite imagery for the Sea and map pages. Terms and choices: docs/research/2026-10-26-imagery-options.md.
   NFImagery.linksHtml(lat, lon, day, zoom): links that open the providers' own viewers at a place (and a date where the
   viewer takes one). Nothing is loaded from those providers until a visitor clicks; links open in a new tab and send no
   referrer.
   NFImagery.sentinel2(map, opts) / sentinel1(map, opts): one mosaic per month (or the last 30 days) from Microsoft
   Planetary Computer's anonymous tile service: Sentinel-2 true colour, least cloudy scenes first; Sentinel-1 radar (VV),
   latest pass first, which sees through cloud and shows ships as bright points. Copernicus Sentinel data is free for any
   use with attribution; the tile service is a Microsoft "Preview", so failures are shown to the visitor, not hidden. */
(function () {
  "use strict";
  var PC = "https://planetarycomputer.microsoft.com/api/data/v1/mosaic/";
  var MIN_ZOOM = 10;          // the service returns nothing below zoom 9, and zoom 9 is slow
  var NATIVE_ZOOM = 14;       // 10 m pixels; closer zooms stretch the zoom-14 tiles
  var MAX_CLOUD = 40;         // per-scene cloud cover limit, %; scenes are drawn least cloudy first
  var MONTHS_BACK = 24;

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function iso(d) { return d.getUTCFullYear() + "-" + pad(d.getUTCMonth() + 1) + "-" + pad(d.getUTCDate()); }
  function addDays(day, n) { var d = new Date(day + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return iso(d); }
  function f(x, n) { return (+x).toFixed(n); }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; });
  }

  // ---------- link-outs
  function links(lat, lon, day, zoom) {
    zoom = Math.max(3, Math.min(zoom || 15, 18));
    var la = f(lat, 5), lo = f(lon, 5), out = [];
    out.push({ label: "Google Maps", note: "satellite, current",
               href: "https://www.google.com/maps/@?api=1&map_action=map&center=" + la + "%2C" + lo + "&zoom=" + zoom + "&basemap=satellite" });
    out.push({ label: "Google Earth", note: "has a historical imagery button",
               href: "https://earth.google.com/web/@" + la + "," + lo + ",0a," + Math.round(3000 * Math.pow(2, 15 - zoom)) + "d,35y,0h,0t,0r" });
    out.push({ label: "Esri Wayback", note: "sharp imagery, versions since 2014",
               href: "https://livingatlas.arcgis.com/wayback/#mapCenter=" + lo + "%2C" + la + "%2C" + Math.min(zoom + 1, 18) + "&mode=explore" });
    if (day) {
      var hw = Math.max(0.04, Math.min(10, 0.08 * Math.pow(2, 13 - zoom))), hh = hw / 2;   // half-width of the view, degrees
      out.push({ label: "Copernicus Browser", note: "Sentinel-2, 30 days to " + day + " (may ask you to log in)",
                 href: "https://browser.dataspace.copernicus.eu/?zoom=" + Math.min(zoom, 14) + "&lat=" + la + "&lng=" + lo +
                       "&themeId=DEFAULT-THEME&datasetId=S2_L2A_CDAS&layerId=1_TRUE_COLOR&fromTime=" + addDays(day, -30) +
                       "T00%3A00%3A00.000Z&toTime=" + day + "T23%3A59%3A59.999Z&dateMode=TIME%20RANGE" });
      out.push({ label: "NASA Worldview", note: "daily, 30–250 m, on " + day,
                 href: "https://worldview.earthdata.nasa.gov/?v=" + [f(lon - hw, 3), f(lat - hh, 3), f(+lon + hw, 3), f(+lat + hh, 3)].join(",") +
                       "&l=Coastlines_15m,HLS_S30_Nadir_BRDF_Adjusted_Reflectance,HLS_L30_Nadir_BRDF_Adjusted_Reflectance," +
                       "MODIS_Terra_CorrectedReflectance_TrueColor&t=" + day + "-T00%3A00%3A00Z" });
    }
    return out;
  }
  function linksHtml(lat, lon, day, zoom) {
    return '<ul class="img-links">' + links(lat, lon, day, zoom).map(function (l) {
      return '<li><a href="' + esc(l.href) + '" target="_blank" rel="noopener noreferrer">' + esc(l.label) + "</a> " +
             '<span class="small">' + esc(l.note) + "</span></li>";
    }).join("") + "</ul>";
  }

  // ---------- Sentinel-2 monthly mosaics
  function windows() {          // oldest first; the newest is the last 30 days
    var now = new Date(), out = [];
    for (var k = MONTHS_BACK; k >= 1; k--) {
      var a = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - k, 1));
      var b = new Date(Date.UTC(a.getUTCFullYear(), a.getUTCMonth() + 1, 0));
      out.push({ key: iso(a).slice(0, 7), start: iso(a), end: iso(b),
                 label: a.toLocaleString("en-US", { month: "long", year: "numeric", timeZone: "UTC" }) });
    }
    var today = iso(now);
    out.push({ key: "recent", start: addDays(today, -30), end: today, label: "Last 30 days (to " + today + ")" });
    return out;
  }
  function windowFor(wins, day) {   // the window holding a UTC day, or null
    for (var i = wins.length - 1; i >= 0; i--) if (day >= wins[i].start && day <= wins[i].end) return i;
    return null;
  }
  var STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search";
  function utc(t) { return t ? t.slice(0, 10) + " " + t.slice(11, 16) + " UTC" : ""; }
  // Two Planetary Computer collections, both Copernicus data (free for any use with attribution), both anonymous.
  var KINDS = {
    s2: { collection: "sentinel-2-l2a", word: "Imagery",
          tiles: "collection=sentinel-2-l2a&assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0&format=png",
          filter: { op: "<=", args: [{ property: "eo:cloud_cover" }, MAX_CLOUD] },
          sortby: [{ field: "eo:cloud_cover", direction: "asc" }],
          fields: ["properties.datetime", "properties.eo:cloud_cover"],
          scene: function (p) {
            return "Image at the map centre: " + p.datetime.slice(0, 10) +
                   (p["eo:cloud_cover"] !== undefined ? " (" + Math.round(p["eo:cloud_cover"]) + "% cloud over that whole scene)" : "");
          } },
    s1: { collection: "sentinel-1-grd", word: "Radar",
          tiles: "collection=sentinel-1-grd&assets=vv&rescale=0%2C250&colormap_name=gray&format=png",
          filter: { op: "=", args: [{ property: "sar:polarizations" }, ["VV", "VH"]] },
          sortby: [{ field: "datetime", direction: "desc" }],
          fields: ["properties.datetime"],
          scene: function (p) { return "Radar pass at the map centre: " + utc(p.datetime); } }
  };
  function timeFilter(K, w) {
    var t = { op: "anyinteracts", args: [{ property: "datetime" }, { interval: [w.start + "T00:00:00Z", w.end + "T23:59:59Z"] }] };
    return K.filter ? { op: "and", args: [t, K.filter] } : t;
  }
  function post(url, body) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); });
  }
  var searches = {};
  function register(K, w) {         // the service returns the same id for the same query, so this is cheap to repeat
    var key = K.collection + ":" + w.key;
    if (searches[key]) return searches[key];
    searches[key] = post(PC + "register", { collections: [K.collection], "filter-lang": "cql2-json", filter: timeFilter(K, w), sortby: K.sortby })
      .then(function (j) { if (!j.searchid) throw new Error("no search id"); return j.searchid; })
      .catch(function (e) { delete searches[key]; throw e; });
    return searches[key];
  }
  function sceneAt(K, w, lat, lon) { // the scene the mosaic draws first at a point: same collection, filter and order
    return post(STAC, { collections: [K.collection], intersects: { type: "Point", coordinates: [+lon, +lat] },
                        "filter-lang": "cql2-json", filter: timeFilter(K, w), sortby: K.sortby, limit: 1,
                        fields: { include: K.fields, exclude: ["assets", "links"] } })
      .then(function (j) { return j.features && j.features.length ? j.features[0].properties : null; });
  }
  // opts.status(text, isError): loading and failure messages; opts.scene(text): the date of the image at the map centre
  function mosaic(kind, map, opts) {
    var K = KINDS[kind], wins = windows(), layer = null, want = null, sceneT = null, seq = 0;
    function credit(w) {
      var y = w.start.slice(0, 4) === w.end.slice(0, 4) ? w.end.slice(0, 4) : w.start.slice(0, 4) + "–" + w.end.slice(0, 4);
      return K.word + ': contains modified Copernicus Sentinel data ' + y + ', via <a href="https://planetarycomputer.microsoft.com/dataset/' +
             K.collection + '" rel="noopener">Microsoft Planetary Computer</a>';
    }
    function scene() {
      clearTimeout(sceneT);
      if (want === null || !opts.scene) return;
      if (map.getZoom() < MIN_ZOOM) { opts.scene(""); return; }
      var w = wins[want], c = map.getCenter(), my = ++seq;
      sceneT = setTimeout(function () {
        sceneAt(K, w, c.lat, c.lng).then(function (p) {
          if (my === seq && want !== null) opts.scene(p ? K.scene(p) : "No image of the map centre in this period.");
        }).catch(function () { if (my === seq) opts.scene(""); });
      }, 600);
    }
    function onMove() { if (want !== null) { seq++; scene(); } }
    function show(i) {
      var w = wins[i];
      want = i;
      opts.status("Loading " + w.label + "…", false);
      if (opts.scene) opts.scene("");
      register(K, w).then(function (id) {
        if (want !== i) return;
        var errors = 0, next = L.tileLayer(PC + id + "/tiles/WebMercatorQuad/{z}/{x}/{y}@1x?" + K.tiles,
          { minZoom: MIN_ZOOM, maxNativeZoom: NATIVE_ZOOM, maxZoom: 19, attribution: credit(w), className: "img-tiles" });
        next.on("tileerror", function () { if (++errors === 3) opts.status("The imagery service isn't answering for some tiles. Try again later.", true); });
        next.on("load", function () { if (want === i) opts.status("", false); });
        next.addTo(map);
        if (layer) map.removeLayer(layer);
        layer = next;
        if (map.getZoom() < MIN_ZOOM) opts.status("", false);      // the page shows its zoom-in hint
        map.off("moveend", onMove).on("moveend", onMove);
        scene();
      }).catch(function (e) {
        if (want === i) opts.status("The imagery service didn't respond (" + e.message + "). Try again later.", true);
      });
    }
    function hide() {
      want = null; seq++; clearTimeout(sceneT); map.off("moveend", onMove);
      if (layer) { map.removeLayer(layer); layer = null; }
      opts.status("", false);
      if (opts.scene) opts.scene("");
    }
    return { windows: wins, show: show, hide: hide, windowFor: function (day) { return windowFor(wins, day); }, minZoom: MIN_ZOOM };
  }
  function sentinel2(map, opts) { return mosaic("s2", map, opts); }
  function sentinel1(map, opts) { return mosaic("s1", map, opts); }

  window.NFImagery = { links: links, linksHtml: linksHtml, sentinel2: sentinel2, sentinel1: sentinel1 };
})();
