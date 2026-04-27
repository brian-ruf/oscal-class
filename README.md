# OSCAL Python Library

This is a collection of python modules for [OSCAL](https://pages.nist.gov/OSCAL) XML, JSON and YAML content. It provides classes for OSCAL content. The classes are able to perform validation, format conversion and some content manipulation. 

It handles all published OSCAL versions, and can "learn" new versions as they are published by NIST.

Please submit feedback, bug reports and enhancement requests as [GitHub issues](https://github.com/brian-ruf/oscal-class/issues). Bug fixes and backward-compatible code contributions are welcome. Please consider collaborating on any breaking enhancements.

### Designed for Air Gapped Environments

The `OSCAL_support` class includes an _OSCAL Support Module_. This is a single SQLite3 database file that contains the NIST-published support files for all OSCAL formats, versions and models. The module enables support functionality in an air gapped environment.

When a new version of OSCAL is published, the support module can be updated on an Internet-connected computer and conveyed into an air gapped environment for use.

#### Inspection

Inspection of the OSCAL Support Module is possible using any SQLite database viewer. Note that the suport files are ZIP compressed within the database; however, no encryption is used in order to facilitate inspection. 

For more information see the [Support Module](docs/SUPPORT_MODULE.md) documentation.

## Setup

The Python OSCAL Class is intended to be used as a library for your OSCAL python projects. 

Add the following to your `requirements.txt` file or `pyproject.toml` file:

- Latest published verson use: `oscal`

- Most up-to-date, unpublished version use: `git+https://github.com/brian-ruf/oscal-class.git@develop#egg=oscal`

Please see the [Setup documentation](./docs/SETUP.md) for setup instructions and related details.

## Usage: Quick Start

Installation

```bash
pip install oscal
```

To use the OSCAL classes in your code, import from the `oscal` library:

```python
from oscal import Catalog

# Create a new catalog object
catalog = Catalog.new(
    title="My Catalog", 
    version="DRAFT-1.0", 
    published="2026-03-02T00:00:00Z"
)

# Create a control group and controls
catalog.create_control_group("", "ac", "Access Control", 
                             props=[{"name":"label", "value": "AC"}, 
                                    {"name":"sort-id", "value": "001"}])

catalog.create_control("ac", "ac-1", "Access Control Policy and Procedures",
                       props=[{"name":"label", "value": "AC-1"}, 
                              {"name":"sort-id", "value": "001-001"}],
                       statements=["The organization develops, documents, and disseminates an access control policy that addresses purpose, scope, roles, responsibilities, management commitment, coordination among organizational entities, and compliance."])

catalog.create_control("ac", "ac-2", "Access Control Enforcement",
                       props=[{"name":"label", "value": "AC-2"}, 
                              {"name":"sort-id", "value": "001-002"}],
                       statements=["The organization enforces access control policies through technical and administrative mechanisms."])

# Save to multiple formats
catalog.dump("test_catalog.json", format="json", pretty_print=True)
catalog.dump("test_catalog.xml",  format="xml",  pretty_print=True)
catalog.dump("test_catalog.yaml", format="yaml", pretty_print=True)

```

### Load OSCAL content from a file

Open OSCAL content directly from a local file:

```python
from oscal import Catalog

# Load from file
catalog = Catalog.load("./catalog.xml")

# Save to other formats
catalog.dump("test_catalog.json", format="json", pretty_print=True)
catalog.dump("test_catalog.xml", format="xml", pretty_print=True)
catalog.dump("test_catalog.yaml", format="yaml", pretty_print=True)

```

### Parse OSCAL content from a string

Use `loads()` with OSCAL content already in memory:

```python
from oscal import OSCAL

oscal_content = """
<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="http://csrc.nist.gov/ns/oscal/1.0" uuid="8e38fb28-f88e-4c3b-ac72-c39511a51f65">
   <metadata>
      <title>Control Catalog Template</title>
      <published>2025-09-10T12:00:00-04:00</published>
      <last-modified>2025-09-10T12:00:00-04:00</last-modified>
      <version>DRAFT</version>
      <oscal-version>1.1.3</oscal-version>
   </metadata>
</catalog>
"""

catalog = OSCAL.loads(oscal_content)

```

## Use of AI for Creating/Maintaining This Library

**No portion of this library was "vibe coded".**

Early versions of this library were written entirely without the use of AI tools.

Claude/Claude Code and GitHub Co-pilot have been used in a manner similar to pair-programming. This includes:
- options analysis when planning approaches
- improving alignment with "pythonic" best practices
- targeted code reviews
- resolving linter issues
- aid in debugging and testing
- drafting individual functions/methods that I refine and test 
- drafting portions of documentation
- drafting/creating unit tests
