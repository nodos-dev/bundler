import argparse
from subprocess import CompletedProcess, call, run, CalledProcessError
from sys import stderr, stdout
from loguru import logger
import os
import shutil
import yaml
import glob
import platform
import json
import re
from collections import OrderedDict


WORKSPACE_FOLDER = "./workspace"
ARTIFACTS_FOLDER = "./Artifacts/"

class PlatformArch:
    def __init__(self, arch_os_key: str):
        parts = arch_os_key.split("-")
        self.arch = parts[0]
        self.os_name = parts[1]

    def key(self) -> str:
        return f"{self.arch}-{self.os_name}"
    
    def compressed_file_extension(self) -> str:
        if self.os_name == "linux":
            return ".tar.gz"
        return ".zip"
    
    def compression_type(self) -> str:
        if self.os_name == "linux":
            return "gztar"
        return "zip"

class BundlesYamlLoader(yaml.SafeLoader):
    pass

def _remove_implicit_resolver(loader_cls, tag_to_remove):
    for ch, resolvers in list(loader_cls.yaml_implicit_resolvers.items()):
        loader_cls.yaml_implicit_resolvers[ch] = [
            resolver for resolver in resolvers if resolver[0] != tag_to_remove
        ]

_remove_implicit_resolver(BundlesYamlLoader, "tag:yaml.org,2002:int")
_remove_implicit_resolver(BundlesYamlLoader, "tag:yaml.org,2002:float")

def load_bundles_data(path):
    with open(path, 'r') as f:
        bundles_data = yaml.load(f, Loader=BundlesYamlLoader)
    if bundles_data is None:
        logger.error(f"Failed to read {path}")
        exit(1)
    if bundles_data.get("bundles") is None:
        logger.error(f"Failed to read {path}. Missing 'bundles' key")
        exit(1)
    return bundles_data

def force_delete_folder(folder_path):
    """Forcefully deletes a folder, handling permission issues."""
    if not os.path.exists(folder_path):
        return

    try:
        if os.name == "nt":  # Windows
            run(["powershell", "-Command", "Remove-Item", "-Path", folder_path, "-Recurse", "-Force"], shell=True, check=True)
        else:  # Linux/macOS
            run(["rm", "-rf", folder_path], check=True)
    except CalledProcessError as e:
        print(f"Error deleting {folder_path}: {e}", file=stderr)

def get_cur_platform_arch() -> PlatformArch:
    """Get the platform-arch key (x86_64-windows, x86_64-linux, aarch64-linux, etc.)"""
    arch = platform.machine().lower()
    os_name = platform.system().lower()
    
    # Normalize architecture
    if arch in ["amd64", "x86_64"]:
        arch = "x86_64"
    elif arch == "arm64":
        arch = "aarch64"
    
    return PlatformArch(f"{arch}-{os_name}")

def getenv(var_name, fail_on_missing=True):
    val = os.getenv(var_name)
    if val is None:
        logger.error(f"Environment variable {var_name} is not set!")
        if fail_on_missing:
            exit(1)
        else:
            return None
    return val

def run_dry_runnable(args, dry_run):
    if dry_run:
        logger.info("Dry run: %s" % " ".join(args))
        return CompletedProcess(args, 0, "", "")
    return run(args, capture_output=True, text=True, env=os.environ.copy())

def get_build_number():
    build_number = os.getenv('BUILD_NUMBER')
    if not build_number:
        logger.error("Missing version info. Make sure to set BUILD_NUMBER")
        exit(1)
    return build_number

def get_bundle_info(bundle_key, bundles):
    """Get bundle info from list of bundles by name"""
    if isinstance(bundles, list):
        for bundle in bundles:
            if bundle.get("name") == bundle_key:
                return bundle
        logger.error(f"Bundle key {bundle_key} not found in bundles")
        return None
    else:
        # Legacy dict-based structure (fallback)
        if bundles.get(bundle_key) is None:
            logger.error(f"Bundle key {bundle_key} not found in bundles")
            return None
        return bundles[bundle_key]

