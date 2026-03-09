# Setting up OSCAL Class

The Python OSCAL Class is intended to be used as a Python library.

## Importing

While future inclusion in Pypi.org is intended, this is currently only available as a GitHub repository.
To import directly from the GitHub repo use the following in your `requirements.txt` or `pyproject.toml`:

```python
oscal @ git+https://github.com/brian-ruf/oscal-class.git@main

```
Replace `main` with `develop` for the latest work.
Once core functions are complete, this will be released under semantic versioning.


## Depdendencies

The OSCAL Class relies on the following libraries. Most are available via Pypi, except [ruf-common](https://github.com/brian-ruf/ruf-common-python), which is code I maintain that is common to several of my Python projects. The dependency is defined in `[repo_root]/pyproject.toml` and code is loded directly from GitHub.

- ruf-common
- loguru
- python-dotenv ()
- saxonche
- jsonschema_rs
- xmlschema

