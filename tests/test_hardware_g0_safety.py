from __future__ import annotations

import ast
import fnmatch
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
ALLOWED_STDLIB_IMPORTS = {
    "__future__",
    "base64",
    "binascii",
    "collections.abc",
    "dataclasses",
    "enum",
    "hashlib",
    "json",
    "re",
    "subprocess",
    "sys",
    "types",
    "typing",
}
ALLOWED_PROJECT_IMPORTS = {
    "streamdock_n3.device_catalog",
    *G0_IMPORTS,
}
DYNAMIC_RESOLUTION_CALLS = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "getattr",
    "globals",
    "import_module",
    "locals",
    "setattr",
    "vars",
}


def _source(path: Path) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _trees() -> Iterator[tuple[Path, ast.Module]]:
    for path in G0_MODULES:
        yield path, ast.parse(_source(path), filename=str(path))


def _project_import_allowed(module: str) -> bool:
    return module in ALLOWED_PROJECT_IMPORTS


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
        candidate = ".".join(filter(None, (base, alias.name)))
        targets.append(
            base
            if base in ALLOWED_STDLIB_IMPORTS or _project_import_allowed(base)
            else candidate
        )
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
        if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
            violations.append(f"{path}:{node.lineno}: star import")
        targets = _import_targets(path, node)
        for module in targets:
            if module not in ALLOWED_STDLIB_IMPORTS and not _project_import_allowed(module):
                violations.append(f"{path}:{node.lineno}: import outside closed allowlist: {module}")
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
    bindings = _canonical_import_bindings(path, tree)
    imported_names = set(bindings)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if node.id in imported_names:
                violations.append(f"{path}:{node.lineno}: imported binding mutation {node.id}")
        elif isinstance(node, ast.arg) and node.arg in imported_names:
            violations.append(f"{path}:{node.lineno}: imported binding shadow {node.arg}")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            mutated = imported_names.intersection(node.names)
            if mutated:
                violations.append(
                    f"{path}:{node.lineno}: imported binding scope mutation {sorted(mutated)[0]}"
                )
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and isinstance(
            node.value, (ast.Name, ast.Attribute)
        ):
            value = node.value
            canonical_values = _canonical_names(value, bindings)
            if (
                isinstance(value, ast.Name)
                and value.id in DYNAMIC_RESOLUTION_CALLS
                or isinstance(value, ast.Attribute)
                and value.attr == "import_module"
                or any(
                    name == "builtins.open"
                    or name == "os.open"
                    or name == "subprocess"
                    or name.startswith("subprocess.")
                    for name in canonical_values
                )
            ):
                violations.append(f"{path}:{node.lineno}: dangerous assignment alias")
    for call, canonical_names in _canonical_calls(path, tree):
        function = call.func
        lexical_name = function.id if isinstance(function, ast.Name) else ""
        if lexical_name in DYNAMIC_RESOLUTION_CALLS or (
            isinstance(function, ast.Attribute) and function.attr == "import_module"
        ):
            lexical_name = lexical_name or function.attr
            violations.append(f"{path}:{call.lineno}: dynamic resolution call {lexical_name}")
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


def _fixed_argv(call: ast.Call, bindings: dict[str, set[str]]) -> bool:
    if len(call.args) != 1 or not isinstance(call.args[0], (ast.List, ast.Tuple)):
        return False
    value = call.args[0]
    return (
        len(value.elts) == 3
        and _canonical_names(value.elts[0], bindings) == {"sys.executable"}
        and _literal(value.elts[1], "-m")
        and isinstance(value.elts[2], ast.Name)
        and value.elts[2].id == "HELPER_MODULE"
    )


def _single_exact_import(tree: ast.Module, module: str) -> bool:
    matching = [
        alias
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if (alias.asname or alias.name.split(".", 1)[0]) == module
    ]
    return len(matching) == 1 and matching[0].name == module and matching[0].asname is None


