"""Run testrun.run() as a separate process (so a test can SIGKILL the worker).

usage: worker_harness.py RUN_DIR LIVE_DIR TOKEN
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "plugin/dns/dnscrypt-routes/src/opnsense/scripts/dnscrypt_routes"))
import testrun  # noqa: E402

testrun.RUN_DIR, testrun.LIVE_DIR = sys.argv[1], sys.argv[2]
testrun.DRILL = str(HERE / "stub-drill")


def render(root):
    target = Path(root) / testrun.RENDERED_CONFIG
    target.parent.mkdir(parents=True)
    shutil.copy(HERE / "rendered.toml", target)


testrun.run(render=render, token=sys.argv[3])