def get_inheritable_value(bundle_info, key, bundles):
    value = bundle_info.get(key)
    if value is not None:
        return value
    # Try to get value from the bundle's includes
    if "includes" in bundle_info:
        queue = list(bundle_info["includes"])
        while len(queue) > 0:
            current = queue.pop(0)
            other_conf = get_bundle_info(current, bundles)
            if other_conf is None:
                logger.error(f"Depending bundle key {current} not found in bundles")
                exit(1)
            value = other_conf.get(key)
            if value is not None:
                return value
            queue.extend(other_conf.get("includes", []))
    return value



def get_nodos_version(bundle_info, bundles, platform_arch : PlatformArch):
    """Get the nodos version for a bundle.
    
    Reads version from bundle_info['nodos'][platform_arch.key()].
    Versions can be less specific (e.g., "8.0" instead of "8.0.1.b495").
    
    Args:
        bundle_info: Bundle configuration dict
        bundles: All bundles dict  
        platform_arch: PlatformArch
    """
    
    # Check if nodos dict has version info
    nodos_dict = get_inheritable_value(bundle_info, "nodos", bundles)
    if nodos_dict and isinstance(nodos_dict, dict):
        version = nodos_dict.get(platform_arch.key())
        if version:
            return version
        
        logger.error(f"No version specified for nodos on {platform_arch.key()}")
    else:
        logger.error(f"Missing nodos version configuration for {platform_arch.key()}")
    
    exit(1)

def get_nodos_version_major_minor(version):
    if version is None:
        logger.error("Missing version info. Make sure to set VERSION")
        exit(1)
    version_parts = version.split(".")
    if len(version_parts) < 2:
        logger.error(f"Invalid version format: {version}")
        exit(1)
    # First 2 parts are major, minor
    major = version_parts[0]
    minor = version_parts[1]
    return major, minor

def get_semver_from_full_version(version):
    if version is None:
        logger.error("Missing version info. Make sure to set VERSION")
        exit(1)
    version_parts = version.split(".")
    if len(version_parts) < 3:
        logger.error(f"Invalid version format: {version}")
        exit(1)
    # First 3 parts are major, minor, patch
    major = version_parts[0]
    minor = version_parts[1]
    patch = version_parts[2]
    return major, minor, patch

def resolve_package_version(package_name, package_version):
    logger.info(f"Resolving package {package_name} version {package_version} using nosman info")
    result = run(["./nodos", "-w", WORKSPACE_FOLDER, "info", package_name, package_version, "--relaxed"],
                 capture_output=True, text=True, env=os.environ.copy())
    if result.returncode != 0:
        logger.error(f"nosman info returned with {result.returncode}: {result.stderr}")
        exit(result.returncode)
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        logger.error(f"Failed to parse nosman info output for {package_name} {package_version}: {exc}")
        exit(1)
    resolved_version = info.get("info", {}).get("id", {}).get("version")
    if not resolved_version:
        logger.error(f"Failed to resolve version for {package_name} {package_version}")
        exit(1)
    if resolved_version != package_version:
        logger.info(f"Resolved {package_name} {package_version} -> {resolved_version}")
    return resolved_version

def resolve_package_versions(packages):
    resolved = OrderedDict()
    for pkg_name, pkg_data in packages.items():
        resolved_version = resolve_package_version(pkg_name, pkg_data["version"])
        resolved[pkg_name] = {"name": pkg_name, "version": resolved_version, "type": pkg_data.get("type")}
    return resolved

def rename_package_prefix_folder(base_dir, requested_version, resolved_version):
    if requested_version == resolved_version:
        return
    old_path = os.path.join(base_dir, requested_version)
    new_path = os.path.join(base_dir, resolved_version)
    if not os.path.isdir(old_path):
        logger.warning(f"Expected package folder not found: {old_path}")
        return
    if os.path.exists(new_path):
        logger.warning(f"Resolved package folder already exists: {new_path}")
        return
    shutil.move(old_path, new_path)

def read_profile_plugins(workspace_folder, nodos_version):
    engine_version = resolve_nodos_engine_version(workspace_folder, nodos_version)
    profile_json_path = f"{os.path.abspath(workspace_folder)}/Engine/{engine_version}/Config/Profile.json"
    if not os.path.exists(profile_json_path):
        return []
    with open(profile_json_path, "r") as f:
        profile = json.load(f)
    loaded_plugins = profile.get("loaded_plugins")
    if loaded_plugins is None:
        loaded_plugins = profile.get("loaded_modules")
    if loaded_plugins is None:
        return []
    return loaded_plugins

