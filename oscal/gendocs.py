"""Generate API-reference HTML for a Python package by introspection.

Discovers the package's public modules, classes, methods, and functions (with
signatures and docstrings) and renders one of two self-contained HTML documents:

* ``--mode llm``   — a flat, low-noise, machine-parseable reference optimized for
  consumption by agentic AI coding tools (stable ids, ``data-*`` attributes, a
  complete symbol index, docstrings preserved verbatim).
* ``--mode human`` — a styled, navigable reference for people (sticky sidebar,
  live filter, anchored headings, responsive layout).

Both are standalone HTML files intended to be published as static pages, e.g. by
a CI/CD job that runs this script once per mode:

    python -m oscal.gendocs --mode llm   --output docs/api-llm.html
    python -m oscal.gendocs --mode human --output docs/api.html
"""
from __future__ import annotations

import argparse
import dataclasses
import html
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


# ===========================================================================
# Project metadata / module discovery
# ===========================================================================
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


# ===========================================================================
# API model (built once, rendered per mode)
# ===========================================================================
def collect_api(package_dir: str) -> dict:
    """Introspect ``package_dir`` and return a structured API model.

    The model is a plain dict tree (project metadata + modules -> classes ->
    members, plus module-level functions), suitable for rendering to any format.

    Args:
        package_dir (str, required): The library package directory to document.

    Returns:
        dict: ``{"project_name", "package_name", "version", "generated",
            "package_dir", "modules": [...]}``.
    """
    module_names = get_target_modules(package_dir)
    package_name = Path(package_dir).resolve().name
    project_name, project_version = read_project_metadata(package_dir)

    data = {
        "project_name": project_name or package_name,
        "package_name": package_name,
        "version": project_version,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "package_dir": str(package_dir),
        "modules": [],
    }

    for mod_name in module_names:
        try:
            mod = importlib.import_module(mod_name)
        except Exception as e:  # keep going; record the failure in-band
            data["modules"].append({"name": mod_name, "doc": "", "error": str(e),
                                    "classes": [], "functions": []})
            continue

        module_entry = {"name": mod_name, "doc": (mod.__doc__ or "").strip(),
                        "classes": [], "functions": []}

        for class_name, cls in inspect.getmembers(mod, inspect.isclass):
            if cls.__module__ != mod_name:
                continue
            members = [{"name": n, "kind": k, "doc": d, "signature": s or ""}
                       for (n, k, d, s) in _iter_documentable_members(cls, package_name)]
            module_entry["classes"].append(
                {"name": class_name, "doc": (cls.__doc__ or "").strip(), "members": members})

        for func_name, func_obj in inspect.getmembers(mod, inspect.isfunction):
            if func_obj.__module__ != mod_name or func_name.startswith("_"):
                continue
            try:
                sig = str(inspect.signature(func_obj))
            except (ValueError, TypeError):
                continue
            doc = func_obj.__doc__.strip() if func_obj.__doc__ else "No documentation provided."
            module_entry["functions"].append({"name": func_name, "signature": sig, "doc": doc})

        data["modules"].append(module_entry)

    return data


def _counts(data: dict) -> Tuple[int, int, int, int]:
    """Return ``(modules, classes, members, functions)`` counts for the model."""
    modules = len(data["modules"])
    classes = sum(len(m["classes"]) for m in data["modules"])
    members = sum(len(c["members"]) for m in data["modules"] for c in m["classes"])
    funcs = sum(len(m["functions"]) for m in data["modules"])
    return modules, classes, members, funcs


def _member_signature(member: dict) -> str:
    """Render a member's declaration line (kind + name + signature)."""
    name, kind, sig = member["name"], member["kind"], member.get("signature", "")
    if kind == "property":
        return f"property {name}"
    if kind == "classmethod":
        return f"classmethod {name}{sig}"
    if kind == "staticmethod":
        return f"staticmethod {name}{sig}"
    return f"def {name}{sig}"


_esc = html.escape


