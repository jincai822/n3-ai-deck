from __future__ import annotations

import ast
import json
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path
from typing import Any

import pytest

import streamdock_n3.discovery as discovery
from streamdock_n3.discovery import discover_usb_devices

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_MODULES = (
    Path("src/streamdock_n3/device_catalog.py"),
    Path("src/streamdock_n3/discovery.py"),
)
FORBIDDEN_SOURCE = (
    "DeviceManager",
    "LibUSBHIDAPI",
    "streamdock_n3._vendor",
    "import evdev",
    "import pyudev",
    "import gi",
    "subprocess",
    "os.open",
    "/dev/hidraw",
    "/dev/input",
)
ALLOWED_ATTRIBUTES = discovery.ALLOWED_DEVICE_ATTRIBUTES | discovery.ALLOWED_INTERFACE_ATTRIBUTES


def write_attr(parent: Path, name: str, value: str) -> None:
    parent.mkdir(parents=True, exist_ok=True)
    (parent / name).write_text(value + "\n", encoding="ascii")


def add_complete_target(root: Path) -> None:
    for name, value in (
        ("idVendor", "6602"),
        ("idProduct", "1000"),
        ("bcdDevice", "0300"),
    ):
        write_attr(root / "1-2", name, value)
    for name, value in (
        ("bInterfaceNumber", "00"),
        ("bInterfaceClass", "03"),
        ("bInterfaceSubClass", "00"),
        ("bInterfaceProtocol", "00"),
    ):
        write_attr(root / "1-2:1.0", name, value)


def test_m1_production_sources_exclude_active_hardware_dependencies() -> None:
    for relative in PRODUCTION_MODULES:
        source = relative.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_SOURCE:
            assert forbidden not in source