def resolve_nodos_engine_version(workspace_folder, nodos_version):
    engine_root = os.path.join(workspace_folder, "Engine")
    exact_path = os.path.join(engine_root, nodos_version)
    if os.path.isdir(exact_path):
        return nodos_version
    if not os.path.isdir(engine_root):
        logger.error(f"Nodos Engine folder not found: {engine_root}")
        exit(1)
    candidates = []
    prefix = f"{nodos_version}."
    for name in os.listdir(engine_root):
        full_path = os.path.join(engine_root, name)
        if os.path.isdir(full_path) and name.startswith(prefix):
            candidates.append(name)
    if len(candidates) == 1:
        logger.info(f"Resolved Nodos Engine version {nodos_version} to {candidates[0]}")
        return candidates[0]
    if len(candidates) > 1:
        logger.error(f"Multiple Nodos Engine versions match {nodos_version}: {', '.join(candidates)}")
    else:
        logger.error(f"No Nodos Engine version matches {nodos_version} under {engine_root}")
    exit(1)

def get_release_artifacts(dir, platform_arch : PlatformArch):
    files = glob.glob(f"{dir}/*{platform_arch.compressed_file_extension()}")
    return files

def find_latest_bundle_release_tag(gh_release_repo, engine_version, short_name, platform_arch : PlatformArch):
    major, minor, patch = get_semver_from_full_version(engine_version)
    tag_prefix = f"v{major}.{minor}"
    tag_suffix = f"-{short_name}-{platform_arch.key()}"
    jq_filter = (
        f"map(select(.tagName | startswith(\"{tag_prefix}\") and endswith(\"{tag_suffix}\")))"
        " | sort_by(.createdAt) | reverse | .[0].tagName"
    )
    ghargs = ["gh", "release", "list", "--json", "tagName,createdAt", "--jq", jq_filter]
    if gh_release_repo:
        ghargs.extend(["--repo", gh_release_repo])
    result = run(ghargs, capture_output=True, text=True, env=os.environ.copy())
    if result.returncode != 0:
        logger.warning(f"Failed to list GitHub releases: {result.stderr.strip()}")
        return ""
    tag = result.stdout.strip().strip('"')
    if not tag or tag == "null":
        return ""
    logger.info(f"Found matching release tag: {tag}")
    return tag

def fetch_github_release_info(gh_release_repo, release_tag):
    if not release_tag:
        return {}
    ghargs = ["gh", "release", "view"]
    if release_tag:
        ghargs.append(release_tag)
    ghargs.extend(["--json", "body,name,url,tagName"])
    if gh_release_repo:
        ghargs.extend(["--repo", gh_release_repo])
    result = run(ghargs, capture_output=True, text=True, env=os.environ.copy())
    if result.returncode != 0:
        logger.warning(f"Failed to fetch GitHub release info: {result.stderr.strip()}")
        return {}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        logger.warning(f"Failed to parse GitHub release info: {exc}")
        return {}
    return payload

def _parse_name_version_line(line):
    match = re.match(r"(.+?)\s*[:\-]\s*([0-9A-Za-z][0-9A-Za-z\.\-+_]*?)$", line)
    if match is None:
        match = re.match(r"(.+?)\s+([0-9A-Za-z][0-9A-Za-z\.\-+_]*?)$", line)
    if match is None:
        return None, None
    return match.group(1).strip(), match.group(2).strip()

