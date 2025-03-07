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

## Nodos 1.3.0.b4144

### Engine
* Engine version: 1.3.0.b4144 (prev: 1.3.0.b4084, [Compare](https://github.com/mediaz/nodos/compare/v1.3.0.b4084-x86_64-windows...v1.3.0.b4144-x86_64-windows))
### Modules
* nos.sys.variables - 1.0.1.b897 (prev: 1.0.0.b885) [Compare](https://github.com/nodos-dev/modules/compare/build.dev-windows-885...build.dev-windows-897))
* nos.reflect - 1.6.3.b897 (prev: 1.6.2.b885) [Compare](https://github.com/nodos-dev/modules/compare/build.dev-windows-885...build.dev-windows-897))    
* nos.sys.shaderc - 1.1.0.b878 (no change)
* nos.sys.vulkan - 6.1.1.b605 (prev: 6.1.0.b595) [Compare](https://github.com/mediaz/nos-sys-vulkan/compare/build.dev-windows-595...build.dev-windows-605))
* nos.sys.settings - 0.3.0.b804 (no change)
* nos.filters - 1.5.2.b880 (no change)
* nos.math - 1.9.1.b878 (no change)
* nos.utilities - 3.9.0.b897 (prev: 3.8.2.b887) [Compare](https://github.com/nodos-dev/modules/compare/build.dev-windows-887...build.dev-windows-897))  
* nos.mediaio - 2.5.0.b641 (no change)
* nos.sys.mediaio - 0.4.0.b641 (no change)
* nos.webcam - 1.3.1.b641 (prev: 1.3.0.b637) [Compare](https://github.com/nodos-dev/webcam/compare/build.dev-windows-637...build.dev-windows-641))      
* nos.sys.animation - 1.5.0.b878 (no change)
* nos.animation - 0.3.1.b897 (prev: 0.3.0.b878) [Compare](https://github.com/nodos-dev/modules/compare/build.dev-windows-878...build.dev-windows-897))  
* nos.webrtc - 1.2.0.b878 (no change)
* nos.str - 0.3.0.b878 (no change)
* nos.sys.device - 0.3.3.b15 (prev: 0.3.0.b9) [Compare](https://github.com/nodos-dev/sys-device/compare/build.dev-windows-9...build.dev-windows-15))    
* nos.aja - 2.5.0.b694 (prev: 2.4.1.b686) [Compare](https://github.com/nodos-dev/aja/compare/build.dev-windows-686...build.dev-windows-694))
* nos.sys.decklink - 2.1.0.b70 (no change)
* nos.decklink - 1.1.1.b70 (no change)
* nos.track - 1.9.0.b878 (no change)
* nos.display - 0.3.0.b26 (no change)


 Previous release: https://github.com/nodos-dev/bundler/releases/tag/v1.3.0.b3708-broadcast-x86_64-windows