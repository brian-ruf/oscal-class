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

To use the `OSCAL` class in your code, import the `oscal_content_class` module from the `oscal` library:

```python
from oscal import OSCAL

# Create a new OCAL catalog object
oscal_catalog_obj = OSCAL.new(
                     model_name="catalog", 
                     title="My Catalog", 
                     version="DRAFT-1.0", 
                     published="2026-03-02T00:00:00Z")

oscal_catalog_obj.create_control_group("", "ac", "Access Control", 
                                       props=[{"name":"label", "value": "AC"}, 
                                              {"name":"sort-id", "value": "001"}])

oscal_catalog_obj.create_control("ac", "ac-1", "Access Control Policy and Procedures",
                                       props=[{"name":"label", "value": "AC-1"}, 
                                              {"name":"sort-id", "value": "001-001"}],
                                              statements=["The organization develops, documents, and disseminates an access control policy that addresses purpose, scope, roles, responsibilities, management commitment, coordination among organizational entities, and compliance."],
                                              )

oscal_catalog_obj.create_control("ac", "ac-2", "Access Control Enforcement",
                                       props=[{"name":"label", "value": "AC-2"}, 
                                              {"name":"sort-id", "value": "001-002"}],
                                              statements=["The organization enforces access control policies through technical and administrative mechanisms."],
                                              )

if oscal_catalog_obj:
    oscal_catalog_obj.save("test_catalog.json", format="json", pretty_print=True)
    oscal_catalog_obj.save("test_catalog.xml",  format="xml",  pretty_print=True)
    oscal_catalog_obj.save("test_catalog.yaml", format="yaml", pretty_print=True)

```

### Instantiate the OSCAL class

Open OSCAL content directly from a file:
```python
from oscal import oscal_content_class as oscal_content

oscal_catalog_obj = oscal_content_class.OSCAL(filename="./catalog.xml")

if oscal_catalog_obj:
    oscal_catalog_obj.save("test_catalog.json", format="json", pretty_print=True)
    oscal_catalog_obj.save("test_catalog.xml", format="xml", pretty_print=True)
    oscal_catalog_obj.save("test_catalog.yaml", format="yaml", pretty_print=True)

```

Use an existing OSCAL string:

```python

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

oscal_catalog_obj = oscal_content_class.OSCAL(content=oscal_content)

```

