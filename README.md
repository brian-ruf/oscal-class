![GitHub last commit](https://img.shields.io/github/last-commit/brian-ruf/oscal-class) 
![OSCAL](https://img.shields.io/badge/OSCAL-Enabled-blue?style=flat)
![Python](https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white) 
![Open Source](https://img.shields.io/badge/Open%20Source-Yes-brightgreen?logo=github)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg) 
![PyPI](https://img.shields.io/pypi/v/oscal)

# OSCAL Python Library

A Python library for working with [OSCAL](https://pages.nist.gov/OSCAL) (Open Security
Controls Assessment Language) content. Provides classes to load, validate, convert, and
manipulate OSCAL XML, JSON, and YAML documents for all published OSCAL versions and
models.

---

## Features

- **Profile Processing**: Handles any combination and depth of profiles and catalogs. (See [Profile Processing](./docs/PROFILE_PROCESSING.md) for details.) 
- **All OSCAL models**: Catalog, Profile, Mapping, Component Definition, SSP, Assessment Plan, Assessment Results, POA&M
- **All OSCAL formats**: XML, JSON, and YAML — load any, save to any
- **All published OSCAL versions**: pre-populated support database covers every NIST release; update to learn new versions as they are published
- **Pure-Python format conversion**: no external XSLT processor required
- **Metaschema-based validation**: structure, data-type, allowed-value, and cardinality checks against the NIST metaschema
- **Import resolution**: automatically loads referenced catalogs, profiles, and other documents; surfaces structured failure details when imports cannot be resolved
- **Path-based querying**: XPath-inspired syntax for navigating OSCAL content using either XML element names or JSON key names
- **Air-gapped operation**: the bundled support database enables full offline use; update from an internet-connected machine and transfer the database file


### API Reference

- Human Oriented: [https://brian-ruf.github.io/oscal-class/api.html](https://brian-ruf.github.io/oscal-class/api.html) 
- LLM Oriented: [https://brian-ruf.github.io/oscal-class/api-llm.html](https://brian-ruf.github.io/oscal-class/api-llm.html)

---

## Installation

```bash
pip install oscal
```

Latest pre-released development version:

```bash
pip install git+https://github.com/brian-ruf/oscal-class.git@develop#egg=oscal
```

---

## Quick Start

### Create a new catalog

```python
from oscal import Catalog

catalog = Catalog.new(
    title="My Catalog",
    version="1.0.0",
    published="2026-03-02T00:00:00Z",
)

catalog.create_control_group(
    parent_id="", id="ac", title="Access Control",
    props=[{"name": "label", "value": "AC"},
           {"name": "sort-id", "value": "001"}],
)
catalog.create_control(
    parent_id="ac", id="ac-1",
    title="Access Control Policy and Procedures",
    props=[{"name": "label", "value": "AC-1"},
           {"name": "sort-id", "value": "001-001"}],
    statements=["Develop, document, and disseminate an access control policy."],
)

# Save to XML, JSON, and YAML in one step each
catalog.dump("catalog.json", format="json", pretty_print=True)
catalog.dump("catalog.xml",  format="xml",  pretty_print=True)
catalog.dump("catalog.yaml", format="yaml")
```

### Load and convert existing content

```python
from oscal import Catalog

# Load from any supported format
catalog = Catalog.load("./catalog.xml")

if catalog:
    print(f"{catalog.title} ({catalog.oscal_version})")
    catalog.dump("catalog.json", format="json", pretty_print=True)
else:
    print(f"Load failed: {catalog.content_state.name}")
```

### Load in-memory content

```python
from oscal import OSCAL

xml_str = """<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="http://csrc.nist.gov/ns/oscal/1.0" uuid="8e38fb28-...">
  <metadata>
    <title>My Catalog</title>
    <version>DRAFT</version>
    <oscal-version>1.1.3</oscal-version>
  </metadata>
</catalog>"""

doc = OSCAL.loads(xml_str)
print(doc.model, doc.title)   # catalog   My Catalog
```

### Acquire from a URI

```python
from oscal import OSCAL

doc = OSCAL.acquire("https://raw.githubusercontent.com/.../catalog.json")

# Fallback list — first successful source wins
doc = OSCAL.acquire([
    "https://primary.example.com/catalog.json",
    "./local-fallback/catalog.json",
])
```

### Query content

```python
# XML element name syntax
ctrl  = catalog.query_one('//control[@id="ac-2"]')
title = catalog.query_one('/*/metadata/title')

# JSON key name syntax
ctrl  = catalog.json_query_one('//controls[id="ac-2"]')
stmts = catalog.json_query('//parts[name="statement"]')
```

---

## Model Classes

| Class | OSCAL model |
|---|---|
| `Catalog` | `catalog` |
| `Profile` | `profile` |
| `Mapping` | `mapping-collection` |
| `ComponentDefinition` | `component-definition` |
| `SSP` | `system-security-plan` |
| `AssessmentPlan` | `assessment-plan` |
| `AssessmentResults` | `assessment-results` |
| `POAM` | `plan-of-action-and-milestones` |

Use the base `OSCAL` class when the model is not known in advance.

---

## Documentation

| Document | Contents |
|---|---|
| [Getting Started](docs/GETTING_STARTED.md) | Installation, loading patterns, saving, and a walkthrough example |
| [OSCAL Class API](docs/CONTENT.md) | Complete class reference: factory methods, states, querying, mutation, import handling |
| [Querying Content](docs/QUERY_CONTENT.md) | Full path syntax for `query()` and `json_query()` |
| [Import Resolution](docs/IMPORTS.md) | How imports are resolved, failure codes, and retry API |
| [Format Converters](docs/CONVERTERS.md) | `OSCALConverter` and markup conversion internals |
| [Support Module](docs/SUPPORT_MODULE.md) | Support database configuration, updates, and API |
| [Logging](docs/LOGGING.md) | Enabling Loguru logging |

---

## Designed for Air-Gapped Environments

The `OSCALSupport` class manages a local SQLite database of NIST-published metaschema
and support files for every OSCAL version. The database ships pre-populated, enabling
full offline operation from the moment you install the library.

To learn a newly published OSCAL version:

```python
from oscal.oscal_support import get_support

support = get_support()
support.update()           # fetch any new NIST releases
```

Run `update()` on an internet-connected machine, then copy the updated
`support/oscal_support.db` into the air-gapped environment.

---

## Feedback and Contributions

Please submit bug reports and feature requests as
[GitHub issues](https://github.com/brian-ruf/oscal-class/issues).
Bug fixes and backward-compatible contributions are welcome.
Please open an issue before starting work on any breaking changes.

---

## Use of AI in This Library

**No portion of this library was "vibe coded."**

Early versions were written entirely without AI tools. Claude / Claude Code and GitHub
Copilot have since been used in a manner similar to pair programming:

- Options analysis when planning approaches
- Alignment with Pythonic best practices
- Targeted code reviews and linter resolution
- Debugging and testing support
- Drafting individual functions and methods (reviewed and tested before merge)
- Drafting documentation and unit tests

---

<div align="center">
<img width="10%" align="center" alt="Ruf Risk Logo" src="https://github.com/user-attachments/assets/d4b19372-3a77-40aa-978f-c986b7ded260" /><br />

_Cybersecurity Consulting_<br />
https://RufRisk.com<br />
https://www.linkedin.com/company/rufrisk/<br />

**Brian J. Ruf**, CISSP, CCSP, PMP<br />
OSCAL Co-Creator, Independent Consultant<br />
https://www.linkedin.com/in/brianruf/<br />
</div>
