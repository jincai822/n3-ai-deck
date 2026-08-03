from __future__ import annotations

import ast
import importlib
import json
import subprocess
import sys
import tomllib
import zipfile
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

G0_MODULES = (
    Path("src/streamdock_n3/hardware/__init__.py"),
    Path("src/streamdock_n3/hardware/contracts.py"),
    Path("src/streamdock_n3/hardware/gate.py"),
    Path("src/streamdock_n3/hardware/backend.py"),
    Path("src/streamdock_n3/hardware/adapter.py"),
    Path("src/streamdock_n3/hardware/ipc.py"),
    Path("src/streamdock_n3/hardware/helper_main.py"),
    Path("src/streamdock_n3/hardware/evidence.py"),
)

FORBIDDEN_SOURCE = (
    "streamdock_n3._vendor",
    "DeviceManager",
    "LibUSBHIDAPI",
    "import ctypes",
    "from ctypes",
    "import evdev",
    "import pyudev",
    "import gi",
    "os.open",
    "/dev/hidraw",
    "/dev/input",
    "udevadm",
    "systemctl",
    "setfacl",
    "sudo ",
    "shell=True",
    "subprocess.Popen",
)

G0_IMPORTS = tuple(
    f"streamdock_n3.hardware{'.' + path.stem if path.stem != '__init__' else ''}"
    for path in G0_MODULES
)
FORBIDDEN_RUNTIME_MODULES = (
    "streamdock_n3._vendor",
    "ctypes",
    "evdev",
    "pyudev",
    "gi",
)
FORBIDDEN_FILE_METHODS = {
    "open",
    "read_bytes",
    "write_bytes",
    "read_text",
    "write_text",
    "unlink",
    "chmod",
    "chown",
}


def _source(path: Path) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _trees() -> Iterator[tuple[Path, ast.Module]]:
    for path in G0_MODULES:
        yield path, ast.parse(_source(path), filename=str(path))


def _project_import_allowed(module: str) -> bool:
    return module == "streamdock_n3.device_catalog" or module.startswith(
        "streamdock_n3.hardware"
    )


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((item.value for item in call.keywords if item.arg == name), None)


def _literal(value: ast.expr | None, expected: object) -> bool:
    return isinstance(value, ast.Constant) and value.value == expected


def _forbidden_runtime_modules(names: Sequence[str]) -> list[str]:
    return sorted(
        name
        for name in names
        if any(name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN_RUNTIME_MODULES)
    )


