from __future__ import annotations

import ast
import fnmatch
import hashlib
import importlib
import json
import re
import subprocess
import sys
import tokenize
import tomllib
import zipfile
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

G0_MODULES = (
    Path("src/streamdock_n3/hardware/__init__.py"),
    Path("src/streamdock_n3/hardware/contracts.py"),
    Path("src/streamdock_n3/hardware/interface_roles.py"),
    Path("src/streamdock_n3/hardware/permissions.py"),
    Path("src/streamdock_n3/hardware/input_session.py"),
    Path("src/streamdock_n3/hardware/gate.py"),
    Path("src/streamdock_n3/hardware/backend.py"),
    Path("src/streamdock_n3/hardware/adapter.py"),
    Path("src/streamdock_n3/hardware/ipc.py"),
    Path("src/streamdock_n3/hardware/helper_main.py"),
    Path("src/streamdock_n3/hardware/evidence.py"),
)
G0_DEPENDENCY_MODULES = (
    Path("src/streamdock_n3/__init__.py"),
    Path("src/streamdock_n3/device_catalog.py"),
)
G0_SOURCE_CLOSURE = (*G0_MODULES, *G0_DEPENDENCY_MODULES)

REVIEWED_SOURCE_PATHS = (
    *G0_SOURCE_CLOSURE,
    Path("src/streamdock_n3/_vendor/StreamDock/ProductIDs.py"),
    Path("src/streamdock_n3/_data/99-streamdock.rules"),
    Path("pyproject.toml"),
)
WHEEL_REVIEWED_PATHS = REVIEWED_SOURCE_PATHS[:-1]
REVIEWED_SOURCE_SHA256 = {
    Path("src/streamdock_n3/hardware/__init__.py"): (
        "b93b35448f1b12f064a89d2ceebf0835e2026c266d9218e676d394b01377808a"
    ),
    Path("src/streamdock_n3/hardware/contracts.py"): (
        "94c1cdc90b171abd6e1586654740e6e69dcf28078b7b0787c99dfd03253e1788"
    ),
    Path("src/streamdock_n3/hardware/input_session.py"): (
        "3d6f8dd096707060f4f114ec1428c5efdbc8c2ed1f29df0ff1bbdd91d0dabc64"
    ),
    Path("src/streamdock_n3/hardware/interface_roles.py"): (
        "46f87658b5ef91da5605c7eb429867255d3c0ded3581d0262988b36476d692c5"
    ),
    Path("src/streamdock_n3/hardware/permissions.py"): (
        "bfb07fdf9bada8fa796699b37aba07cc3d684a192554963788ab543f3303e32a"
    ),
    Path("src/streamdock_n3/hardware/gate.py"): (
        "ce17ca9d8e2f3f7710e3b77ce63e95ab28d4b96d21e3ddac920329297638bce6"
    ),
    Path("src/streamdock_n3/hardware/backend.py"): (
        "eaf68b254d8a2461abcca8b5f8ef30d8f5687afb9c66c60ab277b14b0cf7ad8d"
    ),
    Path("src/streamdock_n3/hardware/adapter.py"): (
        "ee3efb6a51149894cbf8025d7b4b59d08a7ff88a5ca3ecf235229a6cc780a5f5"
    ),
    Path("src/streamdock_n3/hardware/ipc.py"): (
        "fce96903b3d5e37b978703d08fcf368829dea83efb16d4b313f2ee1ff9881118"
    ),
    Path("src/streamdock_n3/hardware/helper_main.py"): (
        "2166e04f94b564e465fb4d3608def19312fb7223ca60a8686e88e6a2ea360ef2"
    ),
    Path("src/streamdock_n3/hardware/evidence.py"): (
        "5c161f09172264bac669fab49764e5775b27dd6d34ed8a52fb5e1f6d6bc150d9"
    ),
    Path("src/streamdock_n3/__init__.py"): (
        "0612dae9f893b0736b2bbc584afc2fa001e4e7468ab622a9e0061453f5b4d04b"
    ),
    Path("src/streamdock_n3/device_catalog.py"): (
        "59f02515d616b684d331d855ed2415cbbf8d2750bc3db85c425a78e911731f5f"
    ),
    Path("src/streamdock_n3/_vendor/StreamDock/ProductIDs.py"): (
        "f367c2db9d884cbe01a14f1eb8fd992c84d23342607260e3981573b27e6dce3f"
    ),
    Path("src/streamdock_n3/_data/99-streamdock.rules"): (
        "7a53ba40c632e712d390f00b4d42d4b6aab32a33c8e130b3e16735a735ad33fd"
    ),
    Path("pyproject.toml"): (
        "d204ee65fa217dbd2673d6a54ef2079841b9d2baf6897a746894b2e64888d7f8"
    ),
}

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
G0_SOURCE_CLOSURE_IMPORTS = (
    "streamdock_n3",
    "streamdock_n3.device_catalog",
    *G0_IMPORTS,
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
    "contextlib",
    "collections.abc",
    "dataclasses",
    "enum",
    "hashlib",
    "importlib.metadata",
    "json",
    "os",
    "pathlib",
    "re",
    "select",
    "statistics",
    "struct",
    "subprocess",
    "time",
    "sys",
    "types",
    "typing",
}
ALLOWED_PROJECT_IMPORTS = {
    "streamdock_n3",
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
MUTATING_METHODS = {
    "__iadd__",
    "__imul__",
    "__ior__",
    "__delitem__",
    "__setitem__",
    "add",
    "append",
    "clear",
    "difference_update",
    "discard",
    "extend",
    "insert",
    "intersection_update",
    "pop",
    "popitem",
    "remove",
    "reverse",
    "setdefault",
    "sort",
    "symmetric_difference_update",
    "update",
}
PROTECTED_SYMBOLS = {"subprocess", "sys"}
FORBIDDEN_OS_PROCESS_CALLS = {
    "os.fork",
    "os.forkpty",
    "os.popen",
    "os.posix_spawn",
    "os.posix_spawnp",
    "os.startfile",
    "os.system",
}
IMPORT_TIME_ALLOWED_CALLS = {
    "KnownUsbDevice",
    "ValueError",
    "_build_known_usb_device_lookup",
    "dataclasses.dataclass",
    "frozenset",
    "hasattr",
    "importlib.metadata.version",
    "os.geteuid",
    "pathlib.Path",
    "re.compile",
    "struct.Struct",
    "types.MappingProxyType",
}


def _source(path: Path) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _trees() -> Iterator[tuple[Path, ast.Module]]:
    for path in G0_SOURCE_CLOSURE:
        yield path, ast.parse(_source(path), filename=str(path))


def _forbidden_source_violations(path: Path, source: str) -> list[str]:
    if path in G0_MODULES:
        scanned = source
    else:
        tokens = tokenize.generate_tokens(iter(source.splitlines(keepends=True)).__next__)
        scanned = "".join(token.string for token in tokens if token.type != tokenize.COMMENT)
    violations = [forbidden for forbidden in FORBIDDEN_SOURCE if forbidden in scanned]
    if path == Path("src/streamdock_n3/hardware/permissions.py"):
        # "setfacl" appears only as rendered ACL template data inside
        # PermissionArtifact values; permissions.py never invokes it.
        violations = [forbidden for forbidden in violations if forbidden != "setfacl"]
    if path == Path("src/streamdock_n3/hardware/input_session.py"):
        # "os.open" appears only as the single O_RDONLY open inside
        # EvdevReadOnlyBackend.open_read_only; the module never writes.
        violations = [forbidden for forbidden in violations if forbidden != "os.open"]
    if path == Path("src/streamdock_n3/hardware/ipc.py"):
        # "/dev/input" appears only as the device-node validation regex
        # constant; ipc.py never accesses device nodes itself.
        violations = [forbidden for forbidden in violations if forbidden != "/dev/input"]
    return violations


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
            if base not in {"streamdock_n3", "streamdock_n3.hardware"}
            and (base in ALLOWED_STDLIB_IMPORTS or _project_import_allowed(base))
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


def _contains_protected_symbol(
    expression: ast.AST,
    bindings: dict[str, set[str]],
    symbols: set[str] = PROTECTED_SYMBOLS,
) -> bool:
    for node in ast.walk(expression):
        if isinstance(node, ast.Name) and node.id in symbols:
            return True
        if isinstance(node, (ast.Name, ast.Attribute)):
            canonical_names = _canonical_names(node, bindings)
            if any(
                canonical == symbol or canonical.startswith(symbol + ".")
                for canonical in canonical_names
                for symbol in symbols
            ):
                return True
    return False


def _contains_uncalled_dangerous_reference(
    expression: ast.expr,
    bindings: dict[str, set[str]],
) -> bool:
    if isinstance(expression, ast.Call):
        return False
    if isinstance(expression, (ast.Name, ast.Attribute)):
        lexical_name = expression.id if isinstance(expression, ast.Name) else expression.attr
        canonical_names = _canonical_names(expression, bindings)
        return (
            lexical_name in DYNAMIC_RESOLUTION_CALLS
            or lexical_name == "import_module"
            or lexical_name in FORBIDDEN_FILE_METHODS
            or lexical_name in PROTECTED_SYMBOLS
            or any(
                canonical == "builtins.open"
                or canonical == "os.open"
                or canonical == "sys"
                or canonical.startswith("sys.")
                or canonical == "subprocess"
                or canonical.startswith("subprocess.")
                for canonical in canonical_names
            )
        )
    return any(
        _contains_uncalled_dangerous_reference(child, bindings)
        for child in ast.iter_child_nodes(expression)
        if isinstance(child, ast.expr)
    )


def _allowed_protected_mutation(
    path: Path,
    tree: ast.Module,
    node: ast.AST,
    target: ast.expr,
) -> bool:
    root_bytecode_guard = (
        path == Path("src/streamdock_n3/__init__.py")
        and isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and target is node.targets[0]
        and isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "sys"
        and target.attr == "dont_write_bytecode"
        and _literal(node.value, True)
    )
    return root_bytecode_guard


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
        elif (
            isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr))
            and node.value is not None
            and _contains_uncalled_dangerous_reference(node.value, bindings)
        ):
            violations.append(f"{path}:{node.lineno}: dangerous assignment alias")
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            targets = [node.target]
        elif isinstance(node, ast.Delete):
            targets = node.targets
        else:
            targets = []
        for target in targets:
            if _contains_protected_symbol(target, bindings) and not _allowed_protected_mutation(
                path, tree, node, target
            ):
                violations.append(f"{path}:{node.lineno}: protected symbol mutation")
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
            # The offline InstallTransaction is the single scoped file-IO boundary:
            # it operates only on an explicit root that can never be /etc or /usr.
            scoped_install = (
                path == Path("src/streamdock_n3/hardware/permissions.py")
                and _enclosing_class(tree, call) == "InstallTransaction"
            )
            # input_session.py may call os.open only for the single O_RDONLY
            # device open inside EvdevReadOnlyBackend.open_read_only.
            scoped_read_open = (
                path == Path("src/streamdock_n3/hardware/input_session.py")
                and function.attr == "open"
                and _enclosing_class(tree, call) == "EvdevReadOnlyBackend"
            )
            if not scoped_install and not scoped_read_open:
                violations.append(f"{path}:{call.lineno}: conservative file method {function.attr}")
        else:
            file_functions = canonical_names & {"builtins.open", "os.open"}
            if file_functions:
                # input_session.py may call os.open only for the single
                # O_RDONLY device open inside EvdevReadOnlyBackend.
                scoped_read_open = (
                    path == Path("src/streamdock_n3/hardware/input_session.py")
                    and file_functions == {"os.open"}
                    and _enclosing_class(tree, call) == "EvdevReadOnlyBackend"
                    and _enclosing_function(tree, call) is not None
                    and _enclosing_function(tree, call).name == "open_read_only"  # type: ignore[union-attr]
                )
                if not scoped_read_open:
                    violations.append(
                        f"{path}:{call.lineno}: file function {sorted(file_functions)[0]}"
                    )
        if (
            isinstance(function, ast.Attribute)
            and function.attr in MUTATING_METHODS
            and _contains_protected_symbol(function.value, bindings)
        ):
            violations.append(f"{path}:{call.lineno}: protected object mutation")
        subprocess_functions = {name for name in canonical_names if name.startswith("subprocess.")}
        if subprocess_functions and (
            subprocess_functions != {"subprocess.run"} or path.name != "ipc.py"
        ):
            violations.append(
                f"{path}:{call.lineno}: subprocess function "
                f"{', '.join(sorted(subprocess_functions))}"
            )
        os_process_functions = {
            name
            for name in canonical_names
            if name in FORBIDDEN_OS_PROCESS_CALLS
            or name.startswith("os.exec")
            or name.startswith("os.spawn")
        }
        if os_process_functions:
            violations.append(
                f"{path}:{call.lineno}: OS process function "
                f"{', '.join(sorted(os_process_functions))}"
            )
    return violations


