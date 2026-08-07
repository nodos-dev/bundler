# Nodos Bundler

Nodos Bundler is a tool to bundle a nodos version with modules and release it as a github release and a nodos bundle release.

## Usage

Requirements:

- Python 3.7+
- [`nosman`](https://crates.io/crates/nosman) on PATH: `cargo install nosman`

Environment variables:

- `BUILD_NUMBER`: The build number of the release

## Bundle Versioning

Bundle releases use a bundle-oriented version string:

- `{major}.{minor}` comes from the configured Nodos version for the bundle
- `{short_name}` comes from the bundle `short_name` field, or falls back to the bundle name
- `v{N}` comes from the bundle `version` field in the YAML
- `b{BUILD_NUMBER}` is appended from the build environment

Example:

- `1.3-broadcast-v4-b4711`

GitHub release tags include the platform suffix, for example:

- `v1.3-broadcast-v4-b4711-x86_64-windows`

The nosman package version keeps the bundle identity in the package name and uses the YAML bundle version as the patch component:

- package name: `nodos.bundle.broadcast`
- package version: `1.3.4.b4711`

## Bundle Configuration

Bundles are configured using YAML files. Each Nodos version has its own YAML file:

- `nodos-1.2.yaml` - Bundles for Nodos 1.2
- `nodos-1.3.yaml` - Bundles for Nodos 1.3
- `nodos-1.4.yaml` - Bundles for Nodos 1.4

### Bundle Structure

Bundles are defined as a list with explicit names. Possible fields:

1. `name` - Bundle identifier
2. `short_name` - Short name for release (Optional)
3. `version` - Bundle release version used for GitHub tags and nosman package patch version
4. `nodos` - Nodos version per platform-architecture
5. `bundled_packages` - Map of packages keyed by package name
6. `engine_index_url` - Engine index URL
7. `module_index_urls` - Module index URLs
8. `includes` - List of other bundles to include (Optional). Each item can be a bundle name string or a `{ name, version }` object to pin a specific bundle version. This also works in a inheritance manner for some fields, ie. `nodos` or `engine_index_url` from the included bundle will be used if not defined in the current bundle. `bundled_packages` are merged favoring the current bundle.

The YAML can contain multiple entries with the same `name` as long as their `version` values differ. Use `--bundle-version` to select a specific one. If `--bundle-version` is omitted, the bundler selects the highest available bundle version for that name.

### Platform-Architecture Keys

The bundler uses flat platform-architecture keys:

- `x86_64-windows` - Windows x86_64
- `aarch64-windows` - Windows ARM64
- `x86_64-linux` - Linux x86_64
- `aarch64-linux` - Linux ARM64

#### Example Bundle Configuration

```yaml
bundles:
- name: minimal
  version: 1
  nodos:
    x86_64-windows: 1.3.2
    x86_64-linux: 1.3.0
  bundled_packages:
    nos.reflect:
      x86_64-windows: 1.7.13
      x86_64-linux: 1.6.5
    nos.math:
      x86_64-windows: 1.23.0
      x86_64-linux: 1.23.0
  engine_index_url: https://raw.githubusercontent.com/mediaz/engine-releases/main/index.json
  module_index_urls:
  - url: https://raw.githubusercontent.com/mediaz/nodos-index/main/index
    name: nodos
    is_active: true

- name: standard
  version: 1
  includes:
  - minimal
  bundled_packages:
    nos.filters:
      x86_64-windows: 1.5.5
      x86_64-linux: 1.5.2

- name: standard
  version: 2
  includes:
  - minimal
  bundled_packages:
    nos.filters:
      x86_64-windows: 1.5.6
      x86_64-linux: 1.5.3

- name: broadcast
  version: 4
  includes:
  - name: broadcast
    version: 3
```

## Command Line Usage

Using version and bundle keyword:

```bash
python ./bundler.py --version="1.4" --bundle-key="broadcast" --bundle-version="4" --download-nodos --download-packages --pack --gh-release --gh-release-repo="https://github.com/nodos-dev/bundler" --gh-release-target-branch="dev" --dry-run
```

Using YAML file path:

```bash
python ./bundler.py --bundles-yaml-path="./nodos-1.3.yaml" --bundle-key="broadcast" --bundle-version="4" --download-nodos --download-packages --pack --dry-run
```
