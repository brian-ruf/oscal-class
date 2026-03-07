# Publishing to PyPI

Releases are published automatically to [PyPI](https://pypi.org/project/ruf-common/)
by GitHub Actions when a GitHub Release is created. No manual upload steps are required.

## Prerequisites (one-time setup)

- A `pypi` environment configured in the GitHub repository settings
- A Trusted Publisher configured on PyPI linking this repo's `publish.yml` workflow to the `ruf-common` project

## Release steps

### 1. Update the version

In `pyproject.toml`, bump the version number following [Semantic Versioning](https://semver.org/):

```toml
[project]
version = "X.Y.Z"
```

### 2. Commit and push

```bash
git add pyproject.toml
git commit -m "Bump version to vX.Y.Z"
git push
```

### 3. Tag the commit

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

### 4. Create the GitHub Release

1. Go to [Releases → New release](https://github.com/brian-ruf/ruf-common-python/releases/new)
2. Select tag **`vX.Y.Z`**
3. Set the title to **`vX.Y.Z`**
4. Add release notes summarizing the changes
5. Click **"Publish release"**

Publishing the release triggers the `publish.yml` workflow, which builds the
package and uploads it to PyPI automatically.

### 5. Verify

- **Workflow:** https://github.com/brian-ruf/ruf-common-python/actions
- **PyPI listing:** https://pypi.org/project/ruf-common/

## Version numbering guidelines

| Change type | Example | When to use |
|---|---|---|
| Patch `X.Y.Z+1` | `1.0.1` → `1.0.2` | Bug fixes, no API changes |
| Minor `X.Y+1.0` | `1.0.2` → `1.1.0` | New features, backward-compatible |
| Major `X+1.0.0` | `1.1.0` → `2.0.0` | Breaking changes |