def _lexical_call_name(expression: ast.expr) -> str:
    if isinstance(expression, ast.Name):
        return expression.id
    if isinstance(expression, ast.Attribute):
        base = _lexical_call_name(expression.value)
        return f"{base}.{expression.attr}" if base else expression.attr
    return ""


def _is_main_guard(node: ast.If) -> bool:
    expected = ast.parse("__name__ == '__main__'", mode="eval").body
    return ast.dump(node.test) == ast.dump(expected)


def _import_time_side_effect_violations(path: Path, tree: ast.Module) -> list[str]:
    bindings = _canonical_import_bindings(path, tree)
    local_functions = {
        statement.name: statement
        for statement in tree.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    violations: list[str] = []
    visited_functions: set[str] = set()
    function_depth = 0

    class ImportTimeVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            for decorator in node.decorator_list:
                self.visit(decorator)
            for default in (*node.args.defaults, *node.args.kw_defaults):
                if default is not None:
                    self.visit(default)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            for base in node.bases:
                self.visit(base)
            for keyword in node.keywords:
                self.visit(keyword.value)
            for decorator in node.decorator_list:
                self.visit(decorator)
            for statement in node.body:
                self.visit(statement)

        def visit_If(self, node: ast.If) -> None:
            self.visit(node.test)
            statements = node.orelse if _is_main_guard(node) else (*node.body, *node.orelse)
            for statement in statements:
                self.visit(statement)

        def visit_Call(self, node: ast.Call) -> None:
            nonlocal function_depth
            lexical = _lexical_call_name(node.func)
            canonical = _canonical_names(node.func, bindings)
            names = canonical or {lexical}
            if not names or not names <= IMPORT_TIME_ALLOWED_CALLS:
                violations.append(f"{path}:{node.lineno}: import-time call {sorted(names)}")
            if lexical in local_functions and lexical not in visited_functions:
                visited_functions.add(lexical)
                function_depth += 1
                for statement in local_functions[lexical].body:
                    self.visit(statement)
                function_depth -= 1
            self.generic_visit(node)

        def _check_target(self, node: ast.AST, target: ast.expr) -> None:
            if not isinstance(target, (ast.Attribute, ast.Subscript)):
                return
            canonical = _canonical_names(target, bindings)
            if function_depth and not canonical:
                return
            allowed = (
                path == Path("src/streamdock_n3/__init__.py")
                and canonical == {"sys.dont_write_bytecode"}
                and isinstance(node, ast.Assign)
                and _literal(node.value, True)
            )
            if not allowed:
                violations.append(f"{path}:{node.lineno}: import-time external mutation")

        def visit_Assign(self, node: ast.Assign) -> None:
            for target in node.targets:
                self._check_target(node, target)
            self.visit(node.value)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            self._check_target(node, node.target)
            if node.value is not None:
                self.visit(node.value)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            self._check_target(node, node.target)
            self.visit(node.value)

        def visit_Delete(self, node: ast.Delete) -> None:
            for target in node.targets:
                self._check_target(node, target)

        def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
            self._check_target(node, node.target)
            self.visit(node.value)

    ImportTimeVisitor().visit(tree)
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
        len(value.elts) == 4
        and _canonical_names(value.elts[0], bindings) == {"sys.executable"}
        and _literal(value.elts[1], "-I")
        and _literal(value.elts[2], "-m")
        and _literal(value.elts[3], "streamdock_n3.hardware.helper_main")
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
                isinstance(node, (ast.Attribute, ast.Subscript))
                and isinstance(node.ctx, (ast.Store, ast.Del))
                and any(
                    isinstance(child, ast.Name) and child.id == symbol
                    for child in ast.walk(node)
                )
            )
            or (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in MUTATING_METHODS
                and any(
                    isinstance(child, ast.Name) and child.id == symbol
                    for child in ast.walk(node.func.value)
                )
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


def _enclosing_function(tree: ast.Module, target: ast.AST) -> ast.FunctionDef | None:
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    parent = parents.get(target)
    while parent is not None:
        if isinstance(parent, ast.FunctionDef):
            return parent
        parent = parents.get(parent)
    return None


def _enclosing_class(tree: ast.Module, target: ast.AST) -> str | None:
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    parent = parents.get(target)
    while parent is not None:
        if isinstance(parent, ast.ClassDef):
            return parent.name
        parent = parents.get(parent)
    return None


def _timeout_parameter_is_immutable(function: ast.FunctionDef) -> bool:
    positional = (*function.args.posonlyargs, *function.args.args)
    timeout_arguments = [argument for argument in positional if argument.arg == "timeout_ms"]
    if len(timeout_arguments) != 1:
        return False
    if any(
        argument.arg == "timeout_ms"
        for argument in (*function.args.kwonlyargs,)
    ) or (function.args.vararg is not None and function.args.vararg.arg == "timeout_ms") or (
        function.args.kwarg is not None and function.args.kwarg.arg == "timeout_ms"
    ):
        return False
    for node in ast.walk(function):
        if isinstance(node, ast.Name) and node.id == "timeout_ms" and isinstance(
            node.ctx, (ast.Store, ast.Del)
        ):
            return False
        if (
            isinstance(node, ast.arg)
            and node is not timeout_arguments[0]
            and node.arg == "timeout_ms"
        ):
            return False
        if isinstance(node, (ast.Global, ast.Nonlocal)) and "timeout_ms" in node.names:
            return False
        if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(
            node.ctx, (ast.Store, ast.Del)
        ) and any(
            isinstance(child, ast.Name) and child.id == "timeout_ms" for child in ast.walk(node)
        ):
            return False
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in MUTATING_METHODS
            and any(
                isinstance(child, ast.Name) and child.id == "timeout_ms"
                for child in ast.walk(node.func.value)
            )
        ):
            return False
    return True


