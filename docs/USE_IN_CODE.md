# Use in Code

## Important Setup

The Python OSCAL Classes rely on my [Python Common](https://github.com/brian-ruf/common-python) submodule. It must also be present in your project's code repository. 

Relative to the location of your project's main Python module, the Python OSCAL Classes expect:
- the Python Common submodule to be located at `./common/`
- this OSCAL Class submodule to be located at `./oscal/`

Please see the [Setup documentation](./SETUP.md) for setup instructions and related details.


## The OSCAL Classes

There are three OSCAL Classes available. Each class uses and expands on the classes beneath it.:

- **OSCAL Project Class**: Managing a collection of _related_ OSCAL artifacts.
- **OSCAL Content Class**: Managing a single OSCAL artifact.
- **OSCAL Support Class**: Interact directly with the OSCAL Support Module. 

If you are just getting started with this library, consider starting with the OSCAL Content Class.

### The OSCAL Support Class

You only need one support object for your entire project. The OSCAL Content Class and OSCAL Project Class will create and manage this object as needed. You only need to instantiate the support object if you want to interact with the support module directly.

### The OSCAL Content Class

You need one OSCAL Content object for each OSCAL artifact. The OSCAL Project Class will instantiate OSCAL content objects as neeed. You only need to instantiate the content object if you want to interact with a single OSCAL artifact.

### The OSCAL Project Class

You need one OSCAL Project object for each grouping of related OSCAL artifacts. 

For example, if you have a Catalog, Profile, SSP, AP, AR and POA&M for each of three different systems, you would have three OSCAL Project objects. One for each system.

Each OSCAL project object would have six OSCAL content object. One for each of the OSCAL artifacts.

A single OSCAL support object would be instantiated automatically by the OSCAL content class and used automatically as needed.



