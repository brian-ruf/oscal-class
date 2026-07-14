import dataclasses
import importlib
import importlib.util
import inspect
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

# tomllib is stdlib on 3.11+; fall back to tomli, then a minimal parser.
try:
    import tomllib as _toml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - depends on Python version
    try:
        import tomli as _toml  # type: ignore
    except ModuleNotFoundError:
        _toml = None


def find_pyproject(package_dir: str) -> Optional[Path]:
    """Locate the nearest pyproject.toml at or above the package directory.

    Searches the package directory itself and each parent directory.

    Args:
        package_dir (str, required): The library package directory being documented.

    Returns:
        Optional[Path]: Path to the first pyproject.toml found, or None.
    """
    start = Path(package_dir).resolve()
    for candidate in (start, *start.parents):
        pyproject = candidate / "pyproject.toml"
        if pyproject.is_file():
            return pyproject
    return None


def read_project_metadata(package_dir: str) -> Tuple[Optional[str], Optional[str]]:
    """Read the project name and version from the nearest pyproject.toml.

    Args:
        package_dir (str, required): The library package directory being documented.

    Returns:
        Tuple[Optional[str], Optional[str]]: (name, version); either element is None
            when unavailable or unparseable.
    """
    pyproject = find_pyproject(package_dir)
    if pyproject is None:
        return None, None

    try:
        if _toml is not None:
            with pyproject.open("rb") as fh:
                data = _toml.load(fh)
            project = data.get("project", {})
            return project.get("name"), project.get("version")

        # Minimal fallback: scan the [project] table for name/version.
        name = version = None
        in_project = False
        for raw in pyproject.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                in_project = line == "[project]"
                continue
            if not in_project or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key == "name":
                name = value
            elif key == "version":
                version = value
        return name, version
    except Exception as e:
        print(f"Warning: Could not read project metadata from {pyproject}: {e}")
        return None, None


def get_target_modules(package_dir: str) -> List[str]:
    """
    Scans a directory to determine which modules to document.

    Checks __init__.py for an __all__ list and keeps only the entries that resolve
    to importable submodules (class, function, and constant names in __all__ are
    documented under their defining module, so they are skipped here). Falls back to
    scanning all *.py files when __all__ is absent.

    Args:
        package_dir (str, required): The library package directory to scan.

    Returns:
        List[str]: Fully-qualified module names to document.
    """
    path = Path(package_dir).resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"The directory {package_dir} does not exist.")

    # Ensure the parent directory is in sys.path so imports resolve correctly
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))

    package_name = path.name
    init_file = path / "__init__.py"

    # Strategy 1: Check __init__.py for defined public modules via __all__
    if init_file.exists():
        try:
            spec = importlib.util.spec_from_file_location(package_name, str(init_file))
            if spec and spec.loader:
                init_mod = importlib.util.module_from_spec(spec)
                # Register before executing so intra-package imports resolve.
                sys.modules[package_name] = init_mod
                spec.loader.exec_module(init_mod)

                if hasattr(init_mod, "__all__") and init_mod.__all__:
                    modules = []
                    for name in init_mod.__all__:
                        full_name = f"{package_name}.{name}"
                        # Keep the entry only if it is an actual submodule. Class,
                        # function, and constant names in __all__ are documented via
                        # the module that defines them, so they are not modules here.
                        if importlib.util.find_spec(full_name) is not None:
                            modules.append(full_name)
                    if modules:
                        return modules
        except Exception as e:
            print(f"Warning: Could not parse __init__.py  successfully: {e}. Falling back to file scan.")

    # Strategy 2: Fallback to scanning all *.py files in the folder
    modules = []
    for file in path.glob("*.py"):
        if file.name == "__init__.py":
            continue
        modules.append(f"{package_name}.{file.stem}")

    return sorted(modules)


def _defined_in_package(obj, package_name: str) -> bool:
    """Return True when a callable/property is defined within the documented package."""
    mod = getattr(obj, "__module__", "") or ""
    return mod == package_name or mod.startswith(package_name + ".")


