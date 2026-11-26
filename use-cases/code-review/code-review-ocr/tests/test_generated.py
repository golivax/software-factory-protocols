"""protocol.json and the agent units are what their generators write."""
import pathlib
import subprocess
import sys

PKG = pathlib.Path(__file__).resolve().parents[1]
GEN = PKG / "tests" / "generate"


def test_protocol_json_is_generated():
    r = subprocess.run([sys.executable, str(GEN / "gen_protocol.py")], capture_output=True, text=True,
                       check=True)
    assert r.stdout == (PKG / "protocol.json").read_text(), \
        "protocol.json differs from tests/generate/gen_protocol.py: regenerate it"


def test_agent_units_are_generated(tmp_path):
    subprocess.run([sys.executable, str(GEN / "gen_agents.py"), str(tmp_path)], capture_output=True,
                   check=True)
    for unit in sorted(tmp_path.glob("*.md")):
        assert unit.read_text() == (PKG / "workflows" / unit.name).read_text(), \
            f"workflows/{unit.name} differs from tests/generate/gen_agents.py: regenerate it"
