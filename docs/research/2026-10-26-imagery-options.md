# Satellite imagery for the site: options and terms (26 Oct 2026)

**Status:** research for Tom's decision; nothing built. Checked 26 Oct 2026 by Claude: three research passes over the
providers' own pricing, terms and documentation pages, then the deciding clauses re-read on the original pages
(Google Geo Guidelines, Map Tiles policy and Embed billing; Esri Location Platform billing help and Agreement E204;
the Copernicus Sentinel data legal notice; EOX's licence page). Terms and prices change: re-check before building.
Anything marked *unconfirmed* was not found on an official page.

## What we want, and the limits

- **U1, imagery in our own maps.** The map and Sea pages use Leaflet 1.9.4 with no tile basemap at all today (land is
  drawn from Natural Earth outlines we host), so any imagery layer is the site's first outside map dependency.
- **U2, a time slider:** imagery at a place changing over time.
- **U3, link-outs:** a link that opens a provider's own viewer at the place (and date, where possible).
- **Limits:** free, with no way to run up a bill; terms that allow a public site run by a business (treated as
  commercial use even though the site is free and has no ads); every source recorded with its licence in
  `registry/sources.csv` before it feeds a layer.

## Bottom line

1. **No provider lets us embed sharp (sub-metre) historical imagery for free under clear terms.** Sharp history exists
   in Google Earth's and Esri Wayback's own viewers, so for us it is a link-out.
2. **Sharp current imagery inside our maps: only Esri's ArcGIS Location Platform fits.** Free, no card at sign-up, it
   stops at the free limit instead of billing, and it includes a commercial deployment licence. The conditions are real:
   Esri's agreement bars access from Iran, Syria, North Korea, Cuba, Crimea, DNR/LNR, and bars providing access to
   Russia or Belarus, so the layer needs a country check; plus "Powered by Esri" and data credits, a site terms page that
   binds users to Esri's terms, a yearly key renewal, and no imagery in our ODbL downloads.
3. **A time slider inside our maps: Sentinel-2 (10 m, about every 5 days since 2015) or NASA's HLS (30 m).** Cleanest is
   image chips we make ourselves and host as static files; also free are Microsoft Planetary Computer tiles (a Preview
   service) and NASA GIBS tiles with the date in the URL.
4. **Link-outs are free, need no key and raise no licence question:** Google Maps satellite view, Esri Wayback (with a
   date), Copernicus Browser (with a date), NASA Worldview (with a date), Google Earth (has historical imagery; link
   format undocumented).
5. **Ruled out:** Google satellite tiles in our map (card, no monthly cap, and Google's terms bar its maps "with or near
   a non-Google Map"); embedding Google Earth (prohibited) and commercial use of Google Earth imagery on the web; Azure
   Maps (card, no cap); Apple MapKit JS (paid developer account, its own renderer, an "asset tracking" clause); Bing Maps
   (free accounts retired 30 Jun 2025); Mapbox raster and HERE (card, no cap found); MapTiler and Stadia free plans
   (non-commercial); EOX Sentinel-2 cloudless (commercial use needs a paid EOX licence); Vantor open data and Planet
   (non-commercial); Earth Engine (no free commercial tier); Copernicus Sentinel Hub tiles for visitors (10,000 requests a
   month per account, account ID exposed in the page).

## Comparison

| Option | Sharpness | History in our map (U2) | Free allowance | Card needed? Can it bill? | Commercial use | In our Leaflet map (U1) | Verdict |
|---|---|---|---|---|---|---|---|
| **Esri Location Platform**, World Imagery | 15 cm–1.2 m (Vantor Vivid), community aerial 3–30 cm; current only | No | 2,000,000 basemap tiles a month (about 50,000–80,000 map views, estimate) | No card to sign up; pay-as-you-go off by default; over the limit, access stops until next month | Yes: "commercial deployment license" | Yes (esri-leaflet, key) | **Fits with conditions** (export clause, attribution, user terms, key renewal) |
| **Esri World Imagery Wayback** tiles | Same imagery; 197 versions, 20 Feb 2014 – 24 Sep 2026 | Technically yes | No key | Nothing to bill | No licence for third-party sites found | Works technically (tested) | **Ask Esri in writing**; link-out fits |
| **Google Map Tiles API** (satellite) | Sharp; current only | No date option | 100,000 tile requests a month (about 3,000–5,000 views, estimate) | Card required; budgets "do not automatically cap"; only a daily quota limits use | Yes | Unclear: ToS §3.2.3(e) | **Doesn't fit** |
| **Google Maps Embed API** (iframe) | Sharp; current only | No | Free, unlimited | Billing account (card) needed to get the key; Embed use itself is $0 | Yes | No (an iframe panel, not a layer) | Possible as a per-place panel, with a card on file |
| **Google Earth** | Sharp, with history | Only inside Google Earth | — | — | "may not use Google Earth imagery on the web for any commercial or promotional purposes" | Embedding prohibited | **Link-out only** |
| **Azure Maps** imagery | Satellite/aerial, zoom 1–19 | No | 1,000 transactions = 15,000 tiles a month | Card; no spending cap on pay-as-you-go | Terms not readable (*unconfirmed*) | Yes (official plugin) | **Doesn't fit** |
| **Apple MapKit JS** | Apple satellite | No | 250,000 map views a day | Apple Developer Program, $99 a year | Bars "asset tracking" on non-Apple hardware | No (Apple renderer only) | **Doesn't fit** |
| **Mapbox Satellite** | 0.3–2 m, 7.5 cm in places | No | 750,000 raster tiles a month | Card required for the raster API; no cap found | "business intelligence or analytics" needs a paid licence | Yes | **Doesn't fit** |
| **MapTiler Satellite** | 2 m global | No | 100,000 requests a month | No card; hard stop | Free plan "limited to non-commercial use" | Yes | **Doesn't fit** |
| **Stadia Alidade Satellite** | Airbus/PlanetObserver | No | 200,000 credits a month | No card; hard stop | Free plan "Commercial use not allowed" | Yes | **Doesn't fit** |
| **HERE** satellite | — | No | 30,000 a month (*unconfirmed*) | Card required since Aug 2025 | *Unconfirmed* | Yes | **Doesn't fit** |
| **TomTom** satellite | Vantor imagery | No | 200,000 tiles a month, no card | Over-limit behaviour not stated | *Unconfirmed* | Probably | **Unconfirmed** |
| **Sentinel-2 chips we make** | 10 m | Yes: any clear date since 2015 | Free | Nothing to bill | Yes (Copernicus notice) | Yes (image overlays) | **Fits** |
| **Planetary Computer tiles** (Sentinel-2/1, Landsat, HLS) | 10–30 m | Yes (one registered search per date window) | Free, anonymous; rate limit unpublished | Nothing to bill | Not prohibited; a Preview service, may change without notice | Yes (tested) | **Fits with conditions** |
| **NASA GIBS** | HLS 30 m (with gaps); MODIS/VIIRS 250 m daily since 2000 | Yes: date in the tile URL | Free, no key; rate limit unpublished | Nothing to bill | Yes (NASA open data) | Yes (tested) | **Fits** |
| **Copernicus Sentinel Hub** (CDSE) | 10 m | Yes | 10,000 requests a month per account | No | Data yes | Exposes the account's instance ID | **Doesn't fit** for visitors |
| **EOX Sentinel-2 cloudless** | 10 m, one mosaic a year 2016–2025 | Yearly | Free service, rate-limited | — | Commercial use (web services included) needs a paid EOX licence | Yes | **Doesn't fit** |
| **National orthophotos** (own country only) | 5 cm–0.5 m | Latest only, mostly | Free | — | Estonia yes; others mixed | Some | See below |

Notes on the comparison:
- **How often sharp imagery changes at one place.** A Wayback version is a new mosaic of the whole world, not a new
  picture of every place. At one Baltic location, reading every sixth version, the image changed at least 10 times in
  12 years, about yearly since 2021, at 0.31–0.6 m; the current basemap there was captured on 20 May 2025.
- **National orthophotos.** Estonia: 10–25 cm, no key, commercial use allowed (licence of 1 Jan 2025), but the agency
  said in Nov 2025 it will likely reduce resolution and require login for the sharpest imagery. Poland: 5–25 cm, no key;
  licence text not found. Finland: 0.5 m, needs a personal key, "intended for testing … and for small-scale use".
  Denmark: about 12.5 cm, account key, CC BY 4.0. Latvia, Lithuania, Sweden: *unconfirmed* (Lithuania's older guidance
  required permission to publish on a website).
- **Open SAR samples** (Capella, Umbra, Satellogic optical 1 m): CC BY 4.0 sample sets, not map services; Capella adds a
  US-sanctions transfer clause, and Umbra's licence link currently shows generic site terms. Worth a look for the
  maritime lane, not for a basemap.

## Link-out formats

| Viewer | Link (replace LAT, LON, ZOOM, dates) | Date? | Status |
|---|---|---|---|
| Google Maps, satellite | `https://www.google.com/maps/@?api=1&map_action=map&center=LAT%2CLON&zoom=18&basemap=satellite` | No | Documented; no key. Google's brand rules welcome "View on Google Maps" links |
| Esri Wayback | `https://livingatlas.arcgis.com/wayback/#mapCenter=LON%2CLAT%2CZOOM&mode=explore&active=RELEASE` | Yes (RELEASE from the version list) | Read from the app's own code, not documented. **Longitude first** |
| Copernicus Browser | `https://browser.dataspace.copernicus.eu/?zoom=12&lat=LAT&lng=LON&themeId=DEFAULT-THEME&datasetId=S2_L2A_CDAS&layerId=1_TRUE_COLOR&fromTime=YYYY-MM-DDT00%3A00%3A00.000Z&toTime=YYYY-MM-DDT23%3A59%3A59.999Z&dateMode=SINGLE` | Yes | Documented in the browser's repository; visitors may be offered a login or "Use anonymously" |
| NASA Worldview | `https://worldview.earthdata.nasa.gov/?v=MINLON,MINLAT,MAXLON,MAXLAT&l=HLS_S30_Nadir_BRDF_Adjusted_Reflectance,Coastlines_15m&t=YYYY-MM-DD-T00%3A00%3A00Z` | Yes | Documented (`v` is a bounding box) |
| Google Earth | `https://earth.google.com/web/@LAT,LON,…` | No (historical imagery is a button in Earth) | Undocumented; seen in working examples only |
| Planetary Computer Explorer | `https://planetarycomputer.microsoft.com/explore?c=LON%2CLAT&z=10&v=2&d=sentinel-2-l2a&…` | No | Tested |

Not recommended: Sentinel Hub EO Browser (shut down 20 Mar 2026); Bing consumer links (Bing Maps for Enterprise is being
retired; the link format page dates from 2018); Apple Maps links (behaviour on non-Apple devices *unconfirmed*).

## The clauses that decide it (quoted from the original pages)

**Google**
- Geo Guidelines: "Google Earth may not be embedded online or in apps." "You may not use Google Earth imagery on the
  web for any commercial or promotional purposes". Links are welcome: "You're also welcome to link to Google Maps with
  text or a button on your website". Attribution must stay "within close proximity of the content".
- Maps Platform ToS §3.2.3(e): "Customer will not use the Google Maps Core Services with or near a non-Google Map in a
  Customer Application." Map Tiles API is a Core Service. Its policy page does mention third-party renderers, but not
  Leaflet; written confirmation from Google would be needed.
- Map Tiles policy: for "map visualizations" only; image analysis, machine interpretation, object detection or
  identification, geodata extraction and offline use are excluded. No pre-fetching, storing or caching.
- Billing: a budget "does not automatically cap Google Cloud or Google Maps Platform usage or spending".
- Maps Embed API: "free to use with unlimited requests"; "An API key is required for all Maps Embed API requests."

**Esri** (ArcGIS Location Platform Agreement E204, revised 21 Nov 2025; billing help page)
- Billing: pay-as-you-go is "turned off by default for new accounts"; "A payment method is required to enable
  pay-as-you-go"; without it, use is limited to the free tiers and tile access returns at the next billing cycle.
- 11.4 Export compliance: no use "to, by or from any United States embargoed countries currently including Iran, Syria,
  North Korea, Cuba, Crimea region of Ukraine, the Donetsk People's Republic (DNR) and Luhansk People's Republic (LNR)";
  "Additionally, Customer will not export, reexport, transfer, provide access or release any Esri Offerings to Russia or
  Belarus." The customer must "cause the Customer's Application Users" to comply.
- 3.1.c.5: our site must include terms requiring users "to comply with the applicable terms and conditions of this
  Agreement".
- 3.1.a.4: Esri output may not be combined "in a manner that would subject … Resultant Output to open-source or
  open-database use or license terms". Showing our ODbL data over the imagery is display; putting imagery into ODbL
  downloads is not allowed.
- 3.1.d.3: output "only for visualization purposes and only within Customer Applications"; the site must add
  "substantial and independent functionality".
- Wayback items say "This work is licensed under the Esri Master License Agreement" and that the layer "is not intended
  to be used to export tiles for offline". No page licensing Wayback tiles on third-party sites was found.

**Copernicus** (Sentinel data legal notice)
- "free, full and open access" for "(a) reproduction; (b) distribution; (c) communication to the public; (d)
  adaptation, modification and combination with other data and information". Commercial use is not excluded.
- Credit: "Copernicus Sentinel data [Year]", or "Contains modified Copernicus Sentinel data [Year]" for processed images
  (our chips would be clipped and tone-mapped, so the second).
- "EU law allows for specific limitations of access and use in the rare cases of security concerns".

**NASA GIBS:** no fees or access constraints in the service description; NASA "promotes the full and open sharing of
data". Requested acknowledgement: "We acknowledge the use of imagery provided by services from NASA's Global Imagery
Browse Services (GIBS), part of NASA's Earth Science Data and Information System (ESDIS)."

**Others:** Mapbox Product Terms 1.2.3 (business intelligence or analytics needs a commercial licence); MapTiler Cloud
terms 1.2 ("Usage of the Free Plan is limited to non-commercial use"); Stadia pricing ("Commercial use not allowed" on
the free plan); Apple Developer Program Licence Agreement, Attachment 6 §1.2 ("asset tracking").

## Export controls apply to any US provider's layer

Esri states it outright, and MapTiler and Capella have similar clauses. Noise Floor has readers in the regions it
covers. Any imagery layer from a US provider should load only after a country check: on Cloudflare, a small Pages
Function can read the visitor's country and tell the page whether to offer the layer (within the free tier). Whether
that is sufficient for compliance (VPNs) is a legal question, not answered here. Link-outs avoid the issue: the visitor
goes to the provider, which applies its own rules.

## Options to decide

| | What visitors get | Cost and terms | Tom's part |
|---|---|---|---|
| **A. Link-outs** | "View on Google Maps (satellite)", "Esri Wayback (history)", "Copernicus Browser (this date)", "NASA Worldview (this date)" on ship details and map popups | Free; no keys; no licence question | None |
| **B. Sentinel-2 time slider in our maps** | 10 m true-colour images for chosen places and dates, swapped by a slider; links out for sharper views | Free; Copernicus credit; about 150 MB for 30 places × 24 dates; no runtime dependency | Choose the places (private watch list stays private: only places shown publicly) |
| **C. Sharp current imagery in our maps** | Esri World Imagery as a layer | Free tier with a hard stop; export-country check, site terms page, attribution, yearly key | Create the Location Platform account and key (needs your OK; you run key creation) |
| **D. Sharp history in our maps** | Esri Wayback versions on a slider | Needs Esri's written permission | Send Esri the question (draft on request) |

Recommendation: A now; B next; C and D only if sharp imagery inside the map is worth the export-control handling and a
terms page.

## Decision (Tom, 26 Oct 2026) and status

Tom chose A, B and C.
- **A, link-outs:** live on the Sea ship panel and the GNSS map's area history (36e9c30).
- **B, Sentinel-2 by month:** live on the Sea map (36e9c30). Built on Planetary Computer's tile service rather than
  chips we host, so it works anywhere in the map without a list of places (a list would be watch configuration).
- **C, Esri World Imagery:** live from 26 Oct 2026 (48baa95): the Sea map option, `functions/api/imagery.js` (a
  Cloudflare Pages Function that hands out the key only outside the barred countries and regions, tested on 16 cases),
  the `/terms` page, and attribution. Tom created the key on 26 Oct with one privilege (Location services → Basemaps →
  Static basemap tiles, as in Esri's Leaflet raster tutorial), the referrer `https://noisefloor.theintelligence.company`
  and an expiry of **26 Oct 2027 (renew before then)**, and stored it as the Pages secret `ESRI_API_KEY` with
  `npx wrangler pages secret put`. One key per app: the free allowance is per account anyway, and separate keys can be
  rotated, scoped and checked against Esri's export terms app by app.
  Checked live: `/api/imagery` returns the key to a US visitor (`Cache-Control: private, no-store`), the Sea map's Esri
  option loads tiles, and the credits show. **Not verifiable from outside:** Esri's tile server returned tiles for a
  wrong referrer and, the day before, for a made-up token, so neither the referrer restriction nor the usage count can
  be confirmed by request; the account's usage page is the check.

## Not confirmed

- Esri: the live sign-up flow (card never asked?), whether the raster imagery service counts against the 2M-tile pool,
  whether Wayback tiles may be used on third-party sites, and whether Wayback items count as Living Atlas layers (which
  need "a custom license agreement" in apps).
- Google: whether Map Tiles in Leaflet is allowed under §3.2.3(e); Google Earth link format.
- Planetary Computer and GIBS: no published rate limits; Planetary Computer's tiler is a Preview.
- EOX: one EOX page lists the 2016 mosaic as CC BY 4.0, the main licence page doesn't mention CC BY; treat as needing a
  licence.
- HERE, TomTom, Azure Maps: commercial terms not readable; Apple link behaviour off Apple devices.
- National orthophotos for Latvia, Lithuania, Sweden; Poland's licence text; Estonia's planned changes (undated).

## Sources (all read 26 Oct 2026)

Google: [Geo Guidelines](https://about.google/brand-resource-center/products-and-services/geo-guidelines/) ·
[Maps Platform Terms](https://cloud.google.com/maps-platform/terms) ·
[Service Specific Terms](https://cloud.google.com/maps-platform/terms/maps-service-terms) ·
[Maps Core Services list](https://cloud.google.com/maps-platform/terms/maps-services/) ·
[Map Tiles policies](https://developers.google.com/maps/documentation/tile/policies) ·
[2D tiles overview](https://developers.google.com/maps/documentation/tile/2d-tiles-overview) ·
[Pricing](https://developers.google.com/maps/billing-and-pricing/pricing) ·
[Manage costs](https://developers.google.com/maps/billing-and-pricing/manage-costs) ·
[Embed API billing](https://developers.google.com/maps/documentation/embed/usage-and-billing) ·
[Maps URLs](https://developers.google.com/maps/documentation/urls/get-started) ·
[Earth historical imagery](https://support.google.com/earth/answer/15468379) ·
[Earth Engine commercial pricing](https://cloud.google.com/earth-engine/pricing) ·
[Earth Engine noncommercial](https://earthengine.google.com/noncommercial/)

Microsoft and Apple: [Bing Basic shutdown](https://blogs.bing.com/maps/2025/6/Bing-Maps-for-Enterprise-Basic-Account-shutdown-June-30%2C2025/) ·
[Azure Maps pricing](https://azure.microsoft.com/en-us/pricing/details/azure-maps/) ·
[Azure Maps transactions](https://learn.microsoft.com/en-us/azure/azure-maps/understanding-azure-maps-transactions) ·
[Azure spending limit](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/spending-limit) ·
[MapKit JS](https://developer.apple.com/maps/mapkitjs/) ·
[Apple Developer Program Licence Agreement](https://developer.apple.com/support/terms/apple-developer-program-license-agreement/)

Esri: [Location Platform pricing](https://location.arcgis.com/pricing/) ·
[Billing help](https://location.arcgis.com/help/billing/) ·
[Licensing and attribution](https://location.arcgis.com/help/licensing-and-attribution/) ·
[Agreement E204](https://esri.com/content/dam/esrisites/en-us/media/legal/platform/platform-legal.pdf) ·
[Product-Specific Terms E300](https://www.esri.com/content/dam/esrisites/en-us/media/legal/product-specific-terms-of-use/e300.pdf) ·
[Basemap Styles service](https://developers.arcgis.com/rest/basemap-styles/) ·
[API key authentication](https://developers.arcgis.com/documentation/security-and-authentication/api-key-authentication/) ·
[Wayback version list](https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json) ·
[Wayback app source](https://github.com/Esri/wayback) ·
[World Imagery item](https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9) ·
[Static map image terms](https://doc.arcgis.com/en/arcgis-online/reference/static-maps.htm)

Other commercial: [Mapbox pricing](https://www.mapbox.com/pricing) · [Mapbox terms](https://www.mapbox.com/legal/service-terms) ·
[Mapbox sign-up](https://docs.mapbox.com/accounts/guides/signup.md) · [MapTiler pricing](https://www.maptiler.com/cloud/pricing/) ·
[MapTiler terms](https://www.maptiler.com/cloud/terms/) · [Stadia pricing](https://stadiamaps.com/pricing/) ·
[HERE release notes](https://www.here.com/learn/blog/july-2025-platform-release-notes/) · [TomTom pricing](https://docs.tomtom.com/pricing) ·
[Vantor open data](https://registry.opendata.aws/vantor-open-data/) · [Planet terms](https://www.planet.com/terms-of-use/)

Open sources: [Sentinel data legal notice](https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice) ·
[CDSE quotas](https://documentation.dataspace.copernicus.eu/Quotas.html) ·
[CDSE terms](https://dataspace.copernicus.eu/terms-and-conditions) ·
[Copernicus Browser deep links](https://github.com/eu-cdse/copernicus-browser/blob/main/public/deep-linking.txt) ·
[EO Browser sunset](https://community.planet.com/product-updates/important-update-sunset-of-eo-browser-and-sentinel-hub-dashboard-6426) ·
[Planetary Computer terms](https://planetarycomputer.microsoft.com/terms) ·
[Planetary Computer data API](https://planetarycomputer.microsoft.com/docs/quickstarts/using-the-data-api/) ·
[EOX licence](https://cloudless.eox.at/documentation/license) ·
[GIBS API docs](https://nasa-gibs.github.io/gibs-api-docs/) ·
[NASA data policy](https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-information-guidance) ·
[Worldview URL parameters](https://github.com/nasa-gibs/worldview/blob/main/doc/url_parameters.md) ·
[USGS Landsat use](https://www.usgs.gov/faqs/are-there-any-restrictions-use-or-redistribution-landsat-data) ·
[Estonia open data licence](https://geoportaal.maaamet.ee/avaandmete-litsents) ·
[Estonia resolution plans (ERR)](https://www.err.ee/1609870686/) ·
[Poland orthophoto](https://www.geoportal.gov.pl/en/dane/ortofotomapa) ·
[Finland NLS terms](https://www.maanmittauslaitos.fi/en/node/11151) ·
[Denmark terms](https://datafordeler.dk/vejledning/brugervilkaar/kds-geografiske-data/) ·
[Cloudflare Pages limits](https://developers.cloudflare.com/pages/platform/limits/)
