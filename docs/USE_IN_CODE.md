# Use in Code

The OSCAL class is intended to take the complexity out of OSCAL content manipulation, while exposing more all methods and functions for fine-grained control if desired.

## Getting started:

1. Install the OSCAL Class library per the [Setup instructions](./SETUP.md)

2. Import the OSCAL Class into your Python code:

```python
from oscal import *

```

# Create New OSCAL Content:

New OSCAL content is created in the latest OSCAL version (currently 1.1.3). The `oscal-version` field is set automatically.


```python

oscal_obj = oscal.create_new_oscal_content("catalog") # Optional `title`, `version` and `published` arguments available.

```

The returned OSCAL object is fully valid with only minimum necessary place-holder data.

The `title`, `version` and `published` arguments are optional. If passed, they will be set immediately upon content creation. Otherwise, placeholder values are used. 


# Loading Existing OSCAL Content:


```python
content = "string" # XML, JSON, or YAML 


try:
    oscal_object = OSCAL(content=content, filename=filename)  
    # If we get here, initialization succeeded
except ValueError as e:
    # Handle the error
    oscal_object = None
```
