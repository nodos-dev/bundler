# Nodos Bundler

Nodos Bundler is a tool to bundle a nodos version with modules and release it as a github release and a nodos bundle release.

## Usage

Requirements:

- Python 3.7+
- [`nodos` CLI tool](https://github.com/nodos-dev/nodos)

Environment variables:

- `BUILD_NUMBER`: The build number of the release
- `PREVIOUS_COMMIT`: The commit hash of the previous release (Optional)

## Bundle Configuration

Bundles are configured using YAML files. Each Nodos version has its own YAML file:
- `nodos-1.2.yaml` - Bundles for Nodos 1.2
- `nodos-1.3.yaml` - Bundles for Nodos 1.3
- `nodos-1.4.yaml` - Bundles for Nodos 1.4

### Bundle Structure

Each bundle is defined without version suffixes. For example, instead of `broadcast_1.4`, use just `broadcast`.

### Platform-Specific Configuration

The bundler supports platform-specific overrides for both packages and nodos versions:

#### Platform-Specific Nodos Version

```yaml
bundles:
  minimal:
    short_name: minimal
    nodos_version: 1.3.2.b4623  # Default version
    platforms:
      linux:
        nodos_version: 1.3.0.b4294  # Linux-specific override
```

#### Platform-Specific Packages

```yaml
bundles:
  minimal:
    bundled_packages:
    - name: nos.reflect
      version: 1.7.13.b1112  # Default version
      platforms:
        linux:
          version: 1.6.5.b980  # Linux-specific version
  
  standard:
    bundled_packages:
    - name: nos.webcam
      version: 2.0.0.b666  # Default version
      platforms:
        linux:
          disabled: true  # Disabled on Linux
```

## Command Line Usage

### Using version and bundle keyword (recommended):
```bash
python ./bundler.py --version="1.4" --bundle-key="broadcast" --target-platform="windows" --download-nodos --download-packages --pack --gh-release --gh-release-repo="https://github.com/nodos-dev/bundler" --gh-release-target-branch="dev"
```

### Using YAML file path:
```bash
python ./bundler.py --bundles-yaml-path="./nodos-1.3.yaml" --bundle-key="broadcast" --target-platform="linux" --download-nodos --download-packages --pack
```

## GitHub Workflow

The GitHub workflow now accepts:
- **version**: Choose from 1.2, 1.3, 1.4
- **bundle_keyword**: Choose from minimal, standard, broadcast, full, ai
- **target_platform**: Windows or Linux
- **previous_tag**: Optional previous release tag or commit