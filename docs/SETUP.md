# Setting up OSCAL Class

The Python OSCAL Class is intended to be used as a git submodule. It relies on my [Python Common](https://github.com/brian-ruf/common-python) submodule, which must also be present in your project's code repository.


## Project Structure

Relative to the location of your project's main Python module, the Python OSCAL Class expects:
- the Python Common submodule to be located at `./common/`
- this OSCAL Class submodule to be located at `./oscal/`

The resulting project structure should appear as follows:

```
[project-root]
README.md
src/            [Location of your main Python module]
   ├── requirements.txt
   ├── main.py
   ├── oscal/  [this submodule]
   |    ├── oscal*.py
   |    ├── oscal*.py
   |    ├── oscal*.py
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

