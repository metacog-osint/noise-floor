"""Offline test for collectors/bluesky.py normalization and keyword matching (no network)."""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "collectors"))
import bluesky as B  # noqa: E402


def item(handle, text, repost_by=None, alt=None, ext=None):
    post = {"uri": f"at://did:plc:x/app.bsky.feed.post/abc{len(text)}", "indexedAt": "2026-10-14T12:00:00Z",
            "author": {"handle": handle}, "record": {"text": text, "createdAt": "2026-10-14T11:59:00Z"},
            "embed": {"images": [{"alt": alt}]} if alt else ({"external": ext} if ext else {})}
    it = {"post": post}
    if repost_by:
        it["reason"] = {"$type": "app.bsky.feed.defs#reasonRepost", "indexedAt": "2026-10-14T12:05:00Z"}
    return it


def test_normalize_and_match():
    pats = [re.compile(r"jamm\w*", re.I), re.compile(r"\bNOTAM\b", re.I)]
    own = B.normalize(item("a.bsky.social", "GPS jamming near the coast", alt="map of NOTAM area"), "a.bsky.social")
    assert own and not own["repost"] and own["url"].endswith("/post/abc26") and own["alt"] == ["map of NOTAM area"]
    assert B.match(own, pats) == [r"\bNOTAM\b", r"jamm\w*"], B.match(own, pats)
    rp = B.normalize(item("b.bsky.social", "quiet day", repost_by="a"), "a.bsky.social")
    assert rp and rp["repost"] and rp["author"] == "b.bsky.social" and B.match(rp, pats) == []
    other = B.normalize(item("c.bsky.social", "reply from someone else"), "a.bsky.social")
    assert other is None, "only the account's own posts and its reposts are kept"
    lk = B.normalize(item("a.bsky.social", "read this", ext={"uri": "https://x.test/a", "title": "Spoofing report"}), "a.bsky.social")
    assert lk["link"] == {"uri": "https://x.test/a", "title": "Spoofing report"}


if __name__ == "__main__":
    test_normalize_and_match()
    print("PASS test_normalize_and_match")
