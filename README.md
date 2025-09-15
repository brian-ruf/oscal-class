# OSCAL PYTHON MODULES

## Overview
This is a collection of python modules for [OSCAL](https://pages.nist.gov/OSCAL) manipulation. 

Feedback is welcome in the form of a [GitHub issue](https://github.com/brian-ruf/oscal-class/issues). While I will try to address bugs in a timely matter, I only intend to invest in feature requests that align with my project work. Feel free to contribute backward compatible enhancements.

## Dependencies

Collectively, these modules rely on the following external libraries:

- loguru (all)
- python-dotenv ()
- saxonche
- jsonschema_rs
- xmlschema

**This is an incomplete list**, and is being refined as the library is being prepared for independent use. This comment will be removed when the list is complete.


## Setup

These instructions assume the following project structure:

```
[project-root]
README.md
src/            [Your Python project]
   ├── requirements.txt
   ├── your-module1.py
   ├── your-module2.py
   ├── oscal/  [this submodule]
   |    ├── oscal.py
   |    ├── oscal_class.py
   |    ├── misc.py
   |    └── __init__.py
   ├── common/  [required submodule]
        ├── data.py
        ├── database_sqlite3.py
        ├── database.py
        ├── lfs.py
        ├── helper.py
        ├── network.py
        └── __init__.py
```

To use this submodule, your GitHub repository must also have [common-python](https://github.com/brian-ruf/common-python) as a submodule.

1. Ensure the common-python submodule is present


1. With your repository's `./src` folder as the default location, issue the following command:
```
git submodule add https://github.com/brian-ruf/oscal-class.git oscal_class
```

2. Import the library into your python modules:

```python
from oscal_class import * # to import all

# OR

from oscal_class import metaschema_parser # import only one of the modules
```

## Modules

The following modules are exposed to your application via the above instructions:

- `.py`: .

The following additional modules are present and support the above, but are not directly exposed:

- `.py`: .
