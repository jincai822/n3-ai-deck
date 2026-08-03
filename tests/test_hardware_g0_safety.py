from __future__ import annotations

import ast
import importlib
import json
import re
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
    return module == "streamdock_n3.device_catalog" or (
        module == "streamdock_n3.hardware" or module.startswith("streamdock_n3.hardware.")
    )


def _module_name(path: Path) -> str:
    relative = path.relative_to("src").with_suffix("")
    parts = relative.parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _from_base(path: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    module = _module_name(path)
    package = module if path.stem == "__init__" else module.rpartition(".")[0]
    package_parts = package.split(".") if package else []
    retained = len(package_parts) - node.level + 1
    if retained < 0:
        return ""
    parts = package_parts[:retained]
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


def _import_targets(path: Path, node: ast.Import | ast.ImportFrom) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    base = _from_base(path, node)
    targets: list[str] = []
    for alias in node.names:
        candidate = base if alias.name == "*" else ".".join(filter(None, (base, alias.name)))
        # A from-import names a symbol when its source module is already allowlisted;
        # otherwise the alias is needed to resolve imports from a parent package.
        targets.append(base if _project_import_allowed(base) else candidate)
    return tuple(targets)


def _canonical_import_bindings(path: Path, tree: ast.Module) -> dict[str, set[str]]:
    bindings: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".", 1)[0]
                bindings.setdefault(local_name, set()).add(
                    alias.name if alias.asname else local_name
                )
        elif isinstance(node, ast.ImportFrom):
            base = _from_base(path, node)
            for alias in node.names:
                if alias.name != "*":
                    bindings.setdefault(alias.asname or alias.name, set()).add(
                        ".".join(filter(None, (base, alias.name)))
                    )
    return bindings


def _canonical_names(expression: ast.expr, bindings: dict[str, set[str]]) -> set[str]:
    if isinstance(expression, ast.Name):
        if expression.id == "open":
            return {"builtins.open"} | bindings.get(expression.id, set())
        return bindings.get(expression.id, set())
    if isinstance(expression, ast.Attribute):
        return {
            f"{base}.{expression.attr}" for base in _canonical_names(expression.value, bindings)
        }
    if isinstance(expression, ast.Call):
        return {f"{called}()" for called in _canonical_names(expression.func, bindings)}
    return set()


def _import_violations(path: Path, tree: ast.Module) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for module in _import_targets(path, node):
            if (
                module == "streamdock_n3" or module.startswith("streamdock_n3.")
            ) and not _project_import_allowed(module):
                violations.append(f"{path}:{node.lineno}: project import {module}")
        if (
            any(
                canonical == "subprocess" or canonical.startswith("subprocess.")
                for canonical_names in _canonical_import_bindings(
                    path, ast.Module(body=[node], type_ignores=[])
                ).values()
                for canonical in canonical_names
            )
            and path.name != "ipc.py"
        ):
            violations.append(f"{path}:{node.lineno}: subprocess import")
    return violations


def _canonical_calls(path: Path, tree: ast.Module) -> list[tuple[ast.Call, set[str]]]:
    bindings = _canonical_import_bindings(path, tree)
    return [
        (node, _canonical_names(node.func, bindings))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]


def _call_violations(path: Path, tree: ast.Module) -> list[str]:
    violations: list[str] = []
    for call, canonical_names in _canonical_calls(path, tree):
        function = call.func
        # Intentional conservative policy: any method with a file-mutating/opening
        # name is rejected even when static analysis cannot prove its receiver type.
        if isinstance(function, ast.Attribute) and function.attr in FORBIDDEN_FILE_METHODS:
            violations.append(f"{path}:{call.lineno}: conservative file method {function.attr}")
        else:
            file_functions = canonical_names & {"builtins.open", "os.open"}
            if file_functions:
                violations.append(
                    f"{path}:{call.lineno}: file function {sorted(file_functions)[0]}"
                )
        subprocess_functions = {name for name in canonical_names if name.startswith("subprocess.")}
        if subprocess_functions and (
            subprocess_functions != {"subprocess.run"} or path.name != "ipc.py"
        ):
            violations.append(
                f"{path}:{call.lineno}: subprocess function "
                f"{', '.join(sorted(subprocess_functions))}"
            )
    return violations


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((item.value for item in call.keywords if item.arg == name), None)