def parse_release_notes_versions(release_notes_text):
    versions = {"engine": None, "modules": {}, "samples": {}}
    if not release_notes_text:
        return versions
    section = None
    for line in release_notes_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower.startswith("###"):
            if "engine" in lower:
                section = "engine"
            elif "modules" in lower or "plugins" in lower:
                section = "modules"
            elif "samples" in lower:
                section = "samples"
            else:
                section = None
            continue
        if section is None:
            continue
        entry = stripped[1:].strip() if stripped[0] in "-*+" else stripped
        if section == "engine":
            match = re.search(r"(?:version|engine)\s*[:\-]?\s*([0-9A-Za-z][0-9A-Za-z\.\-+_]*?)$", entry, re.IGNORECASE)
            if match is None:
                match = re.match(r"^([0-9A-Za-z][0-9A-Za-z\.\-+_]*?)$", entry)
            if match is not None:
                versions["engine"] = match.group(1)
        else:
            name, version = _parse_name_version_line(entry)
            if name and version:
                versions[section][name] = version
    return versions

def _format_version_change(new_version, old_version):
    if old_version:
        if old_version == new_version:
            return f"{new_version} (no change)"
        return f"{new_version} <- {old_version}"
    return f"{new_version} (new)"

def _lookup_old_version(version_map, version_map_casefold, name):
    old_version = version_map.get(name)
    if old_version:
        return old_version
    return version_map_casefold.get(name.casefold())

def download_nodos(bundle_info, nodos_version):
    force_delete_folder(WORKSPACE_FOLDER)
    logger.info("Reading Nodos version from bundle")

    logger.info(f"Downloading Nodos version {nodos_version} using nosman")
    # Download Nodos
    result = run(["./nodos", "-w", WORKSPACE_FOLDER, "get", "--name", "nodos", "--version", nodos_version, "-y"], stdout=stdout, stderr=stderr, universal_newlines=True)
    if result.returncode != 0:
        logger.error(f"nosman get returned with {result.returncode}")
        exit(result.returncode)

def normalize_bundled_packages(bundled_packages):
    if bundled_packages is None:
        return OrderedDict()
    if isinstance(bundled_packages, dict):
        return OrderedDict(bundled_packages)
    if isinstance(bundled_packages, list):
        normalized = OrderedDict()
        for package in bundled_packages:
            package_name = package.get("name")
            if not package_name:
                logger.error("Bundled package entry missing name")
                exit(1)
            normalized[package_name] = {k: v for k, v in package.items() if k != "name"}
        return normalized
    logger.error(f"Unsupported bundled_packages type: {type(bundled_packages)}")
    exit(1)

def get_bundled_packages(bundle_info, bundles, platform_arch : PlatformArch):
    """Get bundled packages for a bundle using flat platform-arch keys.
    
    Packages use map keys like:
    nos.reflect:
      x86_64-windows: 1.7.13
      x86_64-linux: 1.6.5
    
    Versions can be less specific (e.g., "1.7" instead of "1.7.13.b1112").
    
    Args:
        bundle_info: Bundle configuration dict
        bundles: All bundles dict
        platform_arch: PlatformArch
    """
    
    bundled_packages = OrderedDict()
    if "includes" in bundle_info:
        queue = list(bundle_info["includes"])
        includes = list([])
        while len(queue) > 0:
            current = queue.pop(0)
            includes.extend([current])
            other_conf = get_bundle_info(current, bundles)
            if other_conf is None:
                logger.error(f"Depending bundle key {current} not found in bundles")
                exit(1)
            queue.extend(other_conf.get("includes", []))
        logger.info(f"Adding modules from: {' '.join(includes)}")
        for include in reversed(includes):
            conf = get_bundle_info(include, bundles)
            if conf is None:
                logger.error(f"Include bundle key {include} not found in bundles")
                exit(1)
            others = normalize_bundled_packages(conf.get("bundled_packages", {}))
            for package_name, package_data in others.items():
                bundled_packages[package_name] = package_data

    local_packages = normalize_bundled_packages(bundle_info.get("bundled_packages", {}))
    for package_name, package_data in local_packages.items():
        bundled_packages[package_name] = package_data

    # Process packages with flat platform-arch structure
    packages_map = OrderedDict()
    for package_name, package in bundled_packages.items():
        # Check if version is specified for this platform-arch
        version = package.get(platform_arch.key())
        # Optional type field
        package_type = package.get("type")

        if version:
            # Version explicitly specified
            pkg_data = {
                'name': package_name,
                'version': version,
                'type': package_type
            }
            # Add or update the package in the map
            packages_map[package_name] = pkg_data
        else:
            # No version specified for this platform-arch, skip
            logger.warning(f"Package {package_name} not available for {platform_arch.key()}, skipping")
    
    return packages_map

