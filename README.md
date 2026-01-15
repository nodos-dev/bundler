# Nodos Bundler
Nodos Bundler is a tool to bundle a nodos version with modules and release it as a github release and a nodos bundle release.

# Usage

Requirements:
- Python 3.11+
- [`nodos` CLI tool](https://github.com/nodos-dev/nodos)

Environment variables:
- `BUILD_NUMBER`: The build number of the release
- `PREVIOUS_COMMIT`: The commit hash of the previous release (Optional)

## Bundle Configuration

Bundles are now configured using TOML files instead of JSON. Each Nodos version has its own TOML file:
- `nodos-1.2.toml` - Bundles for Nodos 1.2
- `nodos-1.3.toml` - Bundles for Nodos 1.3
- `nodos-1.4.toml` - Bundles for Nodos 1.4

### Bundle Structure

Each bundle is defined without version suffixes. For example, instead of `broadcast_1.4`, use just `broadcast`.

### Platform-Specific Packages

Packages can now specify platform-specific options:

```toml
# Default package configuration
[[bundles.standard.bundled_packages]]
name = "nos.webcam"
version = "2.0.0.b666"

# Linux-specific override
[[bundles.standard.bundled_packages]]
name = "nos.webcam"
disabled = true
platform = "linux"

# Platform-specific version
[[bundles.minimal.bundled_packages]]
name = "nos.reflect"
version = "1.6.5.b980"
platform = "linux"
```

## Command Line Usage

### Using version and bundle keyword (recommended):
```bash
python ./bundler.py --version="1.4" --bundle-key="broadcast" --target-platform="windows" --download-nodos --download-packages --pack --gh-release --gh-release-repo="https://github.com/nodos-dev/bundler" --gh-release-target-branch="dev"
```

### Using TOML file path:
```bash
python ./bundler.py --bundles-toml-path="./nodos-1.3.toml" --bundle-key="broadcast" --target-platform="linux" --download-nodos --download-packages --pack
```

### Legacy JSON support:
```bash
python ./bundler.py --bundles-json-path="./bundles.json" --bundle-key="broadcast_1.3" --download-nodos --download-packages --pack
```

## GitHub Workflow

The GitHub workflow now accepts:
- **version**: Choose from 1.2, 1.3, 1.4
- **bundle_keyword**: Choose from minimal, standard, broadcast, full, ai
- **target_platform**: Windows or Linux
- **previous_tag**: Optional previous release tag or commit