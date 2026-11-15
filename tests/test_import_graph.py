"""What an import loads (1519 R1, R2): the ledger with no Dat layer, and no pandas without the tables.

Each check runs in a fresh interpreter: this process has long since imported everything.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(code: str, cwd: Path = ROOT) -> str:
    out = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], cwd=cwd, capture_output=True, text=True,
                         timeout=120)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_the_ledger_loads_without_the_dat_layer():
    out = _run("""
        import sys
        import dvc_dat.ledger
        from dvc_dat.ledger import Ledger, hooks
        loaded = sorted(m for m in sys.modules if m in ("dvc_dat.core", "dvc_dat.do", "dvc_dat.datrun"))
        print("loaded:", loaded)
        print("before:", hooks.dat_class())
        from dvc_dat import Dat
        print("after:", hooks.dat_class() is Dat)
        print("dat is a value:", issubclass(Dat, dvc_dat.ledger.Value))
        print("ledger exports Dat:", "Dat" in dvc_dat.ledger.__all__)
    """)
    assert "loaded: []" in out
    assert "before: None" in out
    assert "after: True" in out
    assert "dat is a value: True" in out
    assert "ledger exports Dat: False" in out


def test_import_dvc_dat_alone_loads_no_dat_layer():
    out = _run("""
        import sys
        import dvc_dat
        print("core:", "dvc_dat.core" in sys.modules, "do:", "dvc_dat.do" in sys.modules)
        print("L:", type(dvc_dat.L).__name__)
        dvc_dat.Namespace
        print("namespace alone:", "dvc_dat.core" in sys.modules)
        dvc_dat.DatManager
        print("manager:", "dvc_dat.core" in sys.modules)
    """)
    assert "core: False do: False" in out
    assert "namespace alone: False" in out
    assert "manager: True" in out


def test_a_stored_dat_reads_back_in_a_cold_process(tmp_path):
    """A dat row read by its class name from a process that never imported the Dat layer: the decode imports
    ``dvc_dat.core`` by name, which registers itself, and the value is a ``Dat``."""
    db = tmp_path / "led"
    _run(f"""
        from dvc_dat import Dat, DatManager
        from dvc_dat.ledger import Ledger
        Dat.manager = DatManager(dat_folders=[{str(tmp_path / 'dats')!r}])
        dat = Dat.create({{"dat": {{}}, "x": 1}}, path="d1")
        led = Ledger({str(db)!r}, create=True)
        dat.save()
        dat.seal(led, name="one")
    """, cwd=tmp_path)
    out = _run(f"""
        import sys
        from dvc_dat.ledger import Ledger, hooks
        led = Ledger({str(db)!r})
        assert "dvc_dat.core" not in sys.modules
        v = led.at().load("one")
        print("kind:", type(v).__module__, type(v).__name__, hooks.is_dat(v), v.get_spec()["x"])
    """, cwd=tmp_path)
    assert "kind: dvc_dat.core Dat True 1" in out


def test_pandas_is_not_loaded_by_the_dat_layer():
    out = _run("""
        import sys
        from dvc_dat import Dat, DatManager
        DatManager(dat_folders=["."])
        print("pandas:", "pandas" in sys.modules)
    """)
    assert "pandas: False" in out


def test_the_tables_without_pandas_name_the_extra():
    out = _run("""
        import sys
        sys.modules["pandas"] = None            # as if not installed
        from dvc_dat import dat_tools
        try:
            dat_tools.Cube(points=[{"a": 1}]).get_df()
        except ImportError as e:
            print("error:", e)
    """)
    assert "install dvc-dat[tools]" in out
