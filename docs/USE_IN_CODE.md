# Use in Code

## Important Setup

The Python OSCAL Classes rely on my [Python Common](https://github.com/brian-ruf/common-python) submodule. It must also be present in your project's code repository. 

Relative to the location of your project's main Python module, the Python OSCAL Classes expect:
- the Python Common submodule to be located at `./common/`
- this OSCAL Class submodule to be located at `./oscal/`

Please see the [Setup documentation](./SETUP.md) for setup instructions and related details.


## The OSCAL Classes

There are three OSCAL Classes available. Each class uses and expands on the classes beneath it.:

- **OSCAL Project Class**: Managing a collection of related OSCAL artifacts.
- **OSCAL Content Class**: Managing a single OSCAL artifact.
- **OSCAL Support Class**: Interact directly with the OSCAL Support Module. 

If you are just getting started with this library, consider starting with the OSCAL Content Class.

### The OSCAL Support Class



### The OSCAL Content Class

The OSCAL content class offers a simple solution for ingesting, validating and converting OSCAL content. 