def _symbol_is_immutable(
    tree: ast.Module,
    symbol: str,
    *,
    allowed_store: ast.Name | None = None,
) -> bool:
    for node in ast.walk(tree):
        if (
            (
                isinstance(node, ast.Name)
                and isinstance(node.ctx, (ast.Store, ast.Del))
                and node.id == symbol
                and node is not allowed_store
            )
            or (isinstance(node, ast.arg) and node.arg == symbol)
            or (isinstance(node, (ast.Global, ast.Nonlocal)) and symbol in node.names)
            or (
                isinstance(node, ast.Attribute)
                and isinstance(node.ctx, (ast.Store, ast.Del))
                and isinstance(node.value, ast.Name)
                and node.value.id == symbol
            )
        ):
            return False
    return True


def _bounded_timeout(value: ast.expr | None) -> bool:
    return (
        isinstance(value, ast.BinOp)
        and isinstance(value.op, ast.Div)
        and isinstance(value.left, ast.Name)
        and value.left.id == "timeout_ms"
        and _literal(value.right, 1000)
    )


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
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "HELPER_MODULE"
    ]
    helper_assignment = helper_assignments[0] if len(helper_assignments) == 1 else None
    helper_store = helper_assignment.targets[0] if helper_assignment is not None else None
    if (
        helper_assignment is None
        or not _literal(helper_assignment.value, "streamdock_n3.hardware.helper_main")
        or not _symbol_is_immutable(tree, "HELPER_MODULE", allowed_store=helper_store)
    ):
        violations.append("HELPER_MODULE must have one literal module-scope definition")
    if not _single_exact_import(tree, "sys") or not _symbol_is_immutable(tree, "sys"):
        violations.append("sys must be one immutable exact import")
    if not _single_exact_import(tree, "subprocess") or not _symbol_is_immutable(
        tree, "subprocess"
    ):
        violations.append("subprocess must be one immutable exact import")
    if not _fixed_argv(call, bindings):
        violations.append(f"{path}:{call.lineno}: argv must be the direct exact fixed sequence")

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
    if not _bounded_timeout(_keyword(call, "timeout")):
        violations.append(f"{path}:{call.lineno}: subprocess timeout must be timeout_ms / 1000")
    if _keyword(call, "shell") is not None:
        violations.append(f"{path}:{call.lineno}: subprocess shell is forbidden")
    return violations


def _simple_bindings(tree: ast.Module) -> dict[str, ast.expr | None]:
    bindings: dict[str, ast.expr | None] = {}

    def bind(name: str, value: ast.expr) -> None:
        bindings[name] = value if name not in bindings else None

    for statement in tree.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if statement.value is not None:
                for target in targets:
                    if isinstance(target, ast.Name) and target.id != "g_products":
                        bind(target.id, statement.value)
        elif isinstance(statement, ast.ClassDef):
            for member in statement.body:
                if isinstance(member, (ast.Assign, ast.AnnAssign)):
                    targets = member.targets if isinstance(member, ast.Assign) else [member.target]
                    if member.value is not None:
                        for target in targets:
                            if isinstance(target, ast.Name):
                                bind(f"{statement.name}.{target.id}", member.value)
    return bindings


def _qualified_name(expression: ast.expr) -> str | None:
    if isinstance(expression, ast.Name):
        return expression.id
    if isinstance(expression, ast.Attribute):
        base = _qualified_name(expression.value)
        return f"{base}.{expression.attr}" if base is not None else None
    return None


def _resolved_int(
    expression: ast.expr,
    bindings: dict[str, ast.expr | None],
    seen: frozenset[str] = frozenset(),
) -> int | None:
    if isinstance(expression, ast.Constant) and isinstance(expression.value, int) and not isinstance(
        expression.value, bool
    ):
        return expression.value
    name = _qualified_name(expression)
    if name is None or name in seen:
        return None
    value = bindings.get(name)
    if value is None:
        return None
    return _resolved_int(value, bindings, seen | {name})