def _has_exact_timeout_guard(function: ast.FunctionDef, call: ast.Call) -> bool:
    expected_test = ast.parse(
        "isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) "
        "or not 1 <= timeout_ms <= request.manifest.deadline_ms <= MAX_DEADLINE_MS",
        mode="eval",
    ).body
    for statement in function.body:
        if not isinstance(statement, ast.If) or statement.lineno >= call.lineno:
            continue
        if ast.dump(statement.test) != ast.dump(expected_test) or len(statement.body) != 1:
            continue
        raised = statement.body[0]
        if (
            isinstance(raised, ast.Raise)
            and isinstance(raised.exc, ast.Call)
            and isinstance(raised.exc.func, ast.Name)
            and raised.exc.func.id == "ValueError"
            and len(raised.exc.args) == 1
            and _literal(raised.exc.args[0], "invalid_timeout")
            and not raised.exc.keywords
        ):
            return True
    return False


def _max_deadline_is_fixed(trees: Sequence[tuple[Path, ast.Module]]) -> bool:
    definitions: list[tuple[ast.Module, ast.Name, ast.expr]] = []
    for _path, tree in trees:
        for statement in tree.body:
            if (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
                and statement.targets[0].id == "MAX_DEADLINE_MS"
            ):
                definitions.append((tree, statement.targets[0], statement.value))
    if len(definitions) != 1 or not _literal(definitions[0][2], 600_000):
        return False
    definition_tree, definition_store, _value = definitions[0]
    return all(
        _symbol_is_immutable(
            tree,
            "MAX_DEADLINE_MS",
            allowed_store=definition_store if tree is definition_tree else None,
        )
        for _path, tree in trees
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
    function = _enclosing_function(tree, call)
    if (
        function is None
        or function.name != "run_fake_helper"
        or not _timeout_parameter_is_immutable(function)
        or not _has_exact_timeout_guard(function, call)
        or not _max_deadline_is_fixed(trees)
    ):
        violations.append(f"{path}:{call.lineno}: timeout bound is not statically immutable")
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

    initializers: list[tuple[ast.Name, ast.expr, int]] = []
    for statement in tree.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == "g_products"
        ):
            initializers.append((statement.targets[0], statement.value, statement.lineno))
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == "g_products"
            and statement.value is not None
        ):
            initializers.append((statement.target, statement.value, statement.lineno))

    if len(initializers) != 1:
        occurrences = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id == "g_products"
        ]
        return sorted(set(occurrences or [1]))

    allowed_store, initial_value, initial_lineno = initializers[0]
    check_collection(initial_value, initial_lineno)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name)
            and node.id == "g_products"
            and node is not allowed_store
            or isinstance(node, (ast.AugAssign, ast.Delete, ast.NamedExpr, ast.Call))
        ):
            violations.append(node.lineno)
        elif isinstance(node, ast.Assign):
            if node in tree.body and node.targets == [allowed_store]:
                continue
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                violations.append(node.lineno)
        elif isinstance(node, ast.AnnAssign) and not isinstance(node.target, ast.Name):
            violations.append(node.lineno)
    return sorted(set(violations))