def _literal(value: ast.expr | None, expected: object) -> bool:
    return isinstance(value, ast.Constant) and value.value == expected


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _enclosing_function(
    call: ast.Call, parents: dict[ast.AST, ast.AST]
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    current: ast.AST = call
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
    return None


def _scope_nodes(
    scope: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterator[ast.AST]:
    pending: list[ast.AST] = list(reversed(scope.body))
    while pending:
        node = pending.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        pending.extend(reversed(tuple(ast.iter_child_nodes(node))))


def _fixed_argv_value(
    tree: ast.Module,
    call: ast.Call,
    bindings: dict[str, set[str]],
) -> ast.expr | None:
    if len(call.args) != 1 or not isinstance(call.args[0], ast.Name):
        return None
    argv_name = call.args[0].id
    parents = _parent_map(tree)
    scope = _enclosing_function(call, parents)
    if scope is None:
        return None
    stores = [
        node
        for node in _scope_nodes(scope)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == argv_name
    ]
    if len(stores) != 1:
        return None
    assignment = parents.get(stores[0])
    if not isinstance(assignment, (ast.Assign, ast.AnnAssign)):
        return None
    value = assignment.value
    if value is None or parents.get(assignment) is not scope:
        return None
    top_statement: ast.AST = call
    while parents.get(top_statement) is not scope:
        parent = parents.get(top_statement)
        if parent is None:
            return None
        top_statement = parent
    if not isinstance(top_statement, ast.stmt):
        return None
    if scope.body.index(assignment) >= scope.body.index(top_statement):
        return None
    if not isinstance(value, ast.List) or len(value.elts) != 3:
        return None
    if _canonical_names(value.elts[0], bindings) != {"sys.executable"}:
        return None
    if not _literal(value.elts[1], "-m"):
        return None
    if not isinstance(value.elts[2], ast.Name) or value.elts[2].id != "HELPER_MODULE":
        return None
    return value


def _fixed_helper_violations(trees: Sequence[tuple[Path, ast.Module]]) -> list[str]:
    violations: list[str] = []
    subprocess_calls = [
        (path, tree, call)
        for path, tree in trees
        for call, canonical_names in _canonical_calls(path, tree)
        if any(name.startswith("subprocess.") for name in canonical_names)
    ]
    if len(subprocess_calls) != 1:
        return [f"G0 closure has {len(subprocess_calls)} subprocess calls, expected exactly one"]
    path, tree, call = subprocess_calls[0]
    bindings = _canonical_import_bindings(path, tree)
    subprocess_names = {
        name for name in _canonical_names(call.func, bindings) if name.startswith("subprocess.")
    }
    if path.name != "ipc.py" or subprocess_names != {"subprocess.run"}:
        violations.append(f"{path}:{call.lineno}: only ipc.py subprocess.run is allowed")

    helper_assignments = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "HELPER_MODULE" for target in node.targets
        )
    ]
    if len(helper_assignments) != 1 or not _literal(
        helper_assignments[0] if helper_assignments else None,
        "streamdock_n3.hardware.helper_main",
    ):
        violations.append("HELPER_MODULE must have one literal module-scope definition")
    if _fixed_argv_value(tree, call, bindings) is None:
        violations.append(
            f"{path}:{call.lineno}: argv lacks one safe reaching definition in the call's function"
        )

    keyword_names = [keyword.arg for keyword in call.keywords]
    expected_keywords = {
        "input",
        "capture_output",
        "text",
        "encoding",
        "errors",
        "check",
        "timeout",
    }
    if None in keyword_names:
        violations.append(f"{path}:{call.lineno}: subprocess kwargs expansion is forbidden")
    if set(keyword_names) != expected_keywords:
        violations.append(f"{path}:{call.lineno}: subprocess keyword set is not closed")
    if _keyword(call, "input") is None:
        violations.append(f"{path}:{call.lineno}: subprocess input is required")
    for name, expected in (
        ("capture_output", True),
        ("text", True),
        ("encoding", "utf-8"),
        ("errors", "strict"),
        ("check", False),
    ):
        if not _literal(_keyword(call, name), expected):
            violations.append(f"{path}:{call.lineno}: invalid subprocess {name}")
    if _keyword(call, "timeout") is None:
        violations.append(f"{path}:{call.lineno}: subprocess timeout is required")
    if _keyword(call, "shell") is not None:
        violations.append(f"{path}:{call.lineno}: subprocess shell is forbidden")
    return violations