def download_packages(bundle_info, bundles, nodos_version, platform_arch : PlatformArch):
    logger.info("Deleting old modules")
    force_delete_folder(f"{WORKSPACE_FOLDER}/Module/")
    force_delete_folder(f"{WORKSPACE_FOLDER}/Samples/")
    os.makedirs(f"{WORKSPACE_FOLDER}/Module/", exist_ok=True)
    os.makedirs(f"{WORKSPACE_FOLDER}/Samples/", exist_ok=True)
    logger.info("Collecting module information from bundle")
    result = run(["./nodos", "-w", WORKSPACE_FOLDER, "rescan"], stdout=stdout, stderr=stderr, universal_newlines=True)
    if result.returncode != 0:
        logger.error(f"nosman rescan returned with {result.returncode}")
        exit(result.returncode)
    
    packages_map = get_bundled_packages(bundle_info, bundles, platform_arch)

    downloading_packages_str = ""
    for package in packages_map.keys():
        downloading_packages_str += f"{package} "
    logger.info(f"Downloading packages: {downloading_packages_str}")
    
    absolute_workspace = os.path.abspath(WORKSPACE_FOLDER)

    included_packages = []
    for package in packages_map.values():
        package_name = package["name"]
        package_version = package["version"]
        package_type = package.get("type")
        logger.info(f"Downloading package {package_name} version {package_version} using nosman")
        out_dir = f"{absolute_workspace}/Module/{package_name}"
        if package_type == "sample":
            out_dir = f"{absolute_workspace}/Samples/{package_name}"
        result = run(["./nodos", "-w", WORKSPACE_FOLDER, "install", package_name, package_version, "--out-dir", out_dir, "--prefix", package_version, "--without-deps"], stdout=stdout, stderr=stderr, universal_newlines=True)
        if result.returncode != 0:
            logger.error(f"nosman install returned with {result.returncode}")
            exit(result.returncode)
        resolved_version = resolve_package_version(package_name, package_version)
        rename_package_prefix_folder(out_dir, package_version, resolved_version)
        incl = {"name": package_name, "version": resolved_version, "type": package_type}
        included_packages.append(incl)
    # Write included modules to Profile.json
    engine_version = resolve_nodos_engine_version(WORKSPACE_FOLDER, nodos_version)
    profile_json_path = f"{absolute_workspace}/Engine/{engine_version}/Config/Profile.json"
    profile = {}
    loaded_plugins_key = "loaded_plugins"
    major, minor = get_nodos_version_major_minor(nodos_version)
    # If version lower than 1.4.0 use loaded_modules key
    if int(major) < 1 or (int(major) == 1 and int(minor) < 4):
        loaded_plugins_key = "loaded_modules"
    if loaded_plugins_key not in profile:
        profile[loaded_plugins_key] = []
    included_plugins = []
    for package in included_packages:
        if "type" not in package or package["type"] != "sample":
            included_plugins.append({"name": package["name"], "version": package["version"]})
    profile[loaded_plugins_key].extend(included_plugins)
    with open(f"{profile_json_path}", "w") as f:
        json.dump(profile, f, indent=2)

