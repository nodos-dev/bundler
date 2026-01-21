# Nodos Bundler

Nodos Bundler is a tool to bundle a nodos version with modules and release it as a github release and a nodos bundle release.

## Usage

Requirements:

- Python 3.7+
- [`nodos` CLI tool](https://github.com/nodos-dev/nodos)

Environment variables:

- `BUILD_NUMBER`: The build number of the release

## Bundle Configuration

Bundles are configured using YAML files. Each Nodos version has its own YAML file:

- `nodos-1.2.yaml` - Bundles for Nodos 1.2
- `nodos-1.3.yaml` - Bundles for Nodos 1.3
- `nodos-1.4.yaml` - Bundles for Nodos 1.4

### Bundle Structure

Bundles are defined as a list with explicit names. Possible fields:

1. `name` - Bundle identifier
2. `short_name` - Short name for release (Optional)
3. `nodos` - Nodos version per platform-architecture
4. `bundled_packages` - Map of packages keyed by package name
5. `engine_index_url` - Engine index URL
6. `module_index_urls` - Module index URLs
7. `includes` - List of other bundle names to include (Optional). This also works in a inheritance manner for some fields, ie. `nodos` or `engine_index_url` from the included bundle will be used if not defined in the current bundle. `bundled_packages` are merged favoring the current bundle.

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
  includes:
  - minimal
  bundled_packages:
    nos.filters:
      x86_64-windows: 1.5.5
      x86_64-linux: 1.5.2
```

## Command Line Usage

Using version and bundle keyword:

```bash
python ./bundler.py --version="1.4" --bundle-key="broadcast" --download-nodos --download-packages --pack --gh-release --gh-release-repo="https://github.com/nodos-dev/bundler" --gh-release-target-branch="dev" --dry-run
```

Using YAML file path:

```bash
python ./bundler.py --bundles-yaml-path="./nodos-1.3.yaml" --bundle-key="broadcast" --download-nodos --download-packages --pack --dry-run
```
