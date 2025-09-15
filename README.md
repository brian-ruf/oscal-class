# Python OSCAL Class

This is a collection of python modules for [OSCAL](https://pages.nist.gov/OSCAL) content validation, format conversion, and related capabilities without the need for Internet connectivity. 

It handles all published OSCAL versions, and can be updated with additional versions as they are published by NIST.

Please submit feedback,  bug reports and enhancement requests as [GitHub issues](https://github.com/brian-ruf/oscal-class/issues). I welcome code contributions for enhancements and bug fixes, and would enjoy collaborating with you on any enhancements that may impact existing code.


## The OSCAL Support Module

The Python OSCAL Class creates and maintains a single external file that contains all of the NIST-published support files for all OSCAL versions and models. This is referred to in documentation as the _OSCAL Support Module_.

The Python OSCAL Class is able to validate and convert any OSCAL version and module where the NIST-published support files are present in the OSCAL Support Model. No Internet connection required.

As NIST publishes additional modules, they can be added to the OSCAL Support Module. An Internet connect is rquired to update the OSCAL Support Module; however, once updated, it can be copied to any computer for use.

### Designed for Air Gapped Environments

The concept behind the OSCAL Support Module is that it can be generated or updated on an Internet-connected computer and then conveyed into an air gapped environment for use.  

### Open Standard

The OSCAL Support Module is a SQLite 3 database, implemented without encryption so that tables can be inspected. Each cached file is stored as a blob. 

The default configuration is to compress each cached file before storing; however, the compression can be turned off for even greater transparency with the trade-off of increased file size. 

This default name and location for the OSCAl Support Module is `./support/support.oscal`; however, your project code can override the location and/or the file name. 

## Setup

The Python OSCAL Class is intended to be used as a submodule to your project repository. It currently expects your project repository to have a my [Python Common](https://github.com/brian-ruf/common-python) submodule.

Please see the [Setup documentation](./docs/SETUP.md) for setup instructions and related details.

## Usage in Code Quick Start

The Python OSCAL Class is designed to use the 