def _run_checked(command: Sequence[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )
    assert completed.returncode == 0, (
        f"command failed ({completed.returncode}): {' '.join(command)}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    return completed


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("g0-wheel")
    _run_checked(("uv", "build", "--wheel", "--out-dir", str(output)))
    wheels = tuple(output.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def test_g0_sources_contain_no_forbidden_hardware_or_system_strings() -> None:
    violations = [
        f"{path}: {forbidden}"
        for path in G0_MODULES
        for forbidden in FORBIDDEN_SOURCE
        if forbidden in _source(path)
    ]

    assert violations == []


def test_g0_imports_stay_inside_the_safe_dependency_closure() -> None:
    violations: list[str] = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            imported: tuple[str, ...]
            if isinstance(node, ast.Import):
                imported = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported = (node.module or "",)
            else:
                continue
            for module in imported:
                if module.startswith("streamdock_n3") and not _project_import_allowed(module):
                    violations.append(f"{path}:{node.lineno}: project import {module}")
                if module == "subprocess" and path.name != "ipc.py":
                    violations.append(f"{path}:{node.lineno}: subprocess import")

    assert violations == []


def test_g0_calls_cannot_open_files_or_invoke_process_functions() -> None:
    violations: list[str] = []
    for path, tree in _trees():
        subprocess_modules: set[str] = set()
        subprocess_functions: dict[str, str] = {}
        builtins_modules: set[str] = {"builtins"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "subprocess":
                        subprocess_modules.add(alias.asname or alias.name)
                    if alias.name == "builtins":
                        builtins_modules.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
                subprocess_functions.update(
                    {alias.asname or alias.name: alias.name for alias in node.names}
                )

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if isinstance(function, ast.Name) and function.id == "open":
                violations.append(f"{path}:{node.lineno}: builtin open")
            if isinstance(function, ast.Attribute):
                if function.attr in FORBIDDEN_FILE_METHODS:
                    violations.append(f"{path}:{node.lineno}: file method {function.attr}")
                if (
                    function.attr == "open"
                    and isinstance(function.value, ast.Name)
                    and function.value.id in builtins_modules
                ):
                    violations.append(f"{path}:{node.lineno}: builtins.open")
                if (
                    isinstance(function.value, ast.Name)
                    and function.value.id in subprocess_modules
                    and (function.attr != "run" or path.name != "ipc.py")
                ):
                    violations.append(
                        f"{path}:{node.lineno}: subprocess function {function.attr}"
                    )
            elif isinstance(function, ast.Name) and function.id in subprocess_functions:
                imported_name = subprocess_functions[function.id]
                if imported_name != "run" or path.name != "ipc.py":
                    violations.append(
                        f"{path}:{node.lineno}: subprocess function {imported_name}"
                    )

    assert violations == []


def test_only_subprocess_run_is_the_fixed_fake_helper_boundary() -> None:
    run_calls: list[tuple[Path, ast.Call]] = []
    ipc_tree: ast.Module | None = None
    for path, tree in _trees():
        if path.name == "ipc.py":
            ipc_tree = tree
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"
                and node.func.attr == "run"
            ):
                run_calls.append((path, node))

    assert ipc_tree is not None
    assert len(run_calls) == 1
    path, call = run_calls[0]
    assert path.name == "ipc.py"

    assignments = {
        target.id: node.value
        for node in ast.walk(ipc_tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    helper_module = assignments.get("HELPER_MODULE")
    argv = assignments.get("argv")
    assert _literal(helper_module, "streamdock_n3.hardware.helper_main")
    assert isinstance(argv, ast.List)
    assert len(argv.elts) == 3
    assert (
        isinstance(argv.elts[0], ast.Attribute)
        and isinstance(argv.elts[0].value, ast.Name)
        and argv.elts[0].value.id == "sys"
        and argv.elts[0].attr == "executable"
    )
    assert _literal(argv.elts[1], "-m")
    assert isinstance(argv.elts[2], ast.Name) and argv.elts[2].id == "HELPER_MODULE"
    assert len(call.args) == 1
    assert isinstance(call.args[0], ast.Name) and call.args[0].id == "argv"
    assert _keyword(call, "input") is not None
    assert _literal(_keyword(call, "capture_output"), True)
    assert _literal(_keyword(call, "text"), True)
    assert _literal(_keyword(call, "encoding"), "utf-8")
    assert _literal(_keyword(call, "errors"), "strict")
    assert _keyword(call, "timeout") is not None
    assert _literal(_keyword(call, "check"), False)
    assert _keyword(call, "shell") is None


def test_fresh_source_imports_do_not_load_forbidden_runtime_modules() -> None:
    program = (
        "import importlib,json,sys;"
        f"mods={G0_IMPORTS!r};"
        "[importlib.import_module(name) for name in mods];"
        "print(json.dumps(sorted(sys.modules)))"
    )
    completed = _run_checked((sys.executable, "-c", program))
    loaded = json.loads(completed.stdout)

    assert isinstance(loaded, list)
    assert _forbidden_runtime_modules(loaded) == []


def test_import_and_construction_are_inert_until_fake_helper_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs))
        ipc = importlib.import_module("streamdock_n3.hardware.ipc")
        contracts = importlib.import_module("streamdock_n3.hardware.contracts")
        result = contracts.OperationResult(
            contracts.ResultStatus.SUCCEEDED,
            contracts.ErrorCode.NONE,
            0,
        )
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=ipc.encode_response(result) + "\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    modules = {name: importlib.import_module(name) for name in G0_IMPORTS}
    assert calls == []

    contracts = modules["streamdock_n3.hardware.contracts"]
    gate = modules["streamdock_n3.hardware.gate"]
    backend = modules["streamdock_n3.hardware.backend"]
    adapter = modules["streamdock_n3.hardware.adapter"]
    ipc = modules["streamdock_n3.hardware.ipc"]
    evidence = modules["streamdock_n3.hardware.evidence"]

    stage = contracts.Stage(contracts.Stage.G1_PROFILE.value)
    state = contracts.AdapterState(contracts.AdapterState.CANDIDATE.value)
    operation = contracts.Operation(contracts.Operation.APPROVE_PROFILE.value)
    input_kind = contracts.InputKind(contracts.InputKind.BUTTON.value)
    input_action = contracts.InputAction(contracts.InputAction.PRESS.value)
    result_status = contracts.ResultStatus(contracts.ResultStatus.SUCCEEDED.value)
    error_code = contracts.ErrorCode(contracts.ErrorCode.NONE.value)
    recovery_status = contracts.RecoveryStatus(contracts.RecoveryStatus.NOT_REQUIRED.value)
    interface = contracts.HidInterface(0, 3, 0, 0)
    profile = contracts.DeviceProfile(
        0x6602,
        0x1000,
        0x0300,
        interface,
        contracts.IdentityStatus.USER_REPORTED_CANDIDATE,
        contracts.ProtocolStatus.UNVALIDATED,
        "0123456789abcdef",
    )
    command = contracts.AdapterCommand(operation)
    rule = contracts.CommandRule(operation, 1, 1)
    manifest = contracts.StageManifest(
        stage,
        "0123456789abcdef",
        profile.digest(),
        interface,
        (rule,),
        5_000,
        "g1-validated",
        "g1-recovery",
        "test:g1",
    )
    event = contracts.NormalizedInputEvent(input_kind, 1, input_action, 0)
    result = contracts.OperationResult(result_status, error_code, 0)
    backend_call = backend.BackendCall(operation, None, None, None, 0)
    fake_backend = backend.FakeBackend(events=(event,))
    recorder = evidence.EvidenceRecorder()
    capability_gate = gate.CapabilityGate()
    stage_session = gate.StageSession(manifest, [0])
    gate_violation = gate.GateViolation(contracts.ErrorCode.STATE_NOT_ALLOWED)
    n3_adapter = adapter.N3Adapter(profile, "0123456789abcdef", fake_backend, evidence=recorder)
    request = ipc.IpcRequest(profile, state, manifest, command)
    evidence_kind = evidence.EvidenceKind(evidence.EvidenceKind.OPERATION.value)
    evidence_record = evidence.EvidenceRecord(
        contracts.SCHEMA_VERSION,
        evidence_kind,
        stage,
        "0123456789abcdef",
        profile.digest(),
        interface,
        operation,
        None,
        None,
        0,
        result_status,
        error_code,
        0,
        0,
        "g1-validated",
        "g1-recovery",
        "test:g1",
        None,
        None,
    )
    constructed = {
        type(value).__name__
        for value in (
            stage,
            state,
            operation,
            input_kind,
            input_action,
            result_status,
            error_code,
            recovery_status,
            interface,
            profile,
            command,
            rule,
            manifest,
            event,
            result,
            gate_violation,
            stage_session,
            capability_gate,
            backend_call,
            fake_backend,
            n3_adapter,
            request,
            evidence_kind,
            evidence_record,
            recorder,
        )
    }
    declared = {
        node.name
        for _path, tree in _trees()
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }
    assert declared - {"Backend", "EvidenceSink"} == constructed
    assert calls == []

    helper_result = ipc.run_fake_helper(request, timeout_ms=1_000)

    assert helper_result.succeeded is True
    assert len(calls) == 1


def test_candidate_usb_id_is_not_activated_or_granted_a_udev_rule() -> None:
    product_ids = _source(Path("src/streamdock_n3/_vendor/StreamDock/ProductIDs.py"))
    active_mappings = [line.split("#", 1)[0] for line in product_ids.splitlines()]
    assert not any(
        "USB_VIDN3E" in line and "USB_PID_STREAMDOCK_N1EN" in line
        for line in active_mappings
    )

    udev_rules = _source(Path("src/streamdock_n3/_data/99-streamdock.rules"))
    active_rules = [line.split("#", 1)[0] for line in udev_rules.splitlines()]
    assert not any("6602" in line for line in active_rules)


def test_fresh_wheel_contains_every_g0_module(built_wheel: Path) -> None:
    expected = {
        str(path.relative_to("src")).replace("\\", "/")
        for path in G0_MODULES
    }
    with zipfile.ZipFile(built_wheel) as archive:
        packaged = set(archive.namelist())

    assert expected <= packaged


def test_wheel_install_imports_remain_free_of_forbidden_runtime_modules(
    built_wheel: Path,
    tmp_path: Path,
) -> None:
    venv = tmp_path / "venv"
    _run_checked(("uv", "venv", "--python", sys.executable, str(venv)))
    python = venv / "bin" / "python"
    _run_checked(
        (
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            str(built_wheel),
        )
    )
    program = (
        "import importlib,json,sys;"
        f"mods={G0_IMPORTS!r};"
        "[importlib.import_module(name) for name in mods];"
        "print(json.dumps(sorted(sys.modules)))"
    )
    completed = _run_checked((str(python), "-I", "-c", program), cwd=tmp_path)
    loaded = json.loads(completed.stdout)

    assert isinstance(loaded, list)
    assert _forbidden_runtime_modules(loaded) == []


def test_project_scripts_do_not_expose_the_hardware_package() -> None:
    project = tomllib.loads(_source(Path("pyproject.toml")))["project"]
    scripts = project.get("scripts", {})

    assert isinstance(scripts, dict)
    assert not any(
        isinstance(target, str) and target.startswith("streamdock_n3.hardware")
        for target in scripts.values()
    )