def package(bundle_key, bundle_info, nodos_version, bundles, platform_arch : PlatformArch):
    logger.info("Packaging Nodos")
    force_delete_folder(ARTIFACTS_FOLDER)
    force_delete_folder(f"{WORKSPACE_FOLDER}/.nosman")
    run([f"{WORKSPACE_FOLDER}/nodos", "-w", WORKSPACE_FOLDER, "init"], stdout=stdout, stderr=stderr, universal_newlines=True)
    force_delete_folder(f"{WORKSPACE_FOLDER}/.nosman/remote")
    engine_version = resolve_nodos_engine_version(WORKSPACE_FOLDER, nodos_version)
    engine_folder = f"{WORKSPACE_FOLDER}/Engine/{engine_version}"
    engine_settings_path = f"{engine_folder}/Config/Defaults/EngineSettings.json"
    if not os.path.exists(engine_settings_path):
        engine_settings_path = f"{engine_folder}/Config/EngineSettings.json"
        if not os.path.exists(engine_settings_path):
            logger.error(f"Engine settings file not found in both {engine_folder}/Config and {engine_folder}/Config/Defaults")
            exit(1)
    with open(engine_settings_path, "r") as f:
        engine_settings = json.load(f)
        major, minor = get_nodos_version_major_minor(nodos_version)
        use_plugins_keys = int(major) > 1 or (int(major) == 1 and int(minor) >= 4)
        index_urls_key = "plugin_index_urls" if use_plugins_keys else "module_index_urls"
        engine_index_urls_key = "remote_plugins" if use_plugins_keys else "remote_modules"

        module_index_urls = get_inheritable_value(bundle_info, index_urls_key, bundles)
        engine_index_url = get_inheritable_value(bundle_info, "engine_index_url", bundles)
        if module_index_urls is None:
            logger.error(f"Missing {index_urls_key} in bundle or included bundles")
            exit(1)
        if engine_index_url is None:
            logger.error("Missing engine_index_url in bundle or included bundles")
            exit(1)
        engine_settings[engine_index_urls_key] = module_index_urls
        engine_settings["engine_index_url"] = engine_index_url

    with open(engine_settings_path, "w") as f:
        json.dump(engine_settings, f, indent=2)

    major, minor, patch = get_semver_from_full_version(engine_version)
    # Zip everything under workspace_folder
    shutil.make_archive(f"{ARTIFACTS_FOLDER}/Nodos-{major}.{minor}.{patch}.b{get_build_number()}-bundle-{bundle_key}-{platform_arch.key()}", platform_arch.compression_type(), f"{WORKSPACE_FOLDER}")

