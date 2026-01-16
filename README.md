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

Each bundle is defined without version suffixes. For example, instead of `broadcast_1.4`, use just `broadcast`.

### Flat Platform-Architecture Configuration

The bundler uses a flat structure with platform-architecture keys:

**Supported platform-architecture combinations:**
- `x64-windows` - Windows 64-bit
- `x64-linux` - Linux 64-bit
- `aarch64-linux` - Linux ARM64

#### For Versions 1.2-1.3 (Explicit Versions)

```yaml
bundles:
  minimal:
    short_name: minimal
    nodos:
      x64-windows: 1.3.2.b4623
      x64-linux: 1.3.0.b4294
      aarch64-linux: 1.3.0.b4294
    bundled_packages:
    - name: nos.reflect
      x64-windows: 1.7.13.b1112
      x64-linux: 1.6.5.b980
      aarch64-linux: 1.6.5.b980
    
    - name: nos.math
      x64-windows: 1.23.0.b1104
      x64-linux: 1.23.0.b1104
      aarch64-linux: 1.23.0.b1104
```

#### For Version 1.4+ (Auto-Query via nosman)

For version 1.4 and above, you can omit versions and the bundler will query them automatically using `nosman info`:

```yaml
bundles:
  minimal:
    short_name: minimal
    nodos: {}  # Empty dict - will query latest via nosman
    bundled_packages:
    - name: nos.reflect   # Will query latest via nosman info
    - name: nos.math      # Will query latest via nosman info
```

**Note:** If a version is not specified for a platform-arch combination, it will be queried automatically via `nosman info <package>`.

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
- **bundle_keyword**: Choose from minimal, standard, broadcast, full, ai
- **previous_tag**: Optional previous release tag or commit