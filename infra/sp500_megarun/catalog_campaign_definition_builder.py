"""Repository-only discovery and verification of campaign definitions."""

from __future__ import annotations

import ast
from collections import deque
import json
import os
from pathlib import Path
import re
from typing import Any

import yaml

from .catalog_campaign_definition_contract import (
    CatalogCampaignDefinitionEntryV1,
    CatalogCampaignDefinitionManifestV1,
    CatalogDefinitionRole,
    registry_entry_sha256,
)
from .catalog_campaign_registry import CatalogCampaignEntryV1


_ENGINE_ROOTS: dict[str, tuple[str, ...]] = {
    "optimized_catalog_v1": (
        "schemas/catalog_campaign_definition_manifest_v1.schema.json",
        "infra/sp500_megarun/catalog_campaign_registry.py",
        "infra/sp500_megarun/catalog_campaign_definition_contract.py",
        "infra/sp500_megarun/catalog_optimization_contract.py",
        "scripts/plan_sp500_optimized_catalog_run.py",
        ".github/workflows/catalog-optimized-run.yml",
    )
}
_DECLARED_PATH_KEYS = frozenset(
    {
        "$ref",
        "extends",
        "uses",
    }
)
_REPOSITORY_PREFIXES = (
    ".github/",
    "config/",
    "schemas/",
    "requirements/",
    "scripts/",
    "infra/",
)
_SHELL_PATH = re.compile(
    r"(?P<path>(?:\.\/)?(?:\.github|config|schemas|requirements|scripts|infra)/"
    r"[A-Za-z0-9_.\/-]+(?:\.jsonl|\.json|\.py|\.ya?ml|\.lock|\.txt|\.csv|"
    r"\.md|\.sh|\.ps1))(?=$|\s|['\"\\])"
)
_PYTHON_MODULE = re.compile(
    r"(?:python|python3|py)(?:\s+-[A-Za-z]+)*\s+-m\s+"
    r"(?P<module>[A-Za-z_][A-Za-z0-9_.]+)"
)
_PYTHON_HEREDOC = re.compile(
    r"(?:python|python3|py|\"\$[A-Za-z_][A-Za-z0-9_]*\")"
    r"(?:\s+-[A-Za-z]+)*\s+-\s+<<-?\s*['\"]?"
    r"(?P<tag>[A-Za-z_][A-Za-z0-9_]*)['\"]?[^\n]*\n"
    r"(?P<body>.*?)\n[ \t]*(?P=tag)[ \t]*(?=\n|$)",
    re.DOTALL,
)