# ===========================================================================
# LLM-oriented renderer
# ===========================================================================
_LLM_STYLE = (
    "body{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;line-height:1.5;"
    "max-width:64rem;margin:1.5rem auto;padding:0 1rem;color:#111}"
    "h1{font-size:1.4rem}h2{font-size:1.15rem;margin-top:2rem;border-bottom:1px solid #ccc}"
    "h3{font-size:1rem;margin-top:1.3rem}h4{font-size:.95rem;margin:.9rem 0 .2rem}"
    ".sig{background:#eef;padding:.15rem .4rem;border-radius:3px}"
    "pre.doc{white-space:pre-wrap;margin:.2rem 0 .7rem;padding:.4rem .6rem;background:#f6f6f6;"
    "border-left:3px solid #bbb;overflow-x:auto}"
    "a{color:#0645ad;text-decoration:none}a:hover{text-decoration:underline}"
    "#index ul{margin:.2rem 0;padding-left:1.1rem}.muted{color:#666}"
)


def _llm_doc_block(doc: str) -> str:
    return f'<pre class="doc">{_esc(doc)}</pre>' if doc else ""


def render_llm_html(data: dict) -> str:
    """Render the API model as a flat, machine-parseable HTML document for agents.

    Design goals: a single predictable structure, stable ``id`` anchors and
    ``data-*`` attributes on every symbol, a complete up-front symbol index, and
    docstrings preserved verbatim — with minimal styling/markup noise.

    Args:
        data (dict, required): The API model from :func:`collect_api`.

    Returns:
        str: A complete standalone HTML document.
    """
    modules, classes, members, funcs = _counts(data)
    title = data["project_name"]
    version = data.get("version") or ""

    out: List[str] = []
    out.append("<!DOCTYPE html>")
    out.append('<html lang="en"><head><meta charset="utf-8">')
    out.append(f"<title>{_esc(title)} API reference (LLM)</title>")
    out.append('<meta name="robots" content="index,follow">')
    out.append('<meta name="generator" content="oscal.gendocs">')
    out.append('<meta name="doc-format" content="llm">')
    out.append(f"<style>{_LLM_STYLE}</style></head><body>")

    # Header / provenance
    out.append("<header>")
    out.append(f"<h1>{_esc(title)} — API reference</h1>")
    meta = " · ".join(filter(None, [
        f"version {_esc(version)}" if version else "",
        f"generated {_esc(data['generated'])}",
        f"{modules} modules, {classes} classes, {members} methods, {funcs} functions",
    ]))
    out.append(f'<p class="muted">{meta}</p>')
    out.append("<p>Machine-oriented API reference for automated (agentic) consumption. "
               "Every symbol carries a stable <code>id</code> (its fully-qualified name) "
               "and <code>data-*</code> attributes; docstrings are preserved verbatim.</p>")
    out.append("</header>")

    # Complete symbol index
    out.append('<section id="index"><h2>Index</h2><ul>')
    for module in data["modules"]:
        mid = module["name"]
        out.append(f'<li><a href="#{_esc(mid)}">{_esc(mid)}</a>')
        if module["classes"] or module["functions"]:
            out.append("<ul>")
            for cls in module["classes"]:
                cid = f'{mid}.{cls["name"]}'
                out.append(f'<li><a href="#{_esc(cid)}">class {_esc(cls["name"])}</a>')
                if cls["members"]:
                    out.append("<ul>")
                    for m in cls["members"]:
                        pid = f'{cid}.{m["name"]}'
                        out.append(f'<li><a href="#{_esc(pid)}">{_esc(m["name"])}</a></li>')
                    out.append("</ul>")
                out.append("</li>")
            for fn in module["functions"]:
                fid = f'{mid}.{fn["name"]}'
                out.append(f'<li><a href="#{_esc(fid)}">{_esc(fn["name"])}()</a></li>')
            out.append("</ul>")
        out.append("</li>")
    out.append("</ul></section>")

    # Full reference
    out.append("<main>")
    for module in data["modules"]:
        mid = module["name"]
        out.append(f'<section class="module" id="{_esc(mid)}" data-kind="module" data-fqname="{_esc(mid)}">')
        out.append(f"<h2>module {_esc(mid)}</h2>")
        if module.get("error"):
            out.append(f'<pre class="doc">Could not import module: {_esc(module["error"])}</pre>')
        out.append(_llm_doc_block(module["doc"]))

        for cls in module["classes"]:
            cid = f'{mid}.{cls["name"]}'
            out.append(f'<section class="class" id="{_esc(cid)}" data-kind="class" data-fqname="{_esc(cid)}">')
            out.append(f'<h3>class {_esc(cls["name"])}</h3>')
            out.append(_llm_doc_block(cls["doc"]))
            for m in cls["members"]:
                pid = f'{cid}.{m["name"]}'
                out.append(f'<section class="member" id="{_esc(pid)}" data-kind="{_esc(m["kind"])}" '
                           f'data-fqname="{_esc(pid)}">')
                out.append(f'<h4><code class="sig">{_esc(_member_signature(m))}</code></h4>')
                out.append(_llm_doc_block(m["doc"]))
                out.append("</section>")
            out.append("</section>")

        for fn in module["functions"]:
            fid = f'{mid}.{fn["name"]}'
            out.append(f'<section class="function" id="{_esc(fid)}" data-kind="function" '
                       f'data-fqname="{_esc(fid)}">')
            out.append(f'<h3><code class="sig">def {_esc(fn["name"] + fn["signature"])}</code></h3>')
            out.append(_llm_doc_block(fn["doc"]))
            out.append("</section>")

        out.append("</section>")
    out.append("</main></body></html>")
    return "\n".join(out)


