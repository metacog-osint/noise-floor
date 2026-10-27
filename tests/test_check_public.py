"""Tests for tools/check_public.py's matching rule. Run as a plain script: python tests/test_check_public.py"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import check_public as C  # noqa: E402


def test_found():
    f = C.found
    assert f("acme", "made by acme corp") and f("acme", "acmeco")             # text terms: plain substrings
    assert not f("acme", "nothing here")
    assert f("12345", "zip 12345 here") and f("12345", "12345") and f("12345", "(12345)") and f("12345", "12345.")
    assert f("12345", "code:12345,")                                           # punctuation around it still counts
    assert not f("12345", "60.123456")                                          # inside a decimal
    assert not f("12345", "[1793012345, 59.1, 24.2]")                           # inside a longer number
    assert not f("12345", "112345") and not f("12345", "123456")
    assert not f("12345", "3.12345") and not f("12345", "12345.6")             # decimal digits either side
    assert f("7015551234", "+17015551234") and f("7015551234", "tel 7015551234")  # long digit terms: plain substrings


def main():
    test_found()
    print("test_check_public: ok (1 test)")


if __name__ == "__main__":
    main()
