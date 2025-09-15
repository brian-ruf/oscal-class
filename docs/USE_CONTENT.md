# Use in Code

## Important Setup

The Python OSCAL Class relies on my [Python Common](https://github.com/brian-ruf/common-python) submodule. It must also be present in your project's code repository. 

Relative to the location of your project's main Python module, the Python OSCAL Class expects:
- the Python Common submodule to be located at `./common/`
- this OSCAL Class submodule to be located at `./oscal/`

Please see the [Setup documentation](./SETUP.md) for setup instructions and related details.

## Instantiating the Class

To use the OSCAL Python Class in your Python code

```python

from oscal import oscal_support

support = await oscal_support.OSCAL_support.create(self.config["location"]["supportfile"]["data"])
if self.support is not None:
    print("OSCAL support module initialized.")
else:
    error("Unable to initialize OSCAL support module.")

```

## Validating OSCAL Content

## Converting OSCAl Content

## Managing the OSCAL Support Module