# ===========================================================================
# Human-oriented renderer
# ===========================================================================
_HUMAN_STYLE = """
:root{--bg:#fff;--fg:#1a202c;--muted:#5b6675;--line:#e2e8f0;--accent:#2b6cb0;--code:#f6f8fa;--side:#f8fafc}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:var(--fg);background:var(--bg);line-height:1.55}
code,pre,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.layout{display:flex;min-height:100vh}
.sidebar{width:20rem;flex:0 0 20rem;background:var(--side);border-right:1px solid var(--line);
  position:sticky;top:0;height:100vh;overflow:auto;padding:1rem}
.brand{font-weight:700;font-size:1.05rem;margin-bottom:.2rem}
.brand span{font-weight:400;color:var(--muted);font-size:.85rem}
#filter{width:100%;padding:.45rem .6rem;margin:.6rem 0 .4rem;border:1px solid var(--line);border-radius:6px;font-size:.9rem}
#nav details{margin:.15rem 0}
#nav summary{cursor:pointer;font-weight:600;padding:.15rem 0}
#nav ul{list-style:none;margin:.1rem 0 .4rem .2rem;padding-left:.7rem;border-left:1px solid var(--line)}
#nav li{margin:.08rem 0;font-size:.88rem}
#nav .fn{color:var(--muted)}
main{flex:1;min-width:0;padding:1.5rem 2rem;max-width:60rem}
.page-header{border-bottom:1px solid var(--line);padding-bottom:.8rem;margin-bottom:1rem}
.page-header h1{margin:.2rem 0}
.muted{color:var(--muted);font-size:.9rem}
section.module{margin-top:2.4rem}
h2.module-title{border-bottom:2px solid var(--line);padding-bottom:.3rem}
section.class{border:1px solid var(--line);border-radius:8px;padding:.6rem 1rem 1rem;margin:1rem 0;background:#fff}
h3.class-title{margin:.3rem 0}
.member{border-top:1px solid var(--line);padding:.7rem 0}
.member:first-of-type{border-top:0}
.sig{display:block;background:var(--code);border:1px solid var(--line);border-radius:6px;
  padding:.4rem .6rem;font-size:.9rem;overflow-x:auto}
.badge{display:inline-block;font-size:.7rem;text-transform:uppercase;letter-spacing:.04em;
  color:#fff;background:var(--accent);border-radius:4px;padding:.05rem .35rem;margin-right:.4rem;vertical-align:middle}
.badge.classmethod{background:#6b46c1}.badge.staticmethod{background:#2c7a7b}
.badge.property{background:#b7791f}.badge.function{background:#2f855a}.badge.method{background:#2b6cb0}
pre.doc{white-space:pre-wrap;background:var(--code);border-left:3px solid var(--line);
  padding:.5rem .7rem;border-radius:0 6px 6px 0;margin:.5rem 0;overflow-x:auto;font-size:.88rem}
.anchor{color:var(--line);margin-left:.4rem;font-weight:400;text-decoration:none}
.anchor:hover{color:var(--accent)}
.totop{position:fixed;right:1rem;bottom:1rem;background:var(--accent);color:#fff;border-radius:50%;
  width:2.5rem;height:2.5rem;display:flex;align-items:center;justify-content:center;text-decoration:none;box-shadow:0 1px 4px rgba(0,0,0,.3)}
@media(max-width:820px){.layout{flex-direction:column}.sidebar{position:static;width:auto;height:auto;flex:none}main{padding:1rem}}
"""

