# OSCAL Python Library

This is a collection of python modules for [OSCAL](https://pages.nist.gov/OSCAL) content validation, format conversion, and related capabilities without the need for Internet connectivity. 

It handles all published OSCAL versions, and can "learn" new versions as they are published by NIST.

Please submit feedback,  bug reports and enhancement requests as [GitHub issues](https://github.com/brian-ruf/oscal-class/issues). Bug fixes and backward-compatible code contributions are welcome. Please consider collaborating on any breaking enhancements.

### Designed for Air Gapped Environments

The `OSCAL_support` class includes an _OSCAL Support Module_. A single SQLite3 database file that contains the published support files for all OSCAL formats, versions and models. This enables support functionality in an air gapped environment.

When a new version of OSCAL is published, the support module can be updated on an internet-connected computer and conveyed into an air gapped environment for use.

For more information see the [Support Module](docs/SUPPORT_MODULE.md) documentation.

## Setup

The Python OSCAL Class is intended to be used as a library for your OSCAL python projects. 

Add the following to your `requirements.txt` file or `pyproject.toml` file:

`git+https://github.com/brian-ruf/oscal-class.git@main#egg=oscal-class`

NOTE: [Publication to Python Package Index (Pypi)](https://pypi.org) to occur with formal 1.0.0 release. 

Please see the [Setup documentation](./docs/SETUP.md) for setup instructions and related details.

## Usage: Quick Start

Installation

```bash
pip install oscal-class
```

To use the `OSCAL` class in your code, import the `oscal_content_class` module from the `oscal` library:

```python
from oscal import oscal_content_class

```

### Instantiate the OSCAL class

Open OSCAL content directly from a file:
```python

oscal_file_name = "./catalog.xml"

oscal_catalog_obj = oscal_content_class.OSCAL(filename=oscal_file_name)

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

Create new OSCAL content using the `create_new_oscal_content` function:

```python

oscal_catalog_obj = oscal_content_class.create_new_oscal_content("catalog", "Control Catalog Title")

```
