# Getting Started

The OSCAL class is intended to simplify interaction with OSCAL content, yet offer methods and functions for fine-grained control if desired.

## Getting started:

1. Install the OSCAL library.

The OSCAL library is available via Pypi.org as `oscal`. You can put `oscal` in `requirements.txt`, `pyproject.toml` or simply use `pip` to install:

```bash
pip install oscal

```

2. Import the OSCAL Class into your Python code:

```python
from oscal import Catalog

```

## Common Create/Load Patterns

Use these methods most often when you start working with OSCAL content.

### `loads`

Use `loads` when you already have OSCAL data in memory (string or dictionary).

```python
from oscal import Catalog

catalog_dict = {
	"catalog": {
		"uuid": "11111111-1111-1111-1111-111111111111",
		"metadata": {
			"title": "In-Memory Catalog",
			"version": "0.1.0",
			"oscal-version": "1.1.3",
		},
		"groups": [],
	}
}

catalog = Catalog.loads(catalog_dict, href="memory://catalog")
```

### `load`

Use `load` to read OSCAL content from a local file path or file-like object.

```python
from oscal import Catalog

catalog = Catalog.load("./catalog.xml")
```

### `acquire`

Use `acquire` for non-conventional loading scenarios like URI/reference objects and fallback source lists.

```python
from oscal import OSCAL

catalog = OSCAL.acquire({"href": "https://example.com/catalog.xml"})
```

## Model-Aware Loading with the General `OSCAL` Class

When the model is not known in advance, start with the general `OSCAL` class.
It identifies the OSCAL model from the content (`catalog`, `profile`, `ssp`, etc.).
You can then return a model-specific class instance based on that detected model.

```python
from oscal import (
	OSCAL,
	Catalog,
	Profile,
	Mapping,
	ComponentDefinition,
	SSP,
	AssessmentPlan,
	AssessmentResults,
	POAM,
)

MODEL_CLASS_MAP = {
	"catalog": Catalog,
	"profile": Profile,
	"mapping-collection": Mapping,
	"component-definition": ComponentDefinition,
	"ssp": SSP,
	"assessment-plan": AssessmentPlan,
	"assessment-results": AssessmentResults,
	"poam": POAM,
}


def acquire_typed_oscal(source):
	"""
	Load with OSCAL first, then return the detected model-specific class.
	"""
	generic_obj = OSCAL.acquire(source)
	model_cls = MODEL_CLASS_MAP.get(generic_obj.model)

	if model_cls is None:
		return generic_obj

	return model_cls.acquire(source)


doc = acquire_typed_oscal({"href": "./example/profile.json"})
print(type(doc).__name__)  # Profile
print(doc.model)           # profile
```



### `.new`

Use `.new` to create a fresh OSCAL document from the built-in template for a specific model class.

```python
from oscal import Catalog

catalog = Catalog.new(
	title="My New Catalog",
	version="DRAFT-1.0",
	published="2026-04-26T00:00:00Z",
)
```

### `dump`

Use `dump` to write OSCAL content to disk in XML, JSON, or YAML format.

```python
# Save to JSON, XML, and YAML
catalog.dump("catalog.json", format="json", pretty_print=True)
catalog.dump("catalog.xml", format="xml", pretty_print=True)
catalog.dump("catalog.yaml", format="yaml", pretty_print=True)
```

If `filename` and `format` are omitted, `dump()` will attempt to use the original source location and original format.

## End-to-End Example

```python
from oscal import Catalog

# 1) Create a new catalog
catalog = Catalog.new("Quick Start Catalog", version="1.0.0")

# 2) Dump it
catalog.dump("quick-start-catalog.xml", format="xml", pretty_print=True)

# 3) Load it back from disk
loaded = Catalog.load("quick-start-catalog.xml")

# 4) Save as JSON
loaded.dump("quick-start-catalog.json", format="json", pretty_print=True)
```

