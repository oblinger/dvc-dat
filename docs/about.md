DVC-DAT - A DVC-based Data Management Framework for managing Machine Learning related
data and code.

Developed by Dan Oblinger <dan@sportsvisio.com>
CTO SportsVisio Inc.

## Versioning

Releases follow [semver](https://semver.org). The public contract is
`Dat.create` / `Dat.load` / `do`, the `_spec_.yaml` format, do-system name
resolution and the `dat` CLI: a change to any of those is a **major** version;
a new capability that leaves every existing consumer working is **minor**; a
fix is **patch**. Every release is listed in `CHANGELOG.md` at the repo root.
Consumers pin a tag: `dvc_dat @ git+https://github.com/oblinger/dvc-dat@v2.2.0`.
