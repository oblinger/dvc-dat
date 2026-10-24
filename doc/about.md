:>> [DAT](DAT%20Track/DAT.md) → [DAT about](ha://p/DAT%20about) 
# About
Who built dvc_dat, and the versioning rule for its public contract.

DVC-DAT - A Data Management Framework for managing Machine Learning related
data and code.

Developed by Dan Oblinger <dan@sportsvisio.com>
CTO SportsVisio Inc.

## Versioning

Releases follow [semver](https://semver.org), as `CHANGELOG.md` states it:
a major marks a different DAT and is cut only by the owner (1.x the
original DAT, 2.x DAT with the ledger); a minor is a notable capability,
one per run of related changes; everything else is a patch. Every release is listed in `CHANGELOG.md` at the repo root.
Consumers pin a tag: `dvc_dat @ git+https://github.com/oblinger/dvc-dat@v2.3.0`.