def _expression_names(expression: ast.AST) -> set[str]:
    return {
        node.attr if isinstance(node, ast.Attribute) else node.id
        for node in ast.walk(expression)
        if isinstance(node, (ast.Attribute, ast.Name))
    }


def _candidate_product_mapping_violations(source: str) -> list[int]:
    tree = ast.parse(source, filename="ProductIDs.py")
    mappings: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(
                isinstance(target, ast.Name) and target.id == "g_products" for target in targets
            ):
                value = node.value
                if isinstance(value, (ast.List, ast.Tuple)):
                    mappings.extend(value.elts)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "g_products"
            and node.func.attr == "append"
            and len(node.args) == 1
        ):
            mappings.append(node.args[0])
    return [
        mapping.lineno
        for mapping in mappings
        if isinstance(mapping, (ast.Tuple, ast.List))
        and {"USB_VIDN3E", "USB_PID_STREAMDOCK_N1EN"} <= _expression_names(mapping)
    ]


UDEV_CANDIDATE_VENDOR = re.compile(
    r"(?:ATTR|ATTRS)\s*\{\s*idVendor\s*\}\s*==\s*[\"']6602[\"']",
    re.IGNORECASE,
)


def _candidate_udev_rule_violations(source: str) -> list[int]:
    return [
        lineno
        for lineno, line in enumerate(source.splitlines(), start=1)
        if UDEV_CANDIDATE_VENDOR.search(line.split("#", 1)[0])
    ]