def _collection_entries(
    expression: ast.expr,
    bindings: dict[str, ast.expr | None],
    seen: frozenset[str] = frozenset(),
) -> list[ast.expr] | None:
    name = _qualified_name(expression)
    if name is not None and not isinstance(expression, (ast.List, ast.Tuple)):
        if name in seen or bindings.get(name) is None:
            return None
        value = bindings[name]
        assert value is not None
        return _collection_entries(value, bindings, seen | {name})
    if not isinstance(expression, (ast.List, ast.Tuple)):
        return None
    entries: list[ast.expr] = []
    for item in expression.elts:
        if isinstance(item, ast.Starred):
            expanded = _collection_entries(item.value, bindings, seen)
            if expanded is None:
                return None
            entries.extend(expanded)
        else:
            entries.append(item)
    return entries


def _entry_is_candidate(
    expression: ast.expr,
    bindings: dict[str, ast.expr | None],
) -> bool | None:
    name = _qualified_name(expression)
    if name is not None and not isinstance(expression, (ast.List, ast.Tuple)):
        value = bindings.get(name)
        if value is None:
            return None
        return _entry_is_candidate(value, bindings)
    if not isinstance(expression, (ast.List, ast.Tuple)) or len(expression.elts) < 2:
        return None
    vid = _resolved_int(expression.elts[0], bindings)
    pid = _resolved_int(expression.elts[1], bindings)
    if vid is None or pid is None:
        return None
    return (vid, pid) == (0x6602, 0x1000)


def _target_uses_alias(target: ast.expr, aliases: set[str]) -> bool:
    if isinstance(target, ast.Name):
        return target.id in aliases
    if isinstance(target, ast.Subscript):
        return isinstance(target.value, ast.Name) and target.value.id in aliases
    if isinstance(target, (ast.List, ast.Tuple)):
        return any(_target_uses_alias(item, aliases) for item in target.elts)
    return False


def _candidate_product_mapping_violations(source: str) -> list[int]:
    tree = ast.parse(source, filename="ProductIDs.py")
    bindings = _simple_bindings(tree)
    aliases = {"g_products"}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if isinstance(node.value, ast.Name) and node.value.id in aliases:
                for target in targets:
                    if isinstance(target, ast.Name) and target.id not in aliases:
                        aliases.add(target.id)
                        changed = True

    violations: list[int] = []

    def check_entry(entry: ast.expr, lineno: int) -> None:
        result = _entry_is_candidate(entry, bindings)
        if result is not False:
            violations.append(lineno)

    def check_collection(value: ast.expr, lineno: int) -> None:
        entries = _collection_entries(value, bindings)
        if entries is None:
            violations.append(lineno)
            return
        for entry in entries:
            check_entry(entry, getattr(entry, "lineno", lineno))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if value is None:
                if any(_target_uses_alias(target, aliases) for target in targets):
                    violations.append(node.lineno)
                continue
            if (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id in aliases
            ):
                violations.append(node.lineno)
            for target in targets:
                if isinstance(target, ast.Name) and target.id == "g_products":
                    check_collection(value, node.lineno)
                elif isinstance(target, ast.Name) and target.id in aliases:
                    if not (isinstance(value, ast.Name) and value.id in aliases):
                        violations.append(node.lineno)
                elif _target_uses_alias(target, aliases):
                    violations.append(node.lineno)
        elif isinstance(node, ast.AugAssign) and _target_uses_alias(node.target, aliases):
            if isinstance(node.op, ast.Add):
                check_collection(node.value, node.lineno)
            else:
                violations.append(node.lineno)
        elif isinstance(node, ast.Delete):
            if any(_target_uses_alias(target, aliases) for target in node.targets):
                violations.append(node.lineno)
        elif isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in aliases
            ):
                if node.keywords:
                    violations.append(node.lineno)
                elif node.func.attr == "append" and len(node.args) == 1:
                    check_entry(node.args[0], node.lineno)
                elif node.func.attr == "extend" and len(node.args) == 1:
                    check_collection(node.args[0], node.lineno)
                elif node.func.attr == "insert" and len(node.args) == 2:
                    check_entry(node.args[1], node.lineno)
                else:
                    violations.append(node.lineno)
            elif any(
                isinstance(argument, ast.Name) and argument.id in aliases
                for argument in (*node.args, *(keyword.value for keyword in node.keywords))
            ):
                violations.append(node.lineno)
    return sorted(set(violations))


