"""Offline test for collectors/feeds.py parsing (RSS 2.0 and Atom)."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "collectors"))
import feeds as F  # noqa: E402

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
<item><title>GPS jamming &amp; the Baltic</title><link>https://x.test/a</link><guid>a1</guid>
<pubDate>Tue, 13 Oct 2026 08:00:00 GMT</pubDate><description>&lt;p&gt;Spoofing near &lt;b&gt;Kaliningrad&lt;/b&gt;&lt;/p&gt;</description></item>
</channel></rss>"""
ATOM = b"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>G</title>
<entry><id>tag:github.com,2008:PushEvent/1</id><link type="text/html" rel="alternate" href="https://github.com/x/y/compare/1"/>
<title>pushed to main in x/VLF-Direction-Finding-Grabber</title><updated>2026-10-12T10:00:00Z</updated>
<content type="html">&lt;div&gt;Update grabber&lt;/div&gt;</content></entry></feed>"""


def test_parse():
    r = F.parse(RSS)
    assert r == [{"id": "a1", "link": "https://x.test/a", "title": "GPS jamming & the Baltic",
                  "published": "2026-10-13T08:00:00+00:00", "summary": "Spoofing near Kaliningrad"}], r
    a = F.parse(ATOM)
    assert a[0]["link"] == "https://github.com/x/y/compare/1" and a[0]["published"] == "2026-10-12T10:00:00+00:00"
    assert a[0]["title"].endswith("VLF-Direction-Finding-Grabber") and a[0]["summary"] == "Update grabber"
    assert F.when("2026-09-15 18:10:26 UTC") == "2026-09-15T18:10:26+00:00", "GitHub activity-feed date format"


if __name__ == "__main__":
    test_parse()
    print("PASS test_parse")
