# GTBI V7 Emergency Preservation Inventory

This directory is the current convenience projection for `PREV7-0001`.
It is not immutable gate evidence until the two-PR genesis protocol and the
authoritative GitHub Actions inventory run have completed.

Current remote scope: `emergency_preservation`.

The remote snapshot is fail-closed. `audit_metadata.json` may set
`complete=false` and list unavailable required surfaces. That state is a
blocker, not permission to infer empty results.

The local worktree projection is separate:

- it uses only read-only Git and filesystem metadata;
- user-home prefixes are redacted;
- it never blocks remote preservation or GitHub-only scientific work;
- it is not included in the authoritative remote snapshot digest.

To make the GitHub inventory complete, configure the narrow
`GTBI_INVENTORY_TOKEN` secret with read access to repository administration
metadata and organization packages. The workflow falls back to the repository
`GITHUB_TOKEN`, but it must remain `complete=false` when that token cannot read
a required surface.