_HUMAN_SCRIPT = """
(function(){
  var f=document.getElementById('filter');
  if(!f) return;
  f.addEventListener('input',function(){
    var q=f.value.trim().toLowerCase();
    document.querySelectorAll('#nav li').forEach(function(li){
      var a=li.querySelector('a'); if(!a) return;
      li.style.display = a.textContent.toLowerCase().indexOf(q)>=0 ? '' : 'none';
    });
    document.querySelectorAll('#nav details').forEach(function(d){
      var visible=Array.prototype.slice.call(d.querySelectorAll('li')).some(function(li){return li.style.display!=='none';});
      d.style.display=(q===''||visible)?'':'none';
      if(q!=='') d.open=true;
    });
  });
})();
"""


def _human_doc_block(doc: str) -> str:
    return f'<pre class="doc">{_esc(doc)}</pre>' if doc else ""


def _anchor(target_id: str) -> str:
    return f'<a class="anchor" href="#{_esc(target_id)}" title="Link to this item">#</a>'


def render_human_html(data: dict) -> str:
    """Render the API model as a styled, navigable HTML document for people.

    Includes a sticky sidebar with a live filter, badged member kinds, anchored
    headings, a back-to-top control, and a responsive layout — all self-contained
    (no external assets).

    Args:
        data (dict, required): The API model from :func:`collect_api`.

    Returns:
        str: A complete standalone HTML document.
    """
    modules, classes, members, funcs = _counts(data)
    title = data["project_name"]
    version = data.get("version") or ""

    out: List[str] = []
    out.append("<!DOCTYPE html>")
    out.append('<html lang="en"><head><meta charset="utf-8">')
    out.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    out.append(f"<title>{_esc(title)} API reference</title>")
    out.append('<meta name="generator" content="oscal.gendocs">')
    out.append('<meta name="doc-format" content="human">')
    out.append(f"<style>{_HUMAN_STYLE}</style></head><body>")
    out.append('<div class="layout">')

    # Sidebar
    out.append('<aside class="sidebar">')
    brand_version = f'<span>{_esc(version)}</span>' if version else ""
    out.append(f'<div class="brand">{_esc(title)} {brand_version}</div>')
    out.append('<div class="muted">API reference</div>')
    out.append('<input id="filter" type="search" placeholder="Filter symbols…" aria-label="Filter symbols">')
    out.append('<nav id="nav">')
    for module in data["modules"]:
        mid = module["name"]
        out.append(f'<details open><summary><a href="#{_esc(mid)}">{_esc(mid)}</a></summary><ul>')
        for cls in module["classes"]:
            cid = f'{mid}.{cls["name"]}'
            out.append(f'<li><a href="#{_esc(cid)}">class {_esc(cls["name"])}</a></li>')
        for fn in module["functions"]:
            fid = f'{mid}.{fn["name"]}'
            out.append(f'<li class="fn"><a href="#{_esc(fid)}">{_esc(fn["name"])}()</a></li>')
        out.append("</ul></details>")
    out.append("</nav></aside>")

    # Main content
    out.append("<main>")
    out.append('<div class="page-header">')
    out.append(f"<h1>{_esc(title)} — API reference</h1>")
    meta = " · ".join(filter(None, [
        f"Version {_esc(version)}" if version else "",
        f"Generated {_esc(data['generated'])}",
        f"{modules} modules · {classes} classes · {members} methods · {funcs} functions",
    ]))
    out.append(f'<div class="muted">{meta}</div>')
    out.append("</div>")

    for module in data["modules"]:
        mid = module["name"]
        out.append(f'<section class="module" id="{_esc(mid)}">')
        out.append(f'<h2 class="module-title">{_esc(mid)}{_anchor(mid)}</h2>')
        if module.get("error"):
            out.append(f'<pre class="doc">Could not import module: {_esc(module["error"])}</pre>')
        out.append(_human_doc_block(module["doc"]))

        for cls in module["classes"]:
            cid = f'{mid}.{cls["name"]}'
            out.append(f'<section class="class" id="{_esc(cid)}">')
            out.append(f'<h3 class="class-title">class {_esc(cls["name"])}{_anchor(cid)}</h3>')
            out.append(_human_doc_block(cls["doc"]))
            if not cls["members"]:
                out.append('<div class="muted">No public members.</div>')
            for m in cls["members"]:
                pid = f'{cid}.{m["name"]}'
                out.append(f'<div class="member" id="{_esc(pid)}">')
                out.append(f'<span class="badge {_esc(m["kind"])}">{_esc(m["kind"])}</span>'
                           f'<code class="sig">{_esc(_member_signature(m))}</code>{_anchor(pid)}')
                out.append(_human_doc_block(m["doc"]))
                out.append("</div>")
            out.append("</section>")

        for fn in module["functions"]:
            fid = f'{mid}.{fn["name"]}'
            out.append(f'<section class="class" id="{_esc(fid)}">')
            out.append('<div class="member">')
            out.append('<span class="badge function">function</span>'
                       f'<code class="sig">def {_esc(fn["name"] + fn["signature"])}</code>{_anchor(fid)}')
            out.append(_human_doc_block(fn["doc"]))
            out.append("</div></section>")

        out.append("</section>")

    out.append('<a class="totop" href="#" title="Back to top">↑</a>')
    out.append("</main></div>")
    out.append(f"<script>{_HUMAN_SCRIPT}</script>")
    out.append("</body></html>")
    return "\n".join(out)


