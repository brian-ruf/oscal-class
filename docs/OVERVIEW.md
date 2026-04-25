# OSCAL Library Overview

The OSCAL Library consists of:
- Support Modules
- Content Management Modules
- Format Conversion Modules

## Support Modules

The core modules are:
- `oscal_support.py`: Includes the `OSCAL_support` class, used to manage the NIST-published OSCAL metaschema and support files for all OSCAL versions. 
- `update_support.py`: Interacts with the NIST OSCAL repository to acquire official OSCAL support files for published OSCAL versions.

See [Support Module](./SUPPORT_MODULE.md) for more informaiton. 

## Content Management Modules

There is a core `OSCAL` class, as well as classes for each OSCAL model (`Catalog`, `Profile`, `Mapping`, `ComponentDefinition`, `SSP`, `AssessmentPlan`, `AssessmentResults` and `POAM`). 

Each of the model-specific classes inherit the `OSCAL` class for common methods and attributes. 

The modules are organized as follows:
- `oscal_content.py`: Includes the `OSCAL` class and and related functions common to all OSCAL models. 
- `oscal_controls.py`: Includes `Catalog`, `Profile` and `Mapping` classes and control layer functions.
- `oscal_implementation.py`: Includes `ComponentDefinition` and `SSP` classes and implementation layer functions.
- `oscal_assessment.py`: Includes `AssessmentPlan`, `AssessmentResults` and `POAM` classes and assessment layer functions.
- `oscal_datatypes.py`: OSCAL (Metaschema) data types and their regex patterns.

See [Content Management](./CONTENT.md) for more information.


### Format Conversion Modules

- `oscal_converters.py`: Primary functions to convert in either direction between XML and  JSON, and between OSCAL HTML and OSCAL markdown (markup-line/markup-multiline). 
- `fix_references.py`: Used after converting formats. Adjusts import statements to use an artifact of the same format.
- `oscal_resequence.py`: Resequences keys in OSCAL JSON and YAML files to match the canonical order defined in NIST OSCAL syntax documentation.
- `xml_formatter.py`: Restructures OSCAL XML for readability

See [Converters](./CONVERTERS.md) for more information.
