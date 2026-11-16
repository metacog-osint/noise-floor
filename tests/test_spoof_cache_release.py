"""tools/spoof_cache_release.py: pack a day cache, extract it back unchanged, and refuse unsafe tar members.
Run as a plain script (CI has no pytest)."""
import io
import json
import os
import sys
import tarfile
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import spoof_cache_release as R  # noqa: E402


def refuses(tar_path, dest, root):
    try:
        R.extract(tar_path, dest, root)
    except SystemExit:
        return True
    return False


def main():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "2024-02-20")
        os.makedirs(src)
        files = {"meta.json": json.dumps({"day": "2024-02-20", "candidates": 2}).encode(),
                 "records.pkl.gz": os.urandom(3000), "cand-1.bin": os.urandom(5000)}
        for n, b in files.items():
            open(os.path.join(src, n), "wb").write(b)
        os.makedirs(os.path.join(src, "subdir"))          # folders are not packed
        tp = os.path.join(tmp, "day.tar")
        names = R.pack_dir(src, tp, "2024-02-20")
        assert names == sorted(files), names
        assert len(R.sha256(tp)) == 64
        dest = os.path.join(tmp, "out", "2024-02-20")
        R.extract(tp, dest, "2024-02-20")
        for n, b in files.items():
            assert open(os.path.join(dest, n), "rb").read() == b, n
        assert sorted(os.listdir(dest)) == sorted(files)

        # a folder without meta.json is not a day cache
        os.makedirs(os.path.join(tmp, "empty"))
        try:
            R.pack_dir(os.path.join(tmp, "empty"), os.path.join(tmp, "x.tar"), "x")
            raise AssertionError("packed a folder with no meta.json")
        except SystemExit:
            pass

        # unsafe members are refused: path escape, wrong root, nested path, symlink
        for name, kind in (("../evil", tarfile.REGTYPE), ("other/meta.json", tarfile.REGTYPE),
                           ("2024-02-20/a/b", tarfile.REGTYPE), ("2024-02-20/link", tarfile.SYMTYPE)):
            bad = os.path.join(tmp, "bad.tar")
            with tarfile.open(bad, "w") as t:
                ti = tarfile.TarInfo(name)
                ti.type = kind
                if kind == tarfile.SYMTYPE:
                    ti.linkname = "/etc/passwd"
                    t.addfile(ti)
                else:
                    ti.size = 3
                    t.addfile(ti, io.BytesIO(b"abc"))
            assert refuses(bad, os.path.join(tmp, "bad_out"), "2024-02-20"), name
        assert not os.path.exists(os.path.join(tmp, "evil"))
    print("test_spoof_cache_release: ok")


if __name__ == "__main__":
    main()