# ===========================================================================
# Orchestration / CLI
# ===========================================================================
_RENDERERS = {"llm": render_llm_html, "human": render_human_html}


def generate_docs(package_dir: str, output_file: str, mode: str) -> bool:
    """Introspect ``package_dir`` and write an HTML reference in the given mode.

    Args:
        package_dir (str, required): The library package directory to document.
        output_file (str, required): Path of the HTML file to write (parent
            directories are created as needed).
        mode (str, required): ``"llm"`` or ``"human"``.

    Returns:
        bool: True on success, False on failure.
    """
    renderer = _RENDERERS.get(mode)
    if renderer is None:
        print(f"Error: unknown mode '{mode}'. Expected one of: {', '.join(_RENDERERS)}.")
        return False

    try:
        data = collect_api(package_dir)
    except Exception as e:
        print(f"Error collecting API from '{package_dir}': {e}")
        return False

    html_text = renderer(data)
    out_path = Path(output_file)
    if out_path.parent and not out_path.parent.exists():
        out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_text, encoding="utf-8")

    modules, classes, members, funcs = _counts(data)
    print(f"Success! Wrote {mode} HTML ({modules} modules, {classes} classes, "
          f"{members} methods, {funcs} functions) to '{output_file}'.")
    return True


def main(argv: Optional[List[str]] = None) -> int:
    """Command-line entry point.

    Args:
        argv (list, optional): Argument vector (defaults to ``sys.argv``).

    Returns:
        int: Process exit code (0 on success).
    """
    parser = argparse.ArgumentParser(
        prog="oscal.gendocs",
        description="Generate an HTML API reference for a Python package by introspection.",
    )
    parser.add_argument("--mode", required=True, choices=sorted(_RENDERERS),
                        help="Which variant to generate: 'llm' (machine-oriented) or 'human'.")
    parser.add_argument("--output", required=True,
                        help="Target HTML filename (parent directories are created if needed).")
    parser.add_argument("--package", default="./oscal",
                        help="Package directory to document (default: ./oscal).")
    args = parser.parse_args(argv)

    ok = generate_docs(args.package, args.output, args.mode)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