def test_discovery_imports_only_standard_library_and_device_catalog() -> None:
    source = Path("src/streamdock_n3/discovery.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in sys.stdlib_module_names
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("streamdock_n3"):
                assert module == "streamdock_n3.device_catalog"
            else:
                assert module.split(".")[0] in sys.stdlib_module_names


def test_m1_sources_limit_all_file_io_call_sites() -> None:
    for relative in PRODUCTION_MODULES:
        tree = ast.parse(relative.read_text(encoding="utf-8"))
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "read_text":
                    cursor: ast.AST | None = node
                    enclosing_function: str | None = None
                    while cursor in parents:
                        cursor = parents[cursor]
                        if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            enclosing_function = cursor.name
                            break
                    assert enclosing_function == "_read_attribute"
                assert node.func.attr not in {"read_bytes", "open", "write_text", "write_bytes"}
            elif isinstance(node.func, ast.Name):
                assert node.func.id != "open"


def test_strict_fixture_runtime_reads_only_allowlisted_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    add_complete_target(tmp_path)
    original_reader = discovery._read_attribute
    observed_paths: list[Path] = []

    def recording_reader(
        logical_entry: Path,
        resolved_entry: Path,
        attribute: str,
        allowed_attributes: frozenset[str],
        trusted_sysfs: bool,
        warnings: list[discovery.DiscoveryWarning],
    ) -> str | None:
        data_path = logical_entry / attribute
        observed_paths.append(data_path)
        assert attribute in allowed_attributes
        assert data_path.name in ALLOWED_ATTRIBUTES
        assert data_path.is_relative_to(tmp_path)
        assert trusted_sysfs is False
        return original_reader(
            logical_entry,
            resolved_entry,
            attribute,
            allowed_attributes,
            trusted_sysfs,
            warnings,
        )

    monkeypatch.setattr(discovery, "_read_attribute", recording_reader)

    assert discover_usb_devices(tmp_path).devices
    assert discovery.main(["--sysfs-root", str(tmp_path), "--json"]) == 0
    capsys.readouterr()
    assert observed_paths
    assert all(path.name != "serial" for path in observed_paths)


def test_trusted_runtime_accepts_only_regular_leaf_files_scoped_to_each_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus_root = tmp_path / "bus" / "usb" / "devices"
    devices_root = tmp_path / "devices"
    resolved_device = devices_root / "pci0000:00" / "1-2"
    resolved_interface = resolved_device / "1-2:1.0"
    bus_root.mkdir(parents=True)
    add_complete_target(resolved_device.parent)
    # Move the helper-created interface beneath the resolved device, matching real sysfs topology.
    (resolved_device.parent / "1-2:1.0").rename(resolved_interface)
    (bus_root / "1-2").symlink_to(resolved_device, target_is_directory=True)
    (bus_root / "1-2:1.0").symlink_to(resolved_interface, target_is_directory=True)
    monkeypatch.setattr(discovery, "DEFAULT_SYSFS_ROOT", bus_root.resolve())
    monkeypatch.setattr(discovery, "SYS_DEVICES_ROOT", devices_root.resolve())
    original_reader = discovery._read_attribute
    accepted_paths: list[tuple[Path, Path]] = []

    def verifying_reader(
        logical_entry: Path,
        resolved_entry: Path,
        attribute: str,
        allowed_attributes: frozenset[str],
        trusted_sysfs: bool,
        warnings: list[discovery.DiscoveryWarning],
    ) -> str | None:
        result = original_reader(
            logical_entry,
            resolved_entry,
            attribute,
            allowed_attributes,
            trusted_sysfs,
            warnings,
        )
        if result is not None:
            resolved_attribute = (logical_entry / attribute).resolve()
            accepted_paths.append((resolved_attribute, resolved_entry))
            assert not (logical_entry / attribute).is_symlink()
            assert resolved_attribute.is_file()
            assert resolved_attribute.is_relative_to(resolved_entry)
        return result

    monkeypatch.setattr(discovery, "_read_attribute", verifying_reader)

    report = discover_usb_devices(bus_root)

    assert report.devices[0].interface_selection == "unique"
    assert accepted_paths
    assert {entry for _, entry in accepted_paths} == {resolved_device, resolved_interface}


def test_importing_discovery_does_not_load_active_hardware_modules() -> None:
    forbidden_prefixes = ("streamdock_n3._vendor", "evdev", "pyudev", "gi")
    script = """
import sys
sys.path.insert(0, "src")
import streamdock_n3.discovery
print("\\n".join(sorted(sys.modules)))
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert not any(
        module_name.startswith(forbidden_prefixes) for module_name in result.stdout.splitlines()
    )
    assert "ctypes" not in result.stdout.splitlines()


def test_detection_console_script_targets_discovery_main() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["scripts"]["n3-ai-deck-detect"] == "streamdock_n3.discovery:main"


def _assert_process_succeeded(
    result: subprocess.CompletedProcess[str], action: str
) -> None:
    assert result.returncode == 0, (
        f"{action} failed: returncode={result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_fresh_wheel_contains_detection_entry_point_and_m1_modules(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "wheel"
    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(wheel_dir)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    _assert_process_succeeded(build, "fresh wheel build")

    wheels = sorted(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one fresh wheel in {wheel_dir}, found: {wheels}"

    with zipfile.ZipFile(wheels[0]) as wheel:
        entry_points = [name for name in wheel.namelist() if name.endswith(".dist-info/entry_points.txt")]
        assert len(entry_points) == 1, f"expected one entry_points.txt in {wheels[0].name}"
        assert "n3-ai-deck-detect = streamdock_n3.discovery:main" in wheel.read(
            entry_points[0]
        ).decode("utf-8")
        contents = set(wheel.namelist())
        for module in (
            "streamdock_n3/device_catalog.py",
            "streamdock_n3/discovery.py",
        ):
            assert module in contents, f"fresh wheel is missing {module}"

    venv_dir = tmp_path / "venv"
    venv = subprocess.run(
        ["uv", "venv", str(venv_dir)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    _assert_process_succeeded(venv, "venv creation")

    if sys.platform == "win32":
        python = venv_dir / "Scripts" / "python.exe"
        detector = venv_dir / "Scripts" / "n3-ai-deck-detect.exe"
    else:
        python = venv_dir / "bin" / "python"
        detector = venv_dir / "bin" / "n3-ai-deck-detect"
    install = subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--no-deps",
            "--python",
            str(python),
            str(wheels[0]),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    _assert_process_succeeded(install, "wheel install")

    help_result = subprocess.run(
        [str(detector), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    _assert_process_succeeded(help_result, "installed wheel help")
    help_output = f"{help_result.stdout}\n{help_result.stderr}".lower()
    for phrase in ("read-only", "sysfs-only", "does not confirm", "protocol compatibility"):
        assert phrase in help_output, (
            f"installed wheel help is missing {phrase!r}\n"
            f"stdout:\n{help_result.stdout}\n"
            f"stderr:\n{help_result.stderr}"
        )


def test_fresh_wheel_build_failure_includes_captured_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed_build(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout="simulated wheel stdout",
            stderr="simulated wheel stderr",
        )

    monkeypatch.setattr(subprocess, "run", failed_build)

    with pytest.raises(AssertionError) as raised:
        test_fresh_wheel_contains_detection_entry_point_and_m1_modules(tmp_path)
    message = str(raised.value)
    assert "fresh wheel build failed:" in message
    assert "returncode=1" in message
    assert "simulated wheel stdout" in message
    assert "simulated wheel stderr" in message


@pytest.mark.parametrize(
    "failure_stage",
    ("venv creation", "wheel install", "installed wheel help"),
)
def test_fresh_wheel_step_failure_includes_captured_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    original_run = subprocess.run

    def fail_selected_stage(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        command = [str(part) for part in args[0]]
        stage: str | None = None
        if command[:2] == ["uv", "venv"]:
            stage = "venv creation"
        elif command[:3] == ["uv", "pip", "install"]:
            stage = "wheel install"
        elif command[-1:] == ["--help"]:
            stage = "installed wheel help"
        if stage == failure_stage:
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=1,
                stdout=f"simulated {stage} stdout",
                stderr=f"simulated {stage} stderr",
            )
        return original_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fail_selected_stage)

    with pytest.raises(AssertionError) as raised:
        test_fresh_wheel_contains_detection_entry_point_and_m1_modules(tmp_path)
    message = str(raised.value)
    assert f"{failure_stage} failed:" in message
    assert "returncode=1" in message
    assert f"simulated {failure_stage} stdout" in message
    assert f"simulated {failure_stage} stderr" in message


def test_installed_entry_point_help_keeps_forbidden_modules_unloaded() -> None:
    script = """
import contextlib
import io
import json
import sys
from importlib.metadata import entry_points

entry_point = next(
    item for item in entry_points(group="console_scripts")
    if item.name == "n3-ai-deck-detect"
)
main = entry_point.load()
with contextlib.redirect_stdout(io.StringIO()):
    try:
        main(["--help"])
    except SystemExit as error:
        assert error.code == 0
    else:
        raise AssertionError("argparse help did not exit")
print(json.dumps(sorted(sys.modules)))
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    loaded_modules = json.loads(result.stdout)
    forbidden_prefixes = ("streamdock_n3._vendor", "evdev", "pyudev", "gi")

    assert not any(name.startswith(forbidden_prefixes) for name in loaded_modules)
    assert "ctypes" not in loaded_modules


def test_help_exits_before_scanner_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_scanner(root: Path = discovery.DEFAULT_SYSFS_ROOT) -> discovery.DiscoveryReport:
        raise AssertionError(f"scanner unexpectedly called for {root.name}")

    monkeypatch.setattr(discovery, "discover_usb_devices", forbidden_scanner)

    with pytest.raises(SystemExit) as raised:
        discovery.main(["--help"])

    assert raised.value.code == 0


def test_reader_boundary_has_exact_signature() -> None:
    annotations: dict[str, Any] = discovery._read_attribute.__annotations__

    assert tuple(annotations) == (
        "logical_entry",
        "resolved_entry",
        "attribute",
        "allowed_attributes",
        "trusted_sysfs",
        "warnings",
        "return",
    )