UDEV_VENDOR_MATCH = re.compile(
    r"(?:ATTR|ATTRS)\s*\{\s*idVendor\s*\}\s*==\s*",
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


def _c_unescape(value: str) -> str | None:
    simple = {
        "a": "\a",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
        "\\": "\\",
        "'": "'",
        '"': '"',
        "?": "?",
    }
    decoded: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character != "\\":
            decoded.append(character)
            index += 1
            continue
        index += 1
        if index >= len(value):
            return None
        escape = value[index]
        if escape in simple:
            decoded.append(simple[escape])
            index += 1
        elif escape == "x":
            digits = value[index + 1 : index + 3]
            if len(digits) != 2 or any(digit not in "0123456789abcdefABCDEF" for digit in digits):
                return None
            decoded.append(chr(int(digits, 16)))
            index += 3
        elif escape in "01234567":
            end = index + 1
            while end < min(index + 3, len(value)) and value[end] in "01234567":
                end += 1
            decoded.append(chr(int(value[index:end], 8)))
            index = end
        else:
            return None
    return "".join(decoded)


def _udev_match_value(line: str, start: int) -> tuple[str, bool] | None:
    prefix = ""
    if start < len(line) - 1 and line[start] in "eEiI" and line[start + 1] in "\"'":
        prefix = line[start].lower()
        start += 1
    if start >= len(line) or line[start] not in "\"'":
        return None
    quote = line[start]
    index = start + 1
    content: list[str] = []
    while index < len(line):
        character = line[index]
        if character == quote:
            raw = "".join(content)
            if prefix == "e":
                decoded = _c_unescape(raw)
                return None if decoded is None else (decoded, False)
            return raw, prefix == "i"
        if character == "\\":
            if index + 1 >= len(line):
                return None
            content.extend((character, line[index + 1]))
            index += 2
        else:
            content.append(character)
            index += 1
    return None


def _candidate_udev_rule_violations(source: str) -> list[int]:
    violations: list[int] = []
    for lineno, line in _logical_udev_lines(source):
        for match in UDEV_VENDOR_MATCH.finditer(line):
            parsed = _udev_match_value(line, match.end())
            if parsed is None:
                violations.append(lineno)
                break
            value, case_insensitive = parsed
            candidate = "6602"
            if case_insensitive:
                value = value.lower()
                candidate = candidate.lower()
            alternatives = value.split("|")
            if any(fnmatch.fnmatchcase(candidate, pattern) for pattern in alternatives):
                violations.append(lineno)
                break
    return violations


def _reviewed_source_snapshot_violations(sources: dict[Path, bytes]) -> list[Path]:
    violations = [
        path
        for path in REVIEWED_SOURCE_PATHS
        if path not in sources
        or hashlib.sha256(sources[path]).hexdigest() != REVIEWED_SOURCE_SHA256[path]
    ]
    return [*violations, *sorted(set(sources) - set(REVIEWED_SOURCE_PATHS))]


def _g0_module_set_violations(root: Path) -> list[Path]:
    hardware_root = root / "src/streamdock_n3/hardware"
    actual = {path.relative_to(root) for path in hardware_root.rglob("*.py")}
    return sorted(actual.symmetric_difference(G0_MODULES))


def _wheel_member(path: Path) -> str:
    return path.relative_to("src").as_posix()


def _wheel_reviewed_source_violations(
    members: dict[str, bytes],
    sources: dict[Path, bytes],
) -> list[Path]:
    reviewed_violations = [
        path
        for path in WHEEL_REVIEWED_PATHS
        if path not in sources or members.get(_wheel_member(path)) != sources[path]
    ]
    expected_hardware = {_wheel_member(path) for path in G0_MODULES}
    actual_hardware = {
        member for member in members if member.startswith("streamdock_n3/hardware/")
    }
    extra_hardware = [
        Path("src") / member for member in sorted(actual_hardware - expected_hardware)
    ]
    return [*reviewed_violations, *extra_hardware]


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
        for path in G0_SOURCE_CLOSURE
        for forbidden in _forbidden_source_violations(path, _source(path))
    ]

    assert violations == []


