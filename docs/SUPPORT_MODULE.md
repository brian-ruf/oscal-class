# The OSCAL Support Module

The OSCAL Support Module acquires, stores, and serves local copies of NIST-published OSCAL support files used for validation and format conversion.

The support database distributed with this library is pre-populated with all OSCAL versions available at release time, enabling offline and air-gapped operation.

## Designed For Air-Gapped Environments

The module keeps OSCAL support artifacts in a local database so applications can validate and convert OSCAL content without a live network dependency.

When needed, you can update support content from an internet-connected machine and then move the updated database to offline environments.

## Database Defaults

- Default support DB path: ./support/oscal_support.db (relative to runtime working directory)
- Default DB type: sqlite3
- Support files are cached in the database and may be compressed for size efficiency

## Primary API

The canonical class name is OSCALSupport.

The module also exposes a singleton configuration/access pattern:

```python
from oscal.oscal_support import configure_support, get_support

# Optional explicit configuration before loading any OSCAL content
configure_support(db_path="/path/support.db", init_mode="auto")

# Shared support object used by OSCAL classes
support = get_support()
```

configure_support supports both naming styles for compatibility:

- Pythonic aliases: db_path, init_mode
- Legacy names: support_file, db_init_mode

Supported init_mode values:

- auto: extract packaged DB when missing/empty, otherwise use existing DB
- extract: always try packaged extraction; create empty DB if extraction fails
- create: create an empty DB from scratch

## Updating Support Content

Use update on OSCALSupport to refresh support data:

```python
support = get_support()

# Check for new OSCAL releases (default)
support.update()
support.update(mode="new")

# Re-fetch all supported versions
support.update(mode="all")

# Re-fetch a specific version
support.update(mode="v1.0.0")
```

For compatibility, update(fetch="...") is still accepted.

## Core Methods

Commonly used methods include:

- get_asset(version, model, asset_type)
- list_models(version="all")
- is_valid_model(model, version="all")
- latest_version()
- load_file(name, as_bytes=False)

Compatibility wrappers remain available:

- asset(...)
- enumerate_models(...)
- is_model_valid(...)
- get_latest_version()
- load_file(..., binary=...)

## Compatibility Notes

The previous class name OSCAL_support is retained as an alias to OSCALSupport for backward compatibility.

Likewise, setup_support(...) is retained as a compatibility helper and forwards to configure_support(...).

## Packaging Update Utility

This repository includes an internal utility script that updates support assets and re-zips the distributable support DB payload:

- oscal/update_support.py

That utility is intended for library maintenance workflows, not typical library consumers.

Current usage:

```bash
python oscal/update_support.py --new
python oscal/update_support.py --all
```

It configures support via configure_support(db_path=..., init_mode="auto") and calls support_obj.update(mode=...).

## Future Direction

The support layer currently targets SQLite while using ANSI SQL-oriented patterns intended to ease future support for additional relational backends.