UDEV_VENDOR_MATCH = re.compile(
    r"(?:ATTR|ATTRS)\s*\{\s*idVendor\s*\}\s*==\s*([\"'])(.*?)\1",
    re.IGNORECASE,
)


def _logical_udev_lines(source: str) -> Iterator[tuple[int, str]]:
    start = 0
    parts: list[str] = []
    for lineno, physical in enumerate(source.splitlines(), start=1):
        if not parts and physical.lstrip().startswith("#"):
            continue
        if not parts:
            start = lineno
        segment = physical.lstrip() if parts else physical
        stripped = segment.rstrip()
        continued = stripped.endswith("\\")
        parts.append(stripped[:-1] if continued else segment)
        if not continued:
            yield start, "".join(parts)
            parts = []
    if parts:
        yield start, "".join(parts)


def _candidate_udev_rule_violations(source: str) -> list[int]:
    violations: list[int] = []
    for lineno, line in _logical_udev_lines(source):
        for match in UDEV_VENDOR_MATCH.finditer(line):
            alternatives = match.group(2).lower().split("|")
            if any(fnmatch.fnmatchcase("6602", pattern) for pattern in alternatives):
                violations.append(lineno)
                break
    return violations


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


@pytest.mark.parametrize(
    "source",
    (
        "from os import *\n",
        "def load():\n    from pyudev import Context\n",
        "import requests\n",
        "import importlib\n",
    ),
)
def test_import_gate_is_a_closed_allowlist_and_rejects_star_imports(source: str) -> None:
    path = Path("src/streamdock_n3/hardware/backend.py")

    assert _import_violations(path, ast.parse(source, filename=str(path))) != []


@pytest.mark.parametrize("path", G0_MODULES)
def test_closed_import_and_call_policy_covers_every_g0_module(path: Path) -> None:
    tree = ast.parse(
        "def late_load():\n    from pyudev import Context\n    return __import__('os')\n",
        filename=str(path),
    )

    assert _import_violations(path, tree) != []
    assert _call_violations(path, tree) != []


@pytest.mark.parametrize(
    "source",
    (
        "__import__('os')\n",
        "import_module('os')\n",
        "getattr(object(), 'open')\n",
        "setattr(object(), 'run', None)\n",
        "eval('1')\n",
        "exec('pass')\n",
        "compile('pass', '<x>', 'exec')\n",
        "globals()\n",
        "locals()\n",
        "vars()\n",
    ),
)
def test_call_gate_rejects_dynamic_resolution_entry_points(source: str) -> None:
    path = Path("src/streamdock_n3/hardware/backend.py")

    assert _call_violations(path, ast.parse(source, filename=str(path))) != []


@pytest.mark.parametrize(
    "source",
    (
        "import subprocess\nlaunch = subprocess.Popen\n",
        "opener = open\n",
        "import subprocess as sp\nsp2 = sp\n",
        "loader = __import__\n",
        "loader = importlib.import_module\n",
    ),
)
def test_call_gate_rejects_dangerous_callable_and_module_assignment_aliases(
    source: str,
) -> None:
    path = Path("src/streamdock_n3/hardware/backend.py")

    assert _call_violations(path, ast.parse(source, filename=str(path))) != []


def _direct_helper_tree(*, prelude: str = "", timeout: str = "timeout_ms / 1000") -> ast.Module:
    return ast.parse(
        f'''\
import subprocess
import sys
HELPER_MODULE = "streamdock_n3.hardware.helper_main"
{prelude}
def invoke(payload, timeout_ms):
    return subprocess.run(
        [sys.executable, "-m", HELPER_MODULE],
        input=payload, capture_output=True, text=True, encoding="utf-8",
        errors="strict", check=False, timeout={timeout})
''',
        filename="src/streamdock_n3/hardware/ipc.py",
    )


def test_fixed_helper_gate_accepts_only_direct_exact_argv() -> None:
    path = Path("src/streamdock_n3/hardware/ipc.py")

    assert _fixed_helper_violations(((path, _direct_helper_tree()),)) == []