class _ClosureBuilder:
    def __init__(self, repo_root: Path, registry_entry: CatalogCampaignEntryV1):
        self.root = repo_root.resolve(strict=True)
        if not self.root.is_dir() or repo_root.is_symlink():
            raise ValueError("CATALOG_DEFINITION_ROOT_INVALID")
        self.registry_entry = registry_entry
        self.pending: deque[str] = deque()
        self.roles: dict[str, CatalogDefinitionRole] = {}
        self.contents: dict[str, bytes] = {}

    def add(self, path: str, role: CatalogDefinitionRole | None = None) -> None:
        normalized = self._normalize_path(path)
        if normalized == self.registry_entry.definition_manifest_path:
            return
        selected_role = role or self._role_for(normalized)
        previous_role = self.roles.get(normalized)
        if previous_role is None:
            self.roles[normalized] = selected_role
            self.pending.append(normalized)
        elif previous_role != selected_role:
            self.roles[normalized] = self._stronger_role(previous_role, selected_role)

    def add_directory(
        self,
        path: str,
        role: CatalogDefinitionRole,
    ) -> None:
        directory = self._checked_path(path, require_file=False)
        if not directory.is_dir():
            raise ValueError(f"CATALOG_DEFINITION_EDGE_UNRESOLVED:{path}")
        for current_root, directories, files in os.walk(directory, followlinks=False):
            current = Path(current_root)
            for name in tuple(directories):
                child = current / name
                if child.is_symlink():
                    raise ValueError(
                        f"CATALOG_DEFINITION_SYMLINK_FORBIDDEN:{self._relative(child)}"
                    )
            for name in sorted(files):
                child = current / name
                if child.is_symlink():
                    raise ValueError(
                        f"CATALOG_DEFINITION_SYMLINK_FORBIDDEN:{self._relative(child)}"
                    )
                self.add(self._relative(child), role)

    def build(self) -> CatalogCampaignDefinitionManifestV1:
        self._add_roots()
        while self.pending:
            relative = self.pending.popleft()
            path = self._checked_path(relative, require_file=True)
            content = path.read_bytes()
            self.contents[relative] = content
            suffix = path.suffix.casefold()
            if suffix == ".py":
                self._scan_python(relative, content)
            elif suffix == ".json":
                self._scan_json(relative, content)
            elif suffix in {".yml", ".yaml"}:
                self._scan_yaml(relative, content)
        casefolded: dict[str, str] = {}
        for path in self.contents:
            prior = casefolded.setdefault(path.casefold(), path)
            if prior != path:
                raise ValueError(f"CATALOG_DEFINITION_CASE_COLLISION:{prior}:{path}")
        entries = tuple(
            CatalogCampaignDefinitionEntryV1.from_bytes(
                path=path,
                role=self.roles[path],
                content=self.contents[path],
            )
            for path in sorted(self.contents)
        )
        return CatalogCampaignDefinitionManifestV1(
            schema_version="1",
            closure_algorithm="aurora-catalog-transitive-closure-v1",
            campaign_key=self.registry_entry.campaign_key,
            registry_entry_sha256=registry_entry_sha256(self.registry_entry),
            entries=entries,
        )

    def _add_roots(self) -> None:
        role_by_field: dict[str, CatalogDefinitionRole] = {
            "optimization_policy_path": "configuration",
            "campaign_contract_path": "contract",
            "catalog_dir": "data_identity",
            "selected_config_path": "configuration",
            "admission_evidence_path": "configuration",
            "data_contract_path": "data_identity",
            "feature_contract_path": "data_identity",
        }
        for field, role in role_by_field.items():
            value = getattr(self.registry_entry, field)
            checked = self._checked_path(value, require_file=False)
            if checked.is_dir():
                self.add_directory(value, role)
            else:
                self.add(value, role)
        roots = _ENGINE_ROOTS.get(self.registry_entry.engine_id)
        if roots is None:
            raise ValueError("CATALOG_DEFINITION_ENGINE_UNSUPPORTED")
        for path in roots:
            self.add(path)

    def _scan_json(self, relative: str, content: bytes) -> None:
        try:
            payload = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"CATALOG_DEFINITION_JSON_INVALID:{relative}:{exc}") from None

        def walk(value: object, key: str | None = None) -> None:
            if isinstance(value, dict):
                for child_key, child in value.items():
                    walk(child, str(child_key))
            elif isinstance(value, list):
                for child in value:
                    walk(child, key)
            elif isinstance(value, str):
                self._consider_string_edge(relative, key, value)

        walk(payload)

    def _scan_yaml(self, relative: str, content: bytes) -> None:
        try:
            payload = yaml.safe_load(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ValueError(f"CATALOG_DEFINITION_YAML_INVALID:{relative}:{exc}") from None

        def walk(value: object, key: str | None = None) -> None:
            if isinstance(value, dict):
                for child_key, child in value.items():
                    walk(child, str(child_key))
            elif isinstance(value, list):
                for child in value:
                    walk(child, key)
            elif isinstance(value, str):
                if key == "run":
                    self._scan_shell(relative, value)
                else:
                    self._consider_string_edge(relative, key, value)

        walk(payload)

    def _scan_shell(self, current: str, command: str) -> None:
        for match in _SHELL_PATH.finditer(command):
            self.add(match.group("path").removeprefix("./"))
        for match in _PYTHON_MODULE.finditer(command):
            module = match.group("module")
            resolved = self._resolve_module(module, current=None)
            if resolved is None and self._is_local_module(module):
                raise ValueError(
                    "CATALOG_DEFINITION_EDGE_UNRESOLVED:"
                    + module
                )
            if resolved is not None:
                self.add(resolved, "science_code")
        for match in _PYTHON_HEREDOC.finditer(command):
            self._scan_python(
                current,
                match.group("body").encode("utf-8"),
            )

    def _scan_python(self, relative: str, content: bytes) -> None:
        try:
            tree = ast.parse(content.decode("utf-8-sig"), filename=relative)
        except (UnicodeDecodeError, SyntaxError) as exc:
            raise ValueError(f"CATALOG_DEFINITION_PYTHON_INVALID:{relative}:{exc}") from None
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    resolved = self._resolve_module(alias.name, current=relative)
                    if resolved is not None:
                        self.add(resolved, "science_code")
                    elif self._is_local_module(alias.name) and not self._optional_import(
                        node, parents
                    ):
                        raise ValueError(
                            f"CATALOG_DEFINITION_EDGE_UNRESOLVED:{relative}:{alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = self._absolute_import_from(relative, node)
                if module:
                    resolved = self._resolve_module(module, current=relative)
                    if resolved is not None:
                        self.add(resolved, "science_code")
                    elif self._is_local_module(module) and not self._optional_import(
                        node, parents
                    ):
                        raise ValueError(
                            f"CATALOG_DEFINITION_EDGE_UNRESOLVED:{relative}:{module}"
                        )
                elif node.level:
                    for alias in node.names:
                        candidate = self._absolute_relative_alias(relative, node.level, alias.name)
                        resolved = self._resolve_module(candidate, current=relative)
                        if resolved is not None:
                            self.add(resolved, "science_code")
                        elif not self._optional_import(node, parents):
                            raise ValueError(
                                f"CATALOG_DEFINITION_EDGE_UNRESOLVED:{relative}:{candidate}"
                            )
            elif isinstance(node, ast.Call) and self._is_dynamic_import_call(node):
                modules = self._resolve_dynamic_import_modules(tree, node)
                if modules is None:
                    raise ValueError(
                        f"CATALOG_DEFINITION_DYNAMIC_EDGE_UNRESOLVED:{relative}"
                    )
                for module in modules:
                    resolved = self._resolve_module(module, current=relative)
                    if resolved is not None:
                        self.add(resolved, "science_code")
                    elif self._is_local_module(module):
                        raise ValueError(
                            f"CATALOG_DEFINITION_EDGE_UNRESOLVED:{relative}:{module}"
                        )
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                self._consider_string_edge(relative, None, node.value)

    def _consider_string_edge(
        self,
        current: str,
        key: str | None,
        value: str,
    ) -> None:
        if not value or "://" in value or "${{" in value:
            return
        declared = key in _DECLARED_PATH_KEYS or bool(key and key.endswith("_path"))
        raw = value.split("#", 1)[0] if key == "$ref" else value
        if raw.startswith(_REPOSITORY_PREFIXES) and raw.endswith("/"):
            raw = raw.rstrip("/")
        if not raw:
            return
        if key == "uses" and raw.startswith("./"):
            raw = raw.removeprefix("./")
            target = self._checked_path(raw, require_file=False, allow_missing=True)
            if target.is_dir():
                for action_name in ("action.yml", "action.yaml"):
                    action = target / action_name
                    if action.is_symlink():
                        raise ValueError(
                            f"CATALOG_DEFINITION_SYMLINK_FORBIDDEN:{raw}/{action_name}"
                        )
                    if action.is_file():
                        self.add(self._relative(action), "workflow")
                        return
                raise ValueError(f"CATALOG_DEFINITION_EDGE_UNRESOLVED:{raw}")
            self.add(raw, "workflow")
            return
        if key == "uses":
            if re.fullmatch(
                r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
                r"(?:/[A-Za-z0-9_.-]+)*@[0-9a-f]{40}",
                raw,
            ):
                return
            raise ValueError(
                f"CATALOG_DEFINITION_EXTERNAL_EDGE_UNPINNED:{current}:{value}"
            )
        if key == "extends" and "/" not in raw:
            raw = str((Path(current).parent / raw).as_posix())
            declared = True
        elif key == "$ref" and not raw.startswith(_REPOSITORY_PREFIXES):
            raw = str((Path(current).parent / raw).as_posix())
            declared = True
        elif raw.startswith("./"):
            raw = raw.removeprefix("./")
        elif not raw.startswith(_REPOSITORY_PREFIXES):
            if not declared:
                return
            candidate = Path(current).parent / raw
            if (self.root / candidate).exists():
                raw = candidate.as_posix()
            elif not (self.root / raw).exists():
                raise ValueError(
                    f"CATALOG_DEFINITION_EDGE_UNRESOLVED:{current}:{value}"
                )
        if not raw:
            return
        target = self._checked_path(raw, require_file=False, allow_missing=True)
        if target.is_file():
            self.add(raw)
        elif target.is_dir() and declared:
            self.add_directory(raw, self._role_for(raw))
        elif declared:
            raise ValueError(f"CATALOG_DEFINITION_EDGE_UNRESOLVED:{current}:{value}")

    def _resolve_module(self, module: str, current: str | None) -> str | None:
        del current
        parts = module.split(".")
        if parts[0] == "aurora":
            parts = parts[1:]
        candidates = (
            "/".join(parts) + ".py",
            "/".join(parts) + "/__init__.py",
        )
        for candidate in candidates:
            path = self.root / candidate
            if path.is_file():
                return candidate
        return None

    def _absolute_import_from(self, current: str, node: ast.ImportFrom) -> str | None:
        if node.level == 0:
            return node.module
        package = list(Path(current).with_suffix("").parts[:-1])
        if node.level > len(package):
            return None
        base = package[: len(package) - node.level + 1]
        if node.module:
            base.extend(node.module.split("."))
        return ".".join(base)

    def _absolute_relative_alias(self, current: str, level: int, alias: str) -> str:
        package = list(Path(current).with_suffix("").parts[:-1])
        base = package[: len(package) - level + 1]
        base.append(alias)
        return ".".join(base)

    @staticmethod
    def _is_dynamic_import_call(node: ast.Call) -> bool:
        function = node.func
        return (
            isinstance(function, ast.Name)
            and function.id == "__import__"
            or isinstance(function, ast.Attribute)
            and function.attr == "import_module"
        )

    def _resolve_dynamic_import_modules(
        self,
        tree: ast.Module,
        node: ast.Call,
    ) -> tuple[str, ...] | None:
        if not node.args:
            return None
        argument = node.args[0]
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            return (argument.value,)
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        owner = self._enclosing_function(parents, node)
        globals_ = self._literal_string_collections(tree)
        prefix = ""
        suffix = ""
        dynamic_expression: ast.Name
        if isinstance(argument, ast.Name):
            dynamic_expression = argument
        elif isinstance(argument, ast.JoinedStr):
            dynamic_nodes = [
                value.value
                for value in argument.values
                if isinstance(value, ast.FormattedValue)
                and isinstance(value.value, ast.Name)
            ]
            if len(dynamic_nodes) != 1:
                return None
            dynamic_expression = dynamic_nodes[0]
            static_parts: list[str | None] = []
            for value in argument.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    static_parts.append(value.value)
                elif (
                    isinstance(value, ast.FormattedValue)
                    and value.value is dynamic_expression
                ):
                    static_parts.append(None)
                else:
                    return None
            if static_parts.count(None) != 1:
                return None
            marker = static_parts.index(None)
            prefix = "".join(
                part for part in static_parts[:marker] if part is not None
            )
            suffix = "".join(
                part for part in static_parts[marker + 1 :] if part is not None
            )
        else:
            return None

        if owner is not None and dynamic_expression.id in {
            item.arg for item in owner.args.args
        }:
            allowed = self._closed_private_parameter_values(
                tree,
                owner,
                dynamic_expression.id,
            )
        else:
            allowed = self._static_string_values(
                dynamic_expression,
                owner,
                parents,
                globals_,
                {},
            )
        if not allowed:
            return None
        return tuple(f"{prefix}{value}{suffix}" for value in sorted(allowed))

    @staticmethod
    def _optional_import(
        node: ast.Import | ast.ImportFrom,
        parents: dict[ast.AST, ast.AST],
    ) -> bool:
        current: ast.AST = node
        parent = parents.get(current)
        while parent is not None:
            if isinstance(parent, ast.Try) and any(
                any(child is node for child in ast.walk(statement))
                for statement in parent.body
            ):
                for handler in parent.handlers:
                    caught = handler.type
                    if caught is None:
                        return True
                    names = (
                        tuple(item.id for item in caught.elts if isinstance(item, ast.Name))
                        if isinstance(caught, ast.Tuple)
                        else (caught.id,)
                        if isinstance(caught, ast.Name)
                        else ()
                    )
                    if set(names) & {"Exception", "ImportError", "ModuleNotFoundError"}:
                        return True
            current = parent
            parent = parents.get(current)
        return False

    @staticmethod
    def _literal_string_collections(tree: ast.Module) -> dict[str, frozenset[str]]:
        collections: dict[str, frozenset[str]] = {}
        for statement in tree.body:
            value: ast.expr | None = None
            names: tuple[str, ...] = ()
            if isinstance(statement, ast.Assign):
                value = statement.value
                names = tuple(
                    target.id
                    for target in statement.targets
                    if isinstance(target, ast.Name)
                )
            elif isinstance(statement, ast.AnnAssign) and isinstance(
                statement.target, ast.Name
            ):
                value = statement.value
                names = (statement.target.id,)
            if not names:
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                items = (value.value,)
            elif isinstance(value, (ast.Tuple, ast.List, ast.Set)):
                items = tuple(
                    item.value
                    for item in value.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                )
                if len(items) != len(value.elts):
                    continue
            else:
                continue
            if not items or len(items) != len(set(items)):
                continue
            for name in names:
                collections[name] = frozenset(items)
        return collections

    def _closed_private_parameter_values(
        self,
        tree: ast.Module,
        owner: ast.FunctionDef | ast.AsyncFunctionDef,
        parameter: str,
    ) -> frozenset[str] | None:
        functions = {
            statement.name: statement
            for statement in tree.body
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if owner.name not in functions or not owner.name.startswith("_"):
            return None
        exported = self._literal_string_collections(tree).get("__all__", frozenset())
        if owner.name in exported:
            return None

        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        calls: dict[str, list[ast.Call]] = {name: [] for name in functions}
        escaped: set[str] = set()
        for candidate in ast.walk(tree):
            if not isinstance(candidate, ast.Name) or not isinstance(
                candidate.ctx, ast.Load
            ):
                continue
            if candidate.id not in functions:
                continue
            parent = parents.get(candidate)
            if not (
                isinstance(parent, ast.Call)
                and parent.func is candidate
            ):
                escaped.add(candidate.id)
            else:
                calls[candidate.id].append(parent)

        globals_ = self._literal_string_collections(tree)
        domains: dict[tuple[str, str], frozenset[str]] = {}
        complete: dict[tuple[str, str], bool] = {}
        for _ in range(len(functions) + 1):
            changed = False
            for function_name, function in functions.items():
                parameters = tuple(argument.arg for argument in function.args.args)
                for index, name in enumerate(parameters):
                    key = (function_name, name)
                    values: set[str] = set()
                    is_complete = bool(calls[function_name]) and function_name not in escaped
                    for call in calls[function_name]:
                        expression = self._call_argument(call, function, index, name)
                        if expression is None:
                            is_complete = False
                            continue
                        caller = self._enclosing_function(parents, call)
                        resolved = self._static_string_values(
                            expression,
                            caller,
                            parents,
                            globals_,
                            domains,
                        )
                        if resolved is None:
                            is_complete = False
                        else:
                            values.update(resolved)
                    frozen = frozenset(values)
                    if frozen and domains.get(key) != frozen:
                        domains[key] = frozen
                        changed = True
                    complete[key] = is_complete
            if not changed:
                break
        key = (owner.name, parameter)
        if not complete.get(key):
            return None
        return domains.get(key)

    @staticmethod
    def _call_argument(
        call: ast.Call,
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        index: int,
        name: str,
    ) -> ast.expr | None:
        if index < len(call.args):
            return call.args[index]
        for keyword in call.keywords:
            if keyword.arg == name:
                return keyword.value
        default_offset = len(function.args.args) - len(function.args.defaults)
        if index >= default_offset:
            return function.args.defaults[index - default_offset]
        return None

    @staticmethod
    def _enclosing_function(
        parents: dict[ast.AST, ast.AST],
        node: ast.AST,
    ) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        current = parents.get(node)
        while current is not None:
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return current
            current = parents.get(current)
        return None

    def _static_string_values(
        self,
        expression: ast.expr,
        caller: ast.FunctionDef | ast.AsyncFunctionDef | None,
        parents: dict[ast.AST, ast.AST],
        globals_: dict[str, frozenset[str]],
        domains: dict[tuple[str, str], frozenset[str]],
    ) -> frozenset[str] | None:
        if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
            return frozenset((expression.value,))
        if isinstance(expression, (ast.Tuple, ast.List, ast.Set)):
            values = tuple(
                item.value
                for item in expression.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
            if len(values) == len(expression.elts) and values:
                return frozenset(values)
            return None
        if not isinstance(expression, ast.Name):
            return None
        if expression.id in globals_:
            return globals_[expression.id]
        if caller is not None:
            parameter_domain = domains.get((caller.name, expression.id))
            if parameter_domain is not None:
                return parameter_domain
        current: ast.AST | None = expression
        while current is not None and current is not caller:
            if isinstance(
                current,
                (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp),
            ):
                for generator in current.generators:
                    if (
                        isinstance(generator.target, ast.Name)
                        and generator.target.id == expression.id
                    ):
                        return self._static_string_values(
                            generator.iter,
                            caller,
                            parents,
                            globals_,
                            domains,
                        )
            elif (
                isinstance(current, (ast.For, ast.AsyncFor))
            ):
                if (
                    isinstance(current.target, ast.Name)
                    and current.target.id == expression.id
                ):
                    return self._static_string_values(
                        current.iter,
                        caller,
                        parents,
                        globals_,
                        domains,
                    )
                if isinstance(current.target, (ast.Tuple, ast.List)):
                    indexes = [
                        index
                        for index, target in enumerate(current.target.elts)
                        if isinstance(target, ast.Name) and target.id == expression.id
                    ]
                    if len(indexes) == 1 and isinstance(
                        current.iter, (ast.Tuple, ast.List)
                    ):
                        index = indexes[0]
                        values: list[str] = []
                        for row in current.iter.elts:
                            if not isinstance(row, (ast.Tuple, ast.List)) or index >= len(
                                row.elts
                            ):
                                return None
                            value = row.elts[index]
                            if not isinstance(value, ast.Constant) or not isinstance(
                                value.value, str
                            ):
                                return None
                            values.append(value.value)
                        if values:
                            return frozenset(values)
            current = parents.get(current)
        return None

    def _is_local_module(self, module: str) -> bool:
        first = module.split(".", 1)[0]
        if first == "aurora":
            return True
        return (self.root / first).exists()

    def _normalize_path(self, value: str) -> str:
        try:
            checked = CatalogCampaignDefinitionEntryV1.from_bytes(
                path=value,
                role="configuration",
                content=b"",
            )
            return checked.path
        except Exception:
            raise ValueError(f"CATALOG_DEFINITION_PATH_INVALID:{value}") from None

    def _checked_path(
        self,
        relative: str,
        *,
        require_file: bool,
        allow_missing: bool = False,
    ) -> Path:
        normalized = self._normalize_path(relative)
        candidate = self.root.joinpath(*normalized.split("/"))
        current = self.root
        for part in normalized.split("/"):
            current = current / part
            if current.is_symlink():
                raise ValueError(
                    f"CATALOG_DEFINITION_SYMLINK_FORBIDDEN:{normalized}"
                )
        if not candidate.exists():
            if allow_missing:
                return candidate
            raise ValueError(f"CATALOG_DEFINITION_EDGE_UNRESOLVED:{normalized}")
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise ValueError(
                f"CATALOG_DEFINITION_PATH_ESCAPES_ROOT:{normalized}"
            ) from None
        if require_file and not resolved.is_file():
            raise ValueError(f"CATALOG_DEFINITION_EDGE_UNRESOLVED:{normalized}")
        return resolved

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve(strict=False).relative_to(self.root).as_posix()
        except ValueError:
            raise ValueError("CATALOG_DEFINITION_PATH_ESCAPES_ROOT") from None

    @staticmethod
    def _role_for(path: str) -> CatalogDefinitionRole:
        lower = path.casefold()
        if lower.startswith(".github/"):
            return "workflow"
        if lower.startswith("schemas/") or ".schema." in lower:
            return "schema"
        if lower.endswith(".py") or lower.endswith((".sh", ".ps1")):
            return "science_code"
        if lower.startswith("requirements/") or "contract" in lower:
            return "contract"
        if (
            "free_data" in lower
            or "feature_contract" in lower
            or "strategy_catalog" in lower
        ):
            return "data_identity"
        return "configuration"

    @staticmethod
    def _stronger_role(
        left: CatalogDefinitionRole,
        right: CatalogDefinitionRole,
    ) -> CatalogDefinitionRole:
        priority = {
            "configuration": 0,
            "data_identity": 1,
            "contract": 2,
            "schema": 3,
            "workflow": 4,
            "science_code": 5,
        }
        return left if priority[left] >= priority[right] else right


def discover_catalog_campaign_definition(
    *,
    repo_root: Path,
    registry_entry: CatalogCampaignEntryV1,
) -> CatalogCampaignDefinitionManifestV1:
    return _ClosureBuilder(repo_root, registry_entry).build()


def verify_catalog_campaign_definition(
    *,
    repo_root: Path,
    registry_entry: CatalogCampaignEntryV1,
    manifest: CatalogCampaignDefinitionManifestV1,
) -> CatalogCampaignDefinitionManifestV1:
    expected_row_hash = registry_entry_sha256(registry_entry)
    if manifest.registry_entry_sha256 != expected_row_hash:
        raise ValueError("CATALOG_REGISTRY_ROW_MISMATCH")
    discovered = discover_catalog_campaign_definition(
        repo_root=repo_root,
        registry_entry=registry_entry,
    )
    if discovered != manifest:
        raise ValueError("CATALOG_CAMPAIGN_DEFINITION_MISMATCH")
    return discovered


__all__ = [
    "discover_catalog_campaign_definition",
    "verify_catalog_campaign_definition",
]