def _iter_documentable_members(cls, package_name: str):
    """Yield (name, kind, doc, signature) for the documentable members of a class.

    Covers regular methods, classmethods, staticmethods, and properties (which the
    plain ``inspect.isfunction`` scan misses). Members inherited from outside the
    documented package are skipped so third-party mixins do not leak in.

    Args:
        cls (type, required): The class to inspect.
        package_name (str, required): Top-level package name used to filter members.

    Yields:
        tuple: ``(name, kind, doc, signature_str_or_None)`` for each member, where
            ``kind`` is one of "method", "classmethod", "staticmethod", or "property".
    """
    is_dataclass = dataclasses.is_dataclass(cls)
    for name in sorted(dir(cls)):
        # Filter out private/dunder members, but preserve __init__.
        if name.startswith("_") and name != "__init__":
            continue
        # Skip the __init__ synthesized by @dataclass — its fields are described in
        # the class docstring, and the generated method carries no docstring.
        if name == "__init__" and is_dataclass:
            continue

        try:
            raw = inspect.getattr_static(cls, name)
        except AttributeError:
            continue

        kind = None
        func = None
        if isinstance(raw, classmethod):
            kind, func = "classmethod", raw.__func__
        elif isinstance(raw, staticmethod):
            kind, func = "staticmethod", raw.__func__
        elif isinstance(raw, property):
            kind, func = "property", raw.fget
        elif inspect.isfunction(raw):
            kind, func = "method", raw
        else:
            continue  # skip data attributes and anything unrecognized

        if func is None or not _defined_in_package(func, package_name):
            continue

        doc = func.__doc__.strip() if func.__doc__ else "No documentation provided."

        sig = None
        if kind != "property":
            try:
                sig = str(inspect.signature(func))
            except (ValueError, TypeError):
                sig = None

        yield name, kind, doc, sig


def generate_flat_docs(package_dir: str, output_file: str):
    """
    Automatically detects library modules, flattens class/method hierarchies,
    and writes a token-optimized Markdown context file for LLMs.

    The header records the library name and version (from pyproject.toml when
    available) and a UTC generation timestamp.

    Args:
        package_dir (str, required): The library package directory to document.
        output_file (str, required): Path of the Markdown file to write.

    Returns:
        None
    """
    try:
        module_names = get_target_modules(package_dir)
    except Exception as e:
        print(f"Error initializing module scan: {e}")
        return

    package_name = Path(package_dir).resolve().name
    project_name, project_version = read_project_metadata(package_dir)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    title = project_name or package_name
    header = [f"# {title} — Library Documentation API Context"]
    if project_version:
        header.append(f"**Version:** {project_version}")
    header.append(f"**Generated:** {generated_at}")
    header.append(f"Generated from: `{package_dir}`\n")
    markdown_output = ["\n".join(header)]

    for mod_name in module_names:
        try:
            mod = importlib.import_module(mod_name)
            markdown_output.append(f"# Module: {mod_name}\n")
            if mod.__doc__:
                markdown_output.append(f"{mod.__doc__.strip()}\n")

            for class_name, cls in inspect.getmembers(mod, inspect.isclass):
                # Only document classes explicitly belonging to this module
                if cls.__module__ != mod_name:
                    continue

                markdown_output.append(f"## Class: {class_name}")
                if cls.__doc__:
                    markdown_output.append(f"{cls.__doc__.strip()}\n")

                markdown_output.append("### Available Members\n")

                members = list(_iter_documentable_members(cls, package_name))
                if not members:
                    markdown_output.append("*No public members available.*\n")
                    continue

                for name, kind, doc, sig in members:
                    if kind == "property":
                        markdown_output.append(f"#### `property {name}`")
                    elif kind == "classmethod":
                        markdown_output.append(f"#### `classmethod def {name}{sig}`")
                    elif kind == "staticmethod":
                        markdown_output.append(f"#### `staticmethod def {name}{sig}`")
                    else:
                        markdown_output.append(f"#### `def {name}{sig}`")
                    markdown_output.append(f"{doc}\n")

            # Document module-level functions defined in this module.
            module_funcs = [
                (n, f) for n, f in inspect.getmembers(mod, inspect.isfunction)
                if f.__module__ == mod_name and not n.startswith("_")
            ]
            if module_funcs:
                markdown_output.append("## Module Functions\n")
                for func_name, func_obj in module_funcs:
                    try:
                        sig = inspect.signature(func_obj)
                    except (ValueError, TypeError):
                        continue
                    doc = func_obj.__doc__.strip() if func_obj.__doc__ else "No documentation provided."
                    markdown_output.append(f"#### `def {func_name}{sig}`")
                    markdown_output.append(f"{doc}\n")

        except Exception as e:
            markdown_output.append(f"### Error parsing module {mod_name}: {str(e)}\n")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(markdown_output))
    print(f"Success! Documented {len(module_names)} modules into '{output_file}'.")


# --- Run Configuration ---
if __name__ == "__main__":
    # Point this to your target code directory (e.g., "src/my_library" or "my_library")
    TARGET_FOLDER = "./oscal"
    OUTPUT_MARKDOWN = "./docs/llm_flat_api_docs.md"

    generate_flat_docs(TARGET_FOLDER, OUTPUT_MARKDOWN)