@pytest.mark.parametrize(
    ("prelude", "timeout"),
    (
        ("sys = object()", "timeout_ms / 1000"),
        ("HELPER_MODULE = 'unsafe.module'", "timeout_ms / 1000"),
        ("def mutate():\n    global HELPER_MODULE", "timeout_ms / 1000"),
        (
            "def outer():\n    HELPER_MODULE = 'unsafe.module'\n"
            "    def mutate():\n        nonlocal HELPER_MODULE",
            "timeout_ms / 1000",
        ),
        ("", "None"),
        ("", "timeout_ms"),
    ),
)
def test_fixed_helper_gate_rejects_symbol_mutation_and_unbounded_timeout(
    prelude: str,
    timeout: str,
) -> None:
    path = Path("src/streamdock_n3/hardware/ipc.py")

    assert _fixed_helper_violations(
        ((path, _direct_helper_tree(prelude=prelude, timeout=timeout)),)
    ) != []


@pytest.mark.parametrize(
    "source",
    (
        "g_products = []\ng_products += [(0x6602, 0x1000, Device)]\n",
        "g_products = []\ng_products.extend([(0x6602, 0x1000, Device)])\n",
        "g_products: list[tuple[int, int, object]] = [(0x6602, 0x1000, Device)]\n",
        "g_products = []\ng_products.insert(0, (0x6602, 0x1000, Device))\n",
        "entries = [(0x6602, 0x1000, Device)]\ng_products = [*entries]\n",
        "VID = 0x6602\nPID = 0x1000\ng_products = [(VID, PID, Device)]\n",
        "entry = (0x6602, 0x1000, Device)\ng_products = [entry]\n",
        (
            "class V:\n    ID = 0x6602\nclass P:\n    ID = 0x1000\n"
            "g_products = [(V.ID, P.ID, Device)]\n"
        ),
        "g_products = []\nproducts = g_products\nproducts.append((0x6602, 0x1000, Device))\n",
    ),
)
def test_candidate_mapping_gate_rejects_all_supported_writer_and_value_forms(
    source: str,
) -> None:
    assert _candidate_product_mapping_violations(source) != []


@pytest.mark.parametrize(
    "source",
    (
        "g_products = []\ng_products.insert(0, unknown_entry)\n",
        "g_products = []\ng_products[0] = unknown_entry\n",
        "g_products = []\ndel g_products[0]\n",
        "g_products = []\ng_products.clear()\n",
        "g_products = []\nmutate(g_products)\n",
        "g_products = []\nwriter = g_products.append\nwriter(unknown_entry)\n",
    ),
)
def test_candidate_mapping_gate_fails_closed_for_unknown_writers(source: str) -> None:
    assert _candidate_product_mapping_violations(source) != []


def test_candidate_mapping_gate_uses_values_instead_of_dangerous_looking_names() -> None:
    source = '''
USB_VIDN3E = 0x6603
USB_PID_STREAMDOCK_N1EN = 0x1001
g_products = [(USB_VIDN3E, USB_PID_STREAMDOCK_N1EN, Device)]
'''

    assert _candidate_product_mapping_violations(source) == []


@pytest.mark.parametrize(
    "rule",
    (
        'ATTR{idVendor}=="660[2]", TAG+="uaccess"\n',
        'ATTRS{idVendor}=="660?", TAG+="uaccess"\n',
        'ATTR{idVendor}=="660?|6602", TAG+="uaccess"\n',
        'ATTR{idVendor}=="6602", ENV{NOTE}="# retained"\n',
        'ATTR{idVendor}=="660\\\n    2", TAG+="uaccess"\n',
    ),
)
def test_udev_gate_rejects_patterns_and_continuations_matching_candidate(rule: str) -> None:
    assert _candidate_udev_rule_violations(rule) != []


def test_udev_gate_preserves_quoted_hash_and_only_ignores_full_line_comments() -> None:
    source = '''
   # ATTR{idVendor}=="6602"
ATTR{idVendor}=="6602", ENV{NOTE}="# candidate"
'''

    assert _candidate_udev_rule_violations(source) == [3]
