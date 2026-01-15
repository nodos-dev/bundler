# Bundler Refactoring Migration Guide

This guide explains the changes made to the bundler and how to migrate from the old JSON-based system to the new YAML-based system.

## What Changed

### 1. YAML Instead of JSON

**Before (bundles.json):**
```json
{
  "bundles": {
    "minimal_1.4": {
      "short_name": "minimal",
      "bundled_packages": [...]
    },
    "broadcast_1.4": {
      "short_name": "broadcast",
      "includes": ["standard_1.4"]
    }
  }
}
```

**After (nodos-1.4.yaml):**
```yaml
bundles:
  minimal:
    short_name: minimal
    bundled_packages:
    - name: nos.reflect
      version: 2.0.0.b1104

  broadcast:
    short_name: broadcast
    includes:
    - standard
```

### 2. Version-Specific Files

Instead of one large `bundles.json` file, bundles are now organized by Nodos version:
- `nodos-1.2.yaml` - All bundles for Nodos 1.2
- `nodos-1.3.yaml` - All bundles for Nodos 1.3
- `nodos-1.4.yaml` - All bundles for Nodos 1.4

### 3. Simplified Bundle Keys

Bundle keys no longer include version suffixes:
- ❌ Old: `minimal_1.4`, `broadcast_1.3`
- ✅ New: `minimal`, `broadcast`

Dependencies only reference bundles in the same file:
- ❌ Old: `"includes": ["standard_1.4"]`
- ✅ New: `includes: [standard]`

### 4. Platform-Specific Support

Platform-specific configurations are now nested under a `platforms` sub-element, making them easier to find and maintain.

#### Platform-Specific Nodos Version

```yaml
bundles:
  minimal:
    nodos_version: 1.3.2.b4623  # Default
    platforms:
      linux:
        nodos_version: 1.3.0.b4294  # Linux override
```

#### Platform-Specific Package Versions

```yaml
bundles:
  minimal:
    bundled_packages:
    - name: nos.reflect
      version: 1.7.13.b1112  # Default version
      platforms:
        linux:
          version: 1.6.5.b980  # Linux-specific override
```

#### Disabling Packages Per Platform

```yaml
bundles:
  standard:
    bundled_packages:
    - name: nos.webcam
      version: 2.0.0.b666  # Default - enabled
      platforms:
        linux:
          disabled: true  # Disabled on Linux
```

### 5. Updated Command Line Interface

**Old way:**
```bash
python bundler.py \
  --bundle-key="broadcast_1.4" \
  --bundles-json="./bundles.json" \
  --download-nodos --download-packages --pack
```

**New way:**
```bash
python bundler.py \
  --version="1.4" \
  --bundle-key="broadcast" \
  --target-platform="windows" \
  --download-nodos --download-packages --pack
```

**Alternative (using YAML path):**
```bash
python bundler.py \
  --bundles-yaml-path="./nodos-1.4.yaml" \
  --bundle-key="broadcast" \
  --target-platform="linux" \
  --download-nodos --download-packages --pack
```

**Legacy support (still works):**
```bash
python bundler.py \
  --bundles-json-path="./bundles.json" \
  --bundle-key="broadcast_1.4" \
  --download-nodos --download-packages --pack
```

### 6. GitHub Workflow Changes

**Old workflow inputs:**
- `bundle_key`: Full bundle name with version (e.g., "broadcast_1.4")
- `target_platform`: Windows or Linux

**New workflow inputs:**
- `version`: Choice of "1.2", "1.3", "1.4"
- `bundle_keyword`: Choice of "minimal", "standard", "broadcast", "full", "ai"
- `target_platform`: Windows or Linux

## Migration Steps

1. **Update workflow calls:**
   - Replace `bundle_key: "broadcast_1.4"` with separate `version: "1.4"` and `bundle_keyword: "broadcast"`

2. **For custom scripts:**
   - Update command line to use `--version` and `--bundle-key` instead of combined bundle key
   - Add `--target-platform` parameter (optional, auto-detected if not specified)

3. **Platform-specific bundles:**
   - Remove separate `linux_*` bundles
   - Use platform-specific package entries in the main bundle instead

## Examples

### Example 1: Creating a Linux broadcast bundle for Nodos 1.3

```bash
python bundler.py \
  --version="1.3" \
  --bundle-key="broadcast" \
  --target-platform="linux" \
  --download-nodos \
  --download-packages \
  --pack
```

### Example 2: GitHub Workflow

```yaml
- name: Bundle Nodos
  uses: ./.github/workflows/release.yml
  with:
    version: "1.4"
    bundle_keyword: "broadcast"
    target_platform: "Windows"
```

### Example 3: Checking which packages are included

```python
import yaml

# Load bundle configuration
with open('nodos-1.4.yaml', 'r') as f:
    data = yaml.safe_load(f)
    bundles = data['bundles']

# Get broadcast bundle for Linux
broadcast = bundles['broadcast']
```

## Benefits

1. **Better Organization**: Each Nodos version in its own file
2. **Cleaner Keys**: No version suffixes to maintain
3. **Platform Flexibility**: Easy to specify platform-specific options
4. **Widely Supported**: YAML is a widely-used standard format
5. **Easier to Read**: YAML syntax is clean and human-friendly
6. **Maintainability**: Changes to one version don't affect others

## Backward Compatibility

The `--bundles-json-path` option maintains full backward compatibility with the old JSON format. This allows for gradual migration.
