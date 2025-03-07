# Nodos Bundler
Nodos Bundler is a tool to bundle a nodos version with modules and release it as a github release and a nodos bundle release.

# Usage

Requirements:
- Python 3
- [`nodos` CLI tool](https://github.com/nodos-dev/nodos)

Environment variables:
- `BUILD_NUMBER`: The build number of the release
- `PREVIOUS_COMMIT`: The commit hash of the previous release(Optional)

```bash
python .\bundler.py --bundle-key="broadcast_1.3" --bundles-json="./bundles.json" --gh-release --gh-release-repo="https://github.com/nodos-dev/bundler" --gh-release-target-branch="dev" --download-nodos --download-modules --pack
```