def test_permission_module_never_invokes_or_targets_system_state() -> None:
    source = _source(Path("src/streamdock_n3/hardware/permissions.py"))

    for forbidden in ("udevadm", "systemctl", "subprocess", "os.open"):
        assert forbidden not in source, f"permissions.py contains forbidden text: {forbidden}"

    for forbidden in ("/etc", "/usr"):
        for occurrence in re.finditer(re.escape(forbidden), source):
            line_start = source.rfind("\n", 0, occurrence.start()) + 1
            line_end = source.index("\n", occurrence.start())
            line = source[line_start:line_end]
            assert line.strip().startswith("_FORBIDDEN_ROOTS"), (
                f"permissions.py may name {forbidden} only in the forbidden-roots guard"
            )

    for occurrence in re.finditer(r"setfacl", source):
        line = source[occurrence.start() : source.index("\n", occurrence.start())]
        assert "{node}" in line and "{current_user}" in line, (
            "setfacl must appear only as placeholder ACL template data"
        )

    tree = ast.parse(source, filename="permissions.py")
    file_methods = {
        "read_bytes",
        "read_text",
        "write_bytes",
        "write_text",
        "unlink",
        "chmod",
        "chown",
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr not in file_methods:
            continue
        assert _enclosing_class(tree, node) == "InstallTransaction", (
            f"permissions.py file method {node.func.attr} must stay inside InstallTransaction"
        )


def test_source_tree_contains_exactly_the_reviewed_g0_modules() -> None:
    assert _g0_module_set_violations(ROOT) == []


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


def test_g0_import_time_behavior_stays_inside_the_reviewed_safe_allowlist() -> None:
    violations = [
        violation
        for path, tree in _trees()
        for violation in _import_time_side_effect_violations(path, tree)
    ]

    assert violations == []


def test_only_subprocess_run_is_the_fixed_fake_helper_boundary() -> None:
    violations = _fixed_helper_violations(tuple(_trees()))

    assert violations == []


def test_fresh_source_imports_do_not_load_forbidden_runtime_modules() -> None:
    program = (
        "import importlib,json,sys;"
        f"mods={G0_SOURCE_CLOSURE_IMPORTS!r};"
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
    interface_roles = modules["streamdock_n3.hardware.interface_roles"]
    permissions = modules["streamdock_n3.hardware.permissions"]
    input_session = modules["streamdock_n3.hardware.input_session"]

    stage = contracts.Stage(contracts.Stage.G1_PROFILE.value)
    state = contracts.AdapterState(contracts.AdapterState.CANDIDATE.value)
    stage_phase = contracts.StagePhase(contracts.StagePhase.FORWARD.value)
    operation = contracts.Operation(contracts.Operation.APPROVE_PROFILE.value)
    input_kind = contracts.InputKind(contracts.InputKind.BUTTON.value)
    input_action = contracts.InputAction(contracts.InputAction.PRESS.value)
    result_status = contracts.ResultStatus(contracts.ResultStatus.SUCCEEDED.value)
    error_code = contracts.ErrorCode(contracts.ErrorCode.NONE.value)
    recovery_status = contracts.RecoveryStatus(contracts.RecoveryStatus.NOT_REQUIRED.value)
    interface = contracts.HidInterface(0, 3, 0, 0)
    role_evidence = interface_roles.InterfaceRoleEvidence(interface, False, None)
    interface_role = contracts.InterfaceRole(contracts.InterfaceRole.UNKNOWN.value)
    role_basis = contracts.RoleBasis(contracts.RoleBasis.HID_INTERFACE.value)
    resolution_status = contracts.RoleResolutionStatus(
        contracts.RoleResolutionStatus.AMBIGUOUS.value
    )
    interface_role_binding = contracts.HidInterfaceRole(interface, interface_role, (role_basis,))
    second_interface = contracts.HidInterface(1, 3, 0, 0)
    second_role_binding = contracts.HidInterfaceRole(
        second_interface, interface_role, (role_basis,)
    )
    role_resolution = contracts.InterfaceRoleResolution(
        (interface_role_binding, second_role_binding),
        resolution_status,
        None,
        None,
    )
    permission_kind = contracts.PermissionKind(
        contracts.PermissionKind.TEMPORARY_ACL.value
    )
    permission_artifact = contracts.PermissionArtifact(
        permission_kind,
        "input",
        contracts.InterfaceRole(contracts.InterfaceRole.INPUT.value),
        "setfacl -m u:{current_user}:rw {node}",
    )
    permission_plan = contracts.PermissionPlan(
        (
            permission_artifact,
            contracts.PermissionArtifact(
                contracts.PermissionKind.PERSISTENT_RULE,
                "hidraw",
                contracts.InterfaceRole.CONTROL,
                'SUBSYSTEM=="hidraw", TAG+="uaccess"',
            ),
        ),
        "test:g2",
    )
    install_transaction = permissions.InstallTransaction(Path("/tmp/n3-ai-deck-inert"))
    input_handle = input_session.InputFileHandle(-1, opened_read_only=True)
    evdev_backend = input_session.EvdevReadOnlyBackend()
    session_error = input_session.InputSessionError(
        contracts.ErrorCode.INPUT_SESSION_INVALID
    )
    key_map_entry = contracts.KeyMapEntry(1, 30, 1, input_kind, input_action)
    key_map = contracts.KeyMap((key_map_entry,))
    raw_event = contracts.RawInputEvent(1, 30, 1, 0)
    session_spec = contracts.InputSessionSpec(
        5_000, 10, 20, 250, 2_000, key_map
    )
    control_count = contracts.ControlCount(1, input_kind, 10, 10, 0, 0)
    control_mapping = contracts.ControlMapping(1, input_kind, 1, 30)
    observed_code = contracts.ObservedCode(1, 30)
    session_result = contracts.InputSessionResult(
        (control_count,), 100, 0, False, (control_mapping,), (observed_code,)
    )
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
    spec = contracts.CommandSpec(operation)
    step = contracts.CommandStep(spec)
    manifest = contracts.StageManifest(
        stage,
        "0123456789abcdef",
        profile.digest(),
        interface,
        (step,),
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
    command_policy = gate.CommandPolicy()
    capability_snapshot = contracts.CapabilitySnapshot(
        state, None, None, None, 1, stage, stage_phase
    )
    session_snapshot = contracts.StageSessionSnapshot(stage, stage_phase, 0, 0, False)
    gate_violation = gate.GateViolation(contracts.ErrorCode.STATE_NOT_ALLOWED)
    n3_adapter = adapter.N3Adapter(profile, "0123456789abcdef", fake_backend)
    approved_profile = adapter.ApprovedProfile(
        profile.digest(),
        profile.bcd_device,
        interface,
        contracts.HidInterface(1, 3, 1, 1),
        contracts.InterfaceRoleResolution(
            (
                contracts.HidInterfaceRole(
                    interface,
                    contracts.InterfaceRole.UNKNOWN,
                    (contracts.RoleBasis.HID_INTERFACE,),
                ),
                contracts.HidInterfaceRole(
                    contracts.HidInterface(1, 3, 0, 0),
                    contracts.InterfaceRole.UNKNOWN,
                    (contracts.RoleBasis.HID_INTERFACE,),
                ),
            ),
            contracts.RoleResolutionStatus.AMBIGUOUS,
            None,
            None,
        ).digest(),
        "test:g1",
        "0123456789abcdef",
    )
    request = ipc.IpcRequest(profile, capability_snapshot, manifest, 0, command)
    session_request = ipc.IpcSessionRequest(
        profile, capability_snapshot, manifest, 0, command, "/dev/input/event12"
    )
    session_response = ipc.IpcSessionResponse(result, None)
    evidence_disposition = evidence.EvidenceDisposition(
        evidence.EvidenceDisposition.ATTEMPT.value
    )
    evidence_kind = evidence.EvidenceKind(evidence.EvidenceKind.OPERATION.value)
    evidence_record = evidence.operation_evidence(
        profile,
        manifest,
        command,
        result,
        1,
    )
    constructed = {
        type(value).__name__
        for value in (
            stage,
            state,
            stage_phase,
            operation,
            input_kind,
            input_action,
            result_status,
            error_code,
            recovery_status,
            interface,
            profile,
            command,
            spec,
            step,
            manifest,
            event,
            result,
            gate_violation,
            command_policy,
            capability_snapshot,
            session_snapshot,
            backend_call,
            fake_backend,
            n3_adapter,
            request,
            evidence_disposition,
            evidence_kind,
            evidence_record,
            recorder,
            role_evidence,
            interface_role,
            role_basis,
            resolution_status,
            interface_role_binding,
            role_resolution,
            approved_profile,
            permission_kind,
            permission_artifact,
            permission_plan,
            install_transaction,
            input_handle,
            evdev_backend,
            session_error,
            key_map_entry,
            session_request,
            session_response,
            key_map,
            raw_event,
            session_spec,
            control_count,
            control_mapping,
            session_result,
            observed_code,
        )
    }
    declared = {
        node.name
        for path in G0_MODULES
        for tree in (ast.parse(_source(path), filename=str(path)),)
        for node in tree.body
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
    }
    assert declared - {"Backend", "EvidenceSink", "ReadOnlyInputBackend", "SessionRunner"} == constructed
    assert calls == []

    helper_result = ipc.run_fake_helper(request, timeout_ms=1_000)

    assert helper_result.succeeded is True
    assert len(calls) == 1


def test_candidate_usb_id_is_not_activated_or_granted_a_udev_rule() -> None:
    product_ids = _source(Path("src/streamdock_n3/_vendor/StreamDock/ProductIDs.py"))
    assert _candidate_product_mapping_violations(product_ids) == []

    udev_rules = _source(Path("src/streamdock_n3/_data/99-streamdock.rules"))
    assert _candidate_udev_rule_violations(udev_rules) == []


def test_fresh_wheel_contains_exact_reviewed_source_and_data_bytes(built_wheel: Path) -> None:
    sources = {path: (ROOT / path).read_bytes() for path in WHEEL_REVIEWED_PATHS}
    reviewed_members = {_wheel_member(path) for path in WHEEL_REVIEWED_PATHS}
    with zipfile.ZipFile(built_wheel) as archive:
        packaged = {
            member: archive.read(member)
            for member in archive.namelist()
            if member in reviewed_members or member.startswith("streamdock_n3/hardware/")
        }

    assert _wheel_reviewed_source_violations(packaged, sources) == []


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
        f"mods={G0_SOURCE_CLOSURE_IMPORTS!r};"
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
def invoke(payload, timeout):
    argv = [sys.executable, "-I", "-m", "streamdock_n3.hardware.helper_main"]
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
        (
            "options = {'shell': True}\n    "
            "argv = [sys.executable, '-I', '-m', "
            "'streamdock_n3.hardware.helper_main']\n    "
        ),
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
        trailing = (
            '\n    argv = [sys.executable, "-I", "-m", '
            '"streamdock_n3.hardware.helper_main"]'
        )
    path = Path("src/streamdock_n3/hardware/ipc.py")
    tree = ast.parse(
        f"""
import subprocess
import sys
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
MAX_DEADLINE_MS = 600_000
{prelude}
def run_fake_helper(request, timeout_ms):
    if (
        isinstance(timeout_ms, bool)
        or not isinstance(timeout_ms, int)
        or not 1 <= timeout_ms <= request.manifest.deadline_ms <= MAX_DEADLINE_MS
    ):
        raise ValueError("invalid_timeout")
    return subprocess.run(
        [sys.executable, "-I", "-m", "streamdock_n3.hardware.helper_main"],
        input="{{}}", capture_output=True, text=True, encoding="utf-8",
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
        ("subprocess = object()", "timeout_ms / 1000"),
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


@pytest.mark.parametrize(
    ("source", "allowed"),
    (
        ("from streamdock_n3.hardware import definitely_unsafe\n", False),
        ("from streamdock_n3.hardware import contracts\n", True),
        ("from streamdock_n3.hardware.contracts import definitely_unsafe\n", True),
    ),
)
def test_import_gate_resolves_parent_package_symbols_to_complete_candidates(
    source: str,
    allowed: bool,
) -> None:
    path = Path("src/streamdock_n3/hardware/backend.py")

    assert (_import_violations(path, ast.parse(source, filename=str(path))) == []) is allowed


@pytest.mark.parametrize(
    "source",
    (
        "(loader,) = (__import__,)\n",
        "from subprocess import Popen\n(launch,) = (Popen,)\n",
        "boxed = [open]\n",
        "from pathlib import Path\n(boxed,) = (Path.read_text,)\n",
        "if (boxed := (__import__,)):\n    pass\n",
    ),
)
def test_call_gate_rejects_dangerous_references_in_binding_patterns_and_containers(
    source: str,
) -> None:
    path = Path("src/streamdock_n3/hardware/backend.py")

    assert _call_violations(path, ast.parse(source, filename=str(path))) != []


@pytest.mark.parametrize(
    "source",
    (
        "import subprocess\nsubprocess.__dict__['run'] = lambda *args: None\n",
        "import subprocess\nsubprocess.__dict__.update({'run': lambda: None})\n",
        (
            "import subprocess\nmodule = subprocess\n"
            "module.run = lambda *args: None\n"
        ),
    ),
)
def test_call_gate_rejects_indirect_writes_through_protected_roots(source: str) -> None:
    path = Path("src/streamdock_n3/hardware/ipc.py")

    assert _call_violations(path, ast.parse(source, filename=str(path))) != []


def test_fixed_helper_gate_rejects_timeout_parameter_rebinding_to_a_huge_value() -> None:
    path = Path("src/streamdock_n3/hardware/ipc.py")
    tree = ast.parse(
        '''\
import subprocess
import sys
MAX_DEADLINE_MS = 600_000
def run_fake_helper(request, timeout_ms):
    if (
        isinstance(timeout_ms, bool)
        or not isinstance(timeout_ms, int)
        or not 1 <= timeout_ms <= request.manifest.deadline_ms <= MAX_DEADLINE_MS
    ):
        raise ValueError("invalid_timeout")
    timeout_ms = 10**100
    return subprocess.run(
        [sys.executable, "-I", "-m", "streamdock_n3.hardware.helper_main"],
        input="{}", capture_output=True, text=True, encoding="utf-8",
        errors="strict", check=False, timeout=timeout_ms / 1000)
''',
        filename=str(path),
    )

    assert _fixed_helper_violations(((path, tree),)) != []


@pytest.mark.parametrize(
    "source",
    (
        (
            "g_products = []\n(products,) = (g_products,)\n"
            "products.append((0x6602, 0x1000, Device))\n"
        ),
        (
            "g_products = []\n"
            "(products := g_products).append((0x6602, 0x1000, Device))\n"
        ),
        (
            "g_products = []\n(writer,) = (g_products.append,)\n"
            "writer((0x6602, 0x1000, Device))\n"
        ),
        "g_products = []\ng_products[0][0] = 0x6602\n",
        "g_products = []\nglobals()['g_products'].append((0x6602, 0x1000, Device))\n",
    ),
)
def test_candidate_mapping_gate_rejects_indirect_aliases_and_nested_writers(
    source: str,
) -> None:
    assert _candidate_product_mapping_violations(source) != []


@pytest.mark.parametrize(
    "rule",
    (
        'ATTR{idVendor}==e"6602", TAG+="uaccess"\n',
        'ATTR{idVendor}==e"\\x36\\x36\\x30\\x32", TAG+="uaccess"\n',
        'ATTRS{idVendor}==i"6602", TAG+="uaccess"\n',
        'ATTR{idVendor}==e"\\xZZ", TAG+="uaccess"\n',
    ),
)
def test_udev_gate_rejects_prefixed_escaped_or_unparseable_candidate_values(rule: str) -> None:
    assert _candidate_udev_rule_violations(rule) != []


@pytest.mark.parametrize("path", REVIEWED_SOURCE_PATHS)
def test_reviewed_source_snapshot_gate_rejects_any_covered_byte_mutation(path: Path) -> None:
    sources = {path: (ROOT / path).read_bytes() for path in REVIEWED_SOURCE_PATHS}
    assert _reviewed_source_snapshot_violations(sources) == []

    sources[path] += b"\n# unreviewed mutation\n"

    assert _reviewed_source_snapshot_violations(sources) == [path]


def test_complete_g0_source_closure_keeps_the_exact_brief_modules_and_dependencies() -> None:
    assert (
        Path("src/streamdock_n3/hardware/__init__.py"),
        Path("src/streamdock_n3/hardware/contracts.py"),
        Path("src/streamdock_n3/hardware/interface_roles.py"),
        Path("src/streamdock_n3/hardware/permissions.py"),
        Path("src/streamdock_n3/hardware/input_session.py"),
        Path("src/streamdock_n3/hardware/gate.py"),
        Path("src/streamdock_n3/hardware/backend.py"),
        Path("src/streamdock_n3/hardware/adapter.py"),
        Path("src/streamdock_n3/hardware/ipc.py"),
        Path("src/streamdock_n3/hardware/helper_main.py"),
        Path("src/streamdock_n3/hardware/evidence.py"),
    ) == G0_MODULES
    expected_dependencies = (
        Path("src/streamdock_n3/__init__.py"),
        Path("src/streamdock_n3/device_catalog.py"),
    )
    assert expected_dependencies == G0_DEPENDENCY_MODULES
    assert (*G0_MODULES, *expected_dependencies) == G0_SOURCE_CLOSURE


@pytest.mark.parametrize(
    "path",
    (
        Path("src/streamdock_n3/__init__.py"),
        Path("src/streamdock_n3/device_catalog.py"),
    ),
)
def test_dependency_modules_pass_every_static_source_gate(path: Path) -> None:
    source = _source(path)
    tree = ast.parse(source, filename=str(path))

    assert _forbidden_source_violations(path, source) == []
    assert _import_violations(path, tree) == []
    assert _call_violations(path, tree) == []
    assert _import_time_side_effect_violations(path, tree) == []


@pytest.mark.parametrize(
    "path",
    (
        Path("src/streamdock_n3/__init__.py"),
        Path("src/streamdock_n3/device_catalog.py"),
    ),
)
@pytest.mark.parametrize(
    "source",
    (
        "import os\nos.system('unsafe')\n",
        "open('/tmp/unsafe')\n",
        "import subprocess\nsubprocess.run(['unsafe'])\n",
        "__import__('unsafe')\n",
        "print('unexpected import-time side effect')\n",
        "import os\nos.environ['UNSAFE'] = '1'\n",
    ),
)
def test_dependency_static_gates_reject_import_time_unsafe_regressions(
    path: Path,
    source: str,
) -> None:
    tree = ast.parse(source, filename=str(path))

    assert (
        _import_violations(path, tree)
        or _call_violations(path, tree)
        or _import_time_side_effect_violations(path, tree)
    )


def test_reviewed_snapshot_has_the_exact_unique_sixteen_path_closure() -> None:
    expected_dependencies = (
        Path("src/streamdock_n3/__init__.py"),
        Path("src/streamdock_n3/device_catalog.py"),
    )
    expected = (
        *G0_MODULES,
        *expected_dependencies,
        Path("src/streamdock_n3/_vendor/StreamDock/ProductIDs.py"),
        Path("src/streamdock_n3/_data/99-streamdock.rules"),
        Path("pyproject.toml"),
    )

    assert expected == REVIEWED_SOURCE_PATHS
    assert len(REVIEWED_SOURCE_PATHS) == len(set(REVIEWED_SOURCE_PATHS)) == 16
    assert set(REVIEWED_SOURCE_SHA256) == set(REVIEWED_SOURCE_PATHS)


def test_wheel_reviewed_paths_include_packaged_closure_but_exclude_pyproject() -> None:
    assert REVIEWED_SOURCE_PATHS[:-1] == WHEEL_REVIEWED_PATHS
    assert Path("pyproject.toml") not in WHEEL_REVIEWED_PATHS


def test_wheel_byte_gate_rejects_a_mutated_archive_member() -> None:
    sources = {path: (ROOT / path).read_bytes() for path in WHEEL_REVIEWED_PATHS}
    members = {_wheel_member(path): content for path, content in sources.items()}
    mutated = Path("src/streamdock_n3/__init__.py")
    members[_wheel_member(mutated)] += b"\n# archive-only mutation\n"

    assert _wheel_reviewed_source_violations(members, sources) == [mutated]


def test_source_module_set_gate_rejects_an_extra_nested_python_module(tmp_path: Path) -> None:
    for path in G0_MODULES:
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("# reviewed fixture\n", encoding="utf-8")
    extra = Path("src/streamdock_n3/hardware/experimental/real_backend.py")
    destination = tmp_path / extra
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("# unreviewed backend\n", encoding="utf-8")

    assert _g0_module_set_violations(tmp_path) == [extra]


def test_wheel_byte_gate_rejects_an_extra_hardware_archive_member() -> None:
    sources = {path: (ROOT / path).read_bytes() for path in WHEEL_REVIEWED_PATHS}
    members = {_wheel_member(path): content for path, content in sources.items()}
    extra = Path("src/streamdock_n3/hardware/experimental/real_backend.py")
    members[_wheel_member(extra)] = b"# unreviewed backend\n"

    assert _wheel_reviewed_source_violations(members, sources) == [extra]