def create_nodos_release(gh_release_repo, gh_release_target_branch, gh_release_prev_tag, dry_run_release, skip_nosman_publish, bundle_info, nodos_version, bundle_key, bundles, platform_arch : PlatformArch):
    short_name = bundle_info.get("short_name")
    if short_name is None:
        logger.info("Missing short name in bundle info, choosing short name as bundle key")
        short_name = bundle_key
    release_repo, target_branch = gh_release_repo, gh_release_target_branch
    artifacts = get_release_artifacts(ARTIFACTS_FOLDER, platform_arch)
    if len(artifacts) == 0:
        logger.error("No artifacts found to release")
        exit(1)
    for path in artifacts:
        logger.info(f"Release artifact: {path}")
    engine_version = resolve_nodos_engine_version(WORKSPACE_FOLDER, nodos_version)
    major, minor, patch = get_semver_from_full_version(engine_version)
    build_number = get_build_number()
    tag = f"v{major}.{minor}.{patch}.b{build_number}-{short_name}-{platform_arch.key()}"
    title = f"{tag}"

    bundled_packages = get_bundled_packages(bundle_info, bundles, platform_arch)
    resolved_packages = resolve_package_versions(bundled_packages)

    resolved_modules = OrderedDict((name, data) for name, data in resolved_packages.items() if data.get("type") != "sample" )
    resolved_samples = OrderedDict((name, data) for name, data in resolved_packages.items() if data.get("type") == "sample" )

    previous_tag = gh_release_prev_tag
    if not previous_tag:
        previous_tag = find_latest_bundle_release_tag(release_repo, engine_version, short_name, platform_arch)
    previous_release_info = fetch_github_release_info(release_repo, previous_tag)
    previous_release_notes = previous_release_info.get("body", "") if previous_release_info else ""
    previous_versions = parse_release_notes_versions(previous_release_notes)
    previous_modules = previous_versions.get("modules", {})
    previous_modules_casefold = {name.casefold(): version for name, version in previous_modules.items()}
    previous_samples = previous_versions.get("samples", {})
    previous_samples_casefold = {name.casefold(): version for name, version in previous_samples.items()}

    # Create release notes with version changes
    release_notes = f"## Nodos {engine_version}\n\n"
    release_notes += f"### Engine\n"
    release_notes += f"- Version: {_format_version_change(engine_version, previous_versions.get('engine'))}\n\n"
    release_notes += f"### Modules ({len(resolved_modules)})\n"
    for pkg_name, pkg_data in resolved_modules.items():
        old_version = _lookup_old_version(previous_modules, previous_modules_casefold, pkg_name)
        release_notes += f"- {pkg_name}: {_format_version_change(pkg_data['version'], old_version)}\n"

    if len(resolved_samples) > 0:
        release_notes += f"\n### Samples ({len(resolved_samples)})\n"
    for pkg_name, pkg_data in resolved_samples.items():
        old_version = _lookup_old_version(previous_samples, previous_samples_casefold, pkg_name)
        release_notes += f"- {pkg_name}: {_format_version_change(pkg_data['version'], old_version)}\n"

    if previous_release_info:
        previous_title = previous_release_info.get("name") or previous_release_info.get("tagName") or previous_tag
        previous_url = previous_release_info.get("url")
        if not previous_url and release_repo and previous_tag:
            previous_url = f"https://github.com/{release_repo}/releases/tag/{previous_tag}"
        if previous_title and previous_url:
            release_notes += "\n### Previous Release\n"
            release_notes += f"- [{previous_title}]({previous_url})\n"

    ghargs = ["gh", "release", "create", tag, *artifacts, "--notes", f"{release_notes}", "--title", title]
    if target_branch != "":
        logger.info(f"GitHub Release: Using target branch {target_branch}")
        ghargs.extend(["--target", target_branch])
    else:
        logger.info("GitHub Release: Using default branch")
    if release_repo != "":
        logger.info(f"GitHub Release: Using repo {release_repo}")
        ghargs.extend(["--repo", release_repo])
    else:
        logger.info("GitHub Release: The repo inside the current directory will be used with '--generate-notes' option")
        ghargs.extend(["--generate-notes"])
    logger.info(f"GitHub Release: Pushing release artifacts to repo {release_repo}")
    result = run_dry_runnable(ghargs, dry_run_release)
    if result.returncode != 0:
        logger.error(f"GitHub CLI returned with error {result.stderr} and code {result.returncode}")
        exit(result.returncode)
    logger.info("GitHub release successful")
    if skip_nosman_publish:
        return

    version = f"{major}.{minor}.{patch}.b{build_number}"
    nodos_zip_prefix = f"Nodos-{version}"

    artifacts_abspath = [os.path.abspath(path) for path in artifacts]
    package_name = bundle_info.get("package_name")
    if package_name is None:
        logger.warning(f"Missing package name in bundle info, setting it to 'nodos.bundle.{short_name}'")
        package_name = f"nodos.bundle.{short_name}"

    for path in artifacts_abspath:
        abspath = os.path.abspath(path)
        file_name = os.path.basename(path)
        if not file_name.startswith(nodos_zip_prefix):
            continue
        # If file_name is of format Nodos-{major}.{minor}.{patch}.b{build_number}-bundle-{dist_key}.zip, it is a bundled distribution. Get the dist_key from it.
        dist_key = None
        if file_name.startswith(f"{nodos_zip_prefix}-bundle-"):
            dist_key = file_name.split("-bundle-")[1].split(platform_arch.compressed_file_extension())[0]
        # Use nosman to publish Nodos:
        logger.info("Running nosman publish")
        nosman_args = [f"./nodos", "-w", WORKSPACE_FOLDER, "publish", "--path", path, 
                       "--name", package_name, "--version", f"{major}.{minor}.{patch}", "--version-suffix", f".b{build_number}", 
                       "--type", "nodos", "--vendor", "Nodos", "--publisher-name", "Nodos", "--publisher-email", "bot@nodos.dev",
                       "--version-check", "loose"]
        if dry_run_release:
            nosman_args.append("--dry-run")
        logger.info(f"Running nosman publish with args: {nosman_args}")
        result = run(nosman_args, stdout=stdout, stderr=stderr, universal_newlines=True)
        if result.returncode != 0:
            logger.error(f"nosman publish returned with {result.returncode}")
            exit(result.returncode)