def _forbidden_runtime_modules(names: Sequence[str]) -> list[str]:
    return sorted(
        name
        for name in names
        if any(
            name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN_RUNTIME_MODULES
        )
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
    violations = [
        violation for path, tree in _trees() for violation in _import_violations(path, tree)
    ]

    assert violations == []


def test_g0_calls_cannot_open_files_or_invoke_process_functions() -> None:
    violations = [
        violation for path, tree in _trees() for violation in _call_violations(path, tree)
    ]

    assert violations == []


def test_only_subprocess_run_is_the_fixed_fake_helper_boundary() -> None:
    violations = _fixed_helper_violations(tuple(_trees()))

    assert violations == []


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
    assert _candidate_product_mapping_violations(product_ids) == []

    udev_rules = _source(Path("src/streamdock_n3/_data/99-streamdock.rules"))
    assert _candidate_udev_rule_violations(udev_rules) == []


def test_fresh_wheel_contains_every_g0_module(built_wheel: Path) -> None:
    expected = {str(path.relative_to("src")).replace("\\", "/") for path in G0_MODULES}
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


@pytest.mark.parametrize(
    ("source", "filename"),
    (
        ("from .. import config\n", "src/streamdock_n3/hardware/ipc.py"),
        ("import streamdock_n3.hardwarex\n", "src/streamdock_n3/hardware/ipc.py"),
    ),
)
def test_import_gate_rejects_resolved_project_import_bypasses(
    source: str,
    filename: str,
) -> None:
    path = Path(filename)
    tree = ast.parse(source, filename=filename)

    assert _import_violations(path, tree) != []


@pytest.mark.parametrize(
    "source",
    (
        "from . import contracts\n",
        "from .contracts import Stage\n",
        "from streamdock_n3 import device_catalog\n",
        "from streamdock_n3.device_catalog import DEVICE_CATALOG\n",
    ),
)
def test_import_gate_accepts_resolved_allowlisted_imports(source: str) -> None:
    path = Path("src/streamdock_n3/hardware/ipc.py")

    assert _import_violations(path, ast.parse(source, filename=str(path))) == []


def test_subprocess_gate_counts_alias_calls_across_the_complete_closure() -> None:
    ipc_path = Path("src/streamdock_n3/hardware/ipc.py")
    ipc_tree = ast.parse(
        """
import subprocess
from subprocess import run as extra_run
import sys
HELPER_MODULE = "streamdock_n3.hardware.helper_main"
def invoke(payload, timeout):
    argv = [sys.executable, "-m", HELPER_MODULE]
    subprocess.run(argv, input=payload, capture_output=True, text=True,
                   encoding="utf-8", errors="strict", check=False, timeout=timeout)
    extra_run(argv)
""",
        filename=str(ipc_path),
    )
    assert _fixed_helper_violations(((ipc_path, ipc_tree),)) != []


@pytest.mark.parametrize(
    "source",
    (
        "import subprocess as sp\nsp.run([])\n",
        "from subprocess import run as execute\nexecute([])\n",
        "from subprocess import Popen as launch\nlaunch([])\n",
    ),
)
def test_call_gate_rejects_canonical_subprocess_aliases_outside_ipc(source: str) -> None:
    path = Path("src/streamdock_n3/hardware/backend.py")

    assert _call_violations(path, ast.parse(source, filename=str(path))) != []


def test_call_gate_cannot_lose_provenance_to_a_decoy_import_in_another_scope() -> None:
    path = Path("src/streamdock_n3/hardware/backend.py")
    tree = ast.parse(
        """
import subprocess as process
def unsafe():
    process.Popen([])
def decoy():
    import harmless as process
""",
        filename=str(path),
    )

    assert _call_violations(path, tree) != []


@pytest.mark.parametrize(
    "source",
    (
        "from builtins import open as fopen\nfopen('/tmp/unsafe')\n",
        "import os as operating\noperating.open('/tmp/unsafe', 0)\n",
        "from os import open as oopen\noopen('/tmp/unsafe', 0)\n",
        "import pathlib as paths\npaths.Path('/tmp/unsafe').read_text()\n",
    ),
)
def test_call_gate_rejects_canonical_file_api_aliases(
    source: str,
) -> None:
    path = Path("src/streamdock_n3/hardware/backend.py")
    tree = ast.parse(source, filename=str(path))

    assert _call_violations(path, tree) != []


@pytest.mark.parametrize(
    "mutation",
    (
        "options = {'shell': True}\n    argv = [sys.executable, '-m', HELPER_MODULE]\n    ",
        "argv = ['/bin/unsafe']\n    ",
    ),
)
def test_fixed_helper_gate_rejects_kwargs_and_decoy_argv_bypasses(
    mutation: str,
) -> None:
    if mutation.startswith("options"):
        setup = mutation
        extra_keywords = ", **options"
        trailing = ""
    else:
        setup = mutation
        extra_keywords = ""
        trailing = '\n    argv = [sys.executable, "-m", HELPER_MODULE]'
    path = Path("src/streamdock_n3/hardware/ipc.py")
    tree = ast.parse(
        f"""
import subprocess
import sys
HELPER_MODULE = "streamdock_n3.hardware.helper_main"
def invoke(payload, timeout):
    {setup}completed = subprocess.run(
        argv, input=payload, capture_output=True, text=True, encoding="utf-8",
        errors="strict", check=False, timeout=timeout{extra_keywords}){trailing}
    return completed
""",
        filename=str(path),
    )
    assert _fixed_helper_violations(((path, tree),)) != []


def test_candidate_mapping_gate_rejects_multiline_active_tuple() -> None:
    product_ids = """
g_products = [
    (
        USB_VIDN3E,
        USB_PID_STREAMDOCK_N1EN,
        Device,
    ),
]
"""
    assert _candidate_product_mapping_violations(product_ids) != []


@pytest.mark.parametrize(
    "source",
    (
        "g_products = [(USB_VIDN3E, USB_PID_STREAMDOCK_N1EN, Device)]\n",
        "g_products = ((USB_VIDN3E, USB_PID_STREAMDOCK_N1EN, Device),)\n",
        "g_products = []\ng_products.append([USB_VIDN3E, USB_PID_STREAMDOCK_N1EN, Device])\n",
    ),
)
def test_candidate_mapping_gate_checks_list_tuple_and_append_mappings(source: str) -> None:
    assert _candidate_product_mapping_violations(source) != []


def test_udev_gate_ignores_comments_and_unrelated_6602_values() -> None:
    udev_rules = """
# ATTR{idVendor}=="6602" remains intentionally unsupported
ENV{DOCUMENTED_USB_ID}=="6602", TAG+="uaccess"
ATTR{idProduct}=="6602", TAG+="uaccess"
"""

    assert _candidate_udev_rule_violations(udev_rules) == []


@pytest.mark.parametrize(
    "rule",
    (
        'SUBSYSTEM=="usb", ATTR{idVendor}=="6602", MODE="0666"\n',
        'SUBSYSTEM=="hidraw", ATTRS { idVendor } == "6602", TAG+="uaccess"\n',
    ),
)
def test_udev_gate_rejects_active_candidate_vendor_target_rules(rule: str) -> None:
    assert _candidate_udev_rule_violations(rule) != []
