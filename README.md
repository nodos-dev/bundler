# Nodos Bundler

Nodos Bundler publishes Nodos bundles to the Nodos Store. A bundle release is a
manifest naming the packages it holds, their exact versions and the folder each
lands in — not an archive. The bundler turns the YAML in this repo into one
manifest per target platform and publishes each one with `nosman`.

## Usage

Requirements:

- Python 3.7+
- [`nosman`](https://crates.io/crates/nosman) 0.24.2 on PATH:
  `cargo install nosman --version 0.24.2 --locked`.
- `NODOS_STORE_ACCESS_TOKEN` for the store account that owns the bundle packages

The release workflow installs nosman with the Rust 1.93.1 toolchain pinned in
`rust-toolchain.toml`. Run the install command from this repository so rustup
selects that compiler instead of the machine's default.

Environment variables:

- `BUILD_NUMBER`: the build number of the release

```bash
python ./bundler.py --version="1.5" --bundle-key="vs" \
  --platforms="x86_64-windows,x86_64-linux,aarch64-macos" --dry-run
```

Publishing a bundle also publishes every bundle it includes, each before the
bundle that includes it, because a nested member has to name a version that is
already on the store.

Publishing goes platform by platform, and within a platform chain by chain,
and stops at the first failure. Nothing published before it is retracted: a
failure on the second platform leaves the first platform fully published, and
a failure part way through a chain leaves the included bundles already
published for that platform without the bundle that includes them. The release
notes for every selected platform are written to `--out-dir` before the first
publish; each manifest is written just before its own publish, so a failed
run leaves the notes for every platform and the manifests up to the failure.
A rerun gets a new build number and publishes new versions; it never
overwrites the versions a failed run left behind.

The release workflow's `dry_run` input defaults to true so a run can be
reviewed before publishing. Set it to false to publish the manifests.

## Command line

- `--version` / `--bundles-yaml-path` — which YAML to read
- `--bundle-key` — the bundle to publish
- `--bundle-version` — which entry to take when several share a name
- `--platforms` — comma separated target platforms; the host platform by default
- `--out-dir` — where the manifests and release notes are written (`./Artifacts`).
  Emptied first if it already exists; refused if it resolves to the current
  directory or one of its parents.
- `--previous-version` — the bundle release the notes compare against. If not
  given, the newest release on the same Nodos line is used, and nosman failing
  to find one is an error. Pass an empty string to say explicitly that this is
  the bundle's first ever publish. In the release workflow, the
  `previous_release_version` input passes a version through and the
  `first_publish` input passes the empty string; a bundle that is not on the
  store yet fails at the lookup unless one of them is set.
- `--dry-run` — ask nosman what it would publish instead of publishing

## Bundle versioning

A bundle publishes as `nodos.bundle.<name>` at
`{nodos major}.{nodos minor}.{bundle version}.b{BUILD_NUMBER}`, so `standard`
built against Nodos 1.5 at bundle version 0 and build 4711 is
`nodos.bundle.standard 1.5.0.b4711`.

## Bundle configuration

Bundles are configured using YAML files, one per Nodos version:
`nodos-1.4.yaml`, `nodos-1.5.yaml`, and so on. Fields:

1. `name` — bundle identifier
2. `short_name` — the name the package takes after `nodos.bundle.` (optional)
3. `version` — the bundle release version, the patch component of the published
   version
4. `nodos` — Nodos version, one value or one per platform
5. `bundled_packages` — map of packages keyed by package name
6. `includes` — other bundles this one includes (optional). An item is a bundle
   name or a `{ name, version }` object pinning a bundle version. `nodos` is
   inherited from an included bundle when this one does not set it.

`engine_index_url` and `plugin_index_urls` in the older YAML files are ignored:
a manifest names packages, and where they come from is the workspace's
business.

The YAML can hold several entries with one `name` as long as their `version`
values differ. `--bundle-version` picks one; without it the highest wins.

`nodos-1.2.yaml` and `nodos-1.3.yaml` predate the rules below, and not every
bundle in them still builds: in `nodos-1.3.yaml`, `rive` pins `nos.rive` at
two versions through its include chain, and `broadcast`, `gsplat` and
`filmmaking` each pin a Nodos version that conflicts with `minimal`'s: all
refused by the checks below. Only `nodos-1.4.yaml` and later were written
with these rules in mind.

### What a bundle becomes

The manifest has `schema_version: 1` and then, each only when it has something
to say, `nodos`, `includes` and `packages`:

- `nodos` is the Nodos release at the bundle root. Only the bundle with no
  `includes` carries it; a bundle that includes another one takes Nodos from
  it, and pinning a different Nodos version in both is refused.
- `includes` maps every included bundle to the version published for it in the
  same run. Each lands at the bundle root.
- `packages` groups packages by the folder pattern they land in, `{name}` and
  `{version}` standing for the package's own. A plugin or subsystem goes under
  `Module/{name}/{version}`; a package marked `type: sample` goes under
  `Samples/{name}`. The groups are written in that order, packages in the order
  the YAML lists them, and a group with no packages is left out.
- A package with no version for a platform is absent from that platform's
  manifest: give it a version only for the platforms it declares. A package that
  does declare a version for a platform but has no matching release there is an
  error, not a silent skip. A bundle with no Nodos version for a platform is not
  published there at all — that is how `vs` stays Windows-only.

### Platform keys

- `x86_64-windows`, `x86_64-linux`, `aarch64-linux`, `aarch64-macos`

#### Example

```yaml
bundles:
- name: minimal
  version: 0
  nodos: 1.5
  bundled_packages:
    nos.reflect: 4.0.0
    nos.math:
      x86_64-windows: 3.0
      x86_64-linux: 3.0

- name: standard
  version: 0
  includes:
  - minimal
  bundled_packages:
    nos.filters: 4.0
    nos.sample.dxapp:
      x86_64-windows: 1.1
      type: sample
```

`standard` then publishes as:

```yaml
schema_version: 1
includes:
  nodos.bundle.minimal: 1.5.0.b4711
packages:
  Module/{name}/{version}:
    nos.filters: 4.0.0.b4711
  Samples/{name}:
    nos.sample.dxapp: 1.1.0.b4711
```

and `minimal` as:

```yaml
schema_version: 1
nodos: 1.5.0.b4711
packages:
  Module/{name}/{version}:
    nos.reflect: 4.0.0.b4711
    nos.math: 3.0.0.b4711
```

## Release notes

Each run writes `release-notes-<platform>.md` for the requested bundle,
comparing it against `--previous-version` (or the newest release on the same
Nodos line). The comparison reads the previous bundle's expansion from the
store with `nosman info`, which always expands for the platform the bundler
runs on, so the lookup happens once for the whole run rather than once per
selected platform. On the platform the bundler runs on, the notes list
packages removed since the previous release; for every other platform, the
previous side of the comparison is still the runner's own expansion, so
removals cannot be told apart from packages that were never there, and the
notes leave the Removed section out rather than guess.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -v
```

The tests fake `nosman` and compare the manifests built from the checked-in YAML
against the golden files under `tests/golden/`.