if __name__ == "__main__":
    logger.remove()
    logger.add(stdout, format="<green>[Distribute Nodos]</green> <level>{time:HH:mm:ss.SSS}</level> <level>{level}</level> <level>{message}</level>")

    parser = argparse.ArgumentParser(
        description="Create distribution packages for Nodos")
    parser.add_argument("--version",
                         help="The nodos version (1.2, 1.3, 1.4, etc.)",
                        action="store",
                        required=False)
    parser.add_argument("--bundle-key",
                         help="The key of the bundle to package",
                        action="store",
                        required=False)
    parser.add_argument("--bundles-yaml-path",
                         help="The path to the bundles YAML file",
                        action="store",
                        required=False)
    # TODO: Add option to release for another platform
    #parser.add_argument("--target-platform",
    #                     help="The target platform (linux, windows, etc.)",
    #                    action="store",
    #                    required=False)

    parser.add_argument('--gh-release',
                        action='store_true',
                        default=False,
                        help="Create a GitHub release with the installer executables")

    parser.add_argument('--gh-release-repo',
                        action='store',
                        default='',
                        help="The repo of the release. If empty, the repo of the current directory will be used with '--generate-notes' option of the GitHub CLI.")

    parser.add_argument('--gh-release-target-branch',
                        action='store',
                        default='',
                        help="The branch to create the release on. If empty, the current branch will be used.")

    parser.add_argument('--gh-release-prev-tag',
                        action='store',
                        default='',
                        help="The tag of the previous release to compare against. If empty, the latest release is used.")

    parser.add_argument('--dry-run-release',
                        action='store_true',
                        default=False)
    
    parser.add_argument('--skip-nosman-publish',
                        action='store_true',
                        default=False)
    
    parser.add_argument('--download-nodos',
                         action='store_true',
                        default=False,
                        help="Download Nodos using nosman")

    parser.add_argument('--download-packages',
                         action='store_true',
                        default=False,
                        help="Download modules using nosman")

    parser.add_argument('--pack',
                        action='store_true',
                        default=False,
                        help="Create a zip file for the bundle")

    args = parser.parse_args()

    bundle_info = None
    platform_arch = get_cur_platform_arch()
    logger.info(f"Using platform-arch key: {platform_arch.key()}") 

    if args.bundles_yaml_path:
        # Load YAML file
        bundles_data = load_bundles_data(args.bundles_yaml_path)
    elif args.version:
        # Auto-detect YAML file based on version
        yaml_path = f"nodos-{args.version}.yaml"
        if not os.path.exists(yaml_path):
            logger.error(f"Bundle file {yaml_path} not found")
            exit(1)
        bundles_data = load_bundles_data(yaml_path)
        
    else:
        logger.error("Either --version or --bundles-yaml-path must be specified")
        exit(1)
    bundles = bundles_data.get("bundles")

    if args.bundle_key:
        bundle_info = get_bundle_info(args.bundle_key, bundles)

    nodos_version = None
    if bundle_info:
        nodos_version = get_nodos_version(bundle_info, bundles, platform_arch)

    if bundles is None:
        logger.error("Failed to read bundles. Missing 'bundles' key")
        exit(1)

    if args.bundle_key and bundle_info is None:
        logger.error(f"Failed to read bundle info for key {args.bundle_key}")
        exit(1)

    if args.download_nodos:
        if bundle_info is None or nodos_version is None:
            logger.error("Bundle key and version required for --download-nodos")
            exit(1)
        download_nodos(bundle_info, nodos_version)

    if args.download_packages:
        if bundle_info is None or nodos_version is None:
            logger.error("Bundle key and version required for --download-packages")
            exit(1)
        download_packages(bundle_info, bundles, nodos_version, platform_arch)

    if args.pack:
        if bundle_info is None or nodos_version is None or args.bundle_key is None:
            logger.error("Bundle key and version required for --pack")
            exit(1)
        package(args.bundle_key, bundle_info, nodos_version, bundles, platform_arch)

    if args.gh_release:
        if bundle_info is None or nodos_version is None or args.bundle_key is None:
            logger.error("Bundle key and version required for --gh-release")
            exit(1)
        create_nodos_release(args.gh_release_repo, args.gh_release_target_branch, args.gh_release_prev_tag, args.dry_run_release, args.skip_nosman_publish, bundle_info, nodos_version, args.bundle_key, bundles, platform_arch)
