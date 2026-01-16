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
- `nodos-1.2.yaml` - Bundles for Nodos 1.2 (x86_64-windows only)
- `nodos-1.3.yaml` - Bundles for Nodos 1.3 (x86_64-windows, x86_64-linux)
- `nodos-1.4.yaml` - Bundles for Nodos 1.4 (x86_64-windows, x86_64-linux)

### Bundle Structure

Bundles are defined as a list with explicit names. Each bundle has fields in this order:
1. `name` - Bundle identifier
2. `short_name` - Short name for release
3. `nodos` - Nodos version per platform-architecture
4. `bundled_packages` - List of packages
5. `engine_index_url` - Engine index URL
6. `module_index_urls` - Module index URLs

### Platform-Architecture Keys

The bundler uses flat platform-architecture keys:

**Supported combinations:**
- `x86_64-windows` - Windows x86_64
- `x86_64-linux` - Linux x86_64
- `aarch64-linux` - Linux ARM64 (reserved for future use)

**Version-specific platform support:**
- Version 1.2: `x86_64-windows` only
- Version 1.3+: `x86_64-windows` and `x86_64-linux`

#### Example Bundle Configuration

```yaml
bundles:
- name: minimal
  short_name: minimal
  nodos:
    x86_64-windows: 1.3.2
    x86_64-linux: 1.3.0
  bundled_packages:
  - name: nos.reflect
    x86_64-windows: 1.7.13
    x86_64-linux: 1.6.5
  
  - name: nos.math
    x86_64-windows: 1.23.0
    x86_64-linux: 1.23.0
  
  engine_index_url: https://raw.githubusercontent.com/mediaz/engine-releases/main/index.json
  module_index_urls:
  - url: https://raw.githubusercontent.com/mediaz/nodos-index/main/index
    name: nodos
    is_active: true

- name: standard
  short_name: standard
  nodos:
    x86_64-windows: 1.3.2
    x86_64-linux: 1.3.0
  bundled_packages:
  - name: nos.filters
    x86_64-windows: 1.5.5
    x86_64-linux: 1.5.2
  engine_index_url: https://raw.githubusercontent.com/mediaz/engine-releases/main/index.json
  module_index_urls:
  - url: https://raw.githubusercontent.com/mediaz/nodos-index/main/index
    name: nodos
    is_active: true
  includes:
  - minimal
```

**Version Formats:**
- Versions can be less specific (e.g., "1.4.0" or "8.0")
- All package versions are explicitly specified per platform-architecture
- Packages without a version for a platform-arch are skipped for that platform

## Command Line Usage

### Using version and bundle keyword (recommended):
```bash
python ./bundler.py --version="1.4" --bundle-key="broadcast" --download-nodos --download-packages --pack --gh-release --gh-release-repo="https://github.com/nodos-dev/bundler" --gh-release-target-branch="dev"
```

### Using YAML file path:
```bash
python ./bundler.py --bundles-yaml-path="./nodos-1.3.yaml" --bundle-key="broadcast" --download-nodos --download-packages --pack
```

## GitHub Workflow

The GitHub workflow accepts:
- **version**: Choose from 1.2, 1.3, 1.4
- **bundle_keyword**: Any bundle name defined in the YAML file (e.g., minimal, standard, broadcast, full, ai)
- **previous_tag**: Optional previous release tag or commit