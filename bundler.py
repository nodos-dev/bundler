import argparse
from subprocess import run, CalledProcessError
from sys import stderr, stdout
from loguru import logger
import os
import yaml
import platform
import json
import re
from collections import OrderedDict


WORKSPACE_FOLDER = "./workspace"
ARTIFACTS_FOLDER = "./Artifacts/"

SUPPORTED_PLATFORM_KEYS = ("x86_64-windows", "x86_64-linux", "aarch64-linux", "aarch64-macos")

class PlatformArch:
    def __init__(self, arch_os_key: str):
        parts = arch_os_key.split("-")
        self.arch = parts[0]
        self.os_name = parts[1]

    def key(self) -> str:
        return f"{self.arch}-{self.os_name}"

class BundlesYamlLoader(yaml.SafeLoader):
    pass

def _remove_implicit_resolver(loader_cls, tag_to_remove):
    # yaml_implicit_resolvers belongs to yaml.resolver.Resolver, a mixin shared by
    # every loader and dumper, not just this loader. Without its own copy here,
    # mutating it below edits that one shared dict in place: it would disable
    # int/float parsing for every yaml.safe_load() in the process, and on the way
    # out it would let the dumper stop quoting a version string that reads like a
    # number (e.g. "5.0"), which then loads back as a float instead of a string.
    if "yaml_implicit_resolvers" not in loader_cls.__dict__:
        loader_cls.yaml_implicit_resolvers = {
            ch: list(resolvers) for ch, resolvers in loader_cls.yaml_implicit_resolvers.items()
        }
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

def is_cwd_or_an_ancestor(path):
    """True if path resolves to the current directory or one of its parents. Guards
    force_delete_folder: a wrong or empty --out-dir must never delete the directory the
    bundler is running from, or something above it."""
    target = os.path.abspath(path)
    current = os.path.abspath(".")
    while True:
        if current == target:
            return True
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent

def force_delete_folder(folder_path):
    """Forcefully deletes a folder, handling permission issues."""
    if not os.path.exists(folder_path):
        return
    if is_cwd_or_an_ancestor(folder_path):
        logger.error(f"Refusing to delete {folder_path}: it is the current directory or "
                     f"one of its parents")
        exit(1)

    try:
        if os.name == "nt":  # Windows
            run(["powershell", "-Command", "Remove-Item", "-Path", folder_path, "-Recurse", "-Force"], shell=True, check=True)
        else:  # Linux/macOS
            run(["rm", "-rf", folder_path], check=True)
    except CalledProcessError as e:
        logger.error(f"Error deleting {folder_path}: {e}")
        exit(1)

def get_cur_platform_arch() -> PlatformArch:
    """Get the platform-arch key (x86_64-windows, x86_64-linux, aarch64-linux, etc.)"""
    arch = platform.machine().lower()
    os_name = platform.system().lower()
    
    # Normalize architecture
    if arch in ["amd64", "x86_64"]:
        arch = "x86_64"
    elif arch == "arm64":
        arch = "aarch64"

    # Python calls macOS "darwin"; nosman, the store and the bundle files say "macos".
    if os_name == "darwin":
        os_name = "macos"

    key = f"{arch}-{os_name}"
    if key not in SUPPORTED_PLATFORM_KEYS:
        logger.error(f"Unsupported host platform: {key}. The bundler runs on one of: "
                     f"{', '.join(SUPPORTED_PLATFORM_KEYS)}")
        exit(1)
    return PlatformArch(key)

def parse_platform_keys(platforms_arg):
    """The requested --platforms as PlatformArch objects, in the order given, or the host
    platform when nothing was given. Exits 1 naming the first key that is not one of the
    four supported platform ids."""
    if not platforms_arg:
        return [get_cur_platform_arch()]
    keys = [key.strip() for key in platforms_arg.split(",") if key.strip()]
    for key in keys:
        if key not in SUPPORTED_PLATFORM_KEYS:
            logger.error(f"Unsupported platform: {key}. Supported platforms are: "
                         f"{', '.join(SUPPORTED_PLATFORM_KEYS)}")
            exit(1)
    return [PlatformArch(key) for key in keys]

def get_build_number():
    build_number = os.getenv('BUILD_NUMBER')
    if not build_number:
        logger.error("Missing version info. Make sure to set BUILD_NUMBER")
        exit(1)
    return build_number

def normalize_bundle_version(value, fail_on_missing=True):
    if value is None or str(value).strip() == "":
        if fail_on_missing:
            logger.error("Missing bundle version")
            exit(1)
        return None
    bundle_version_str = str(value).strip()
    if not bundle_version_str.isdigit():
        logger.error(f"Invalid bundle version: {value}. Bundle version must be a non-negative integer")
        exit(1)
    bundle_version = int(bundle_version_str)
    if bundle_version < 0:
        logger.error(f"Invalid bundle version: {value}. Bundle version must be zero or greater")
        exit(1)
    return bundle_version

def _get_matching_bundles(bundle_key, bundles):
    if isinstance(bundles, list):
        return [bundle for bundle in bundles if bundle.get("name") == bundle_key]
    if bundles.get(bundle_key) is None:
        return []
    return [bundles[bundle_key]]

def _format_available_bundle_versions(bundles):
    versions = []
    for bundle in bundles:
        bundle_version = bundle.get("version")
        if bundle_version is None:
            versions.append("(missing)")
        else:
            versions.append(str(bundle_version))
    return ", ".join(versions)

def _select_latest_bundle(matching_bundles):
    return max(
        matching_bundles,
        key=lambda bundle: normalize_bundle_version(bundle.get("version"), fail_on_missing=False) or 0
    )

def get_bundle_info(bundle_key, bundles, bundle_version=None, fail_on_missing=True):
    """Get bundle info from list of bundles by name and optional bundle version."""
    matching_bundles = _get_matching_bundles(bundle_key, bundles)
    if len(matching_bundles) == 0:
        if fail_on_missing:
            logger.error(f"Bundle key {bundle_key} not found in bundles")
        return None

    normalized_requested_version = normalize_bundle_version(bundle_version, fail_on_missing=False)
    if normalized_requested_version is not None:
        version_matches = [
            bundle for bundle in matching_bundles
            if normalize_bundle_version(bundle.get("version")) == normalized_requested_version
        ]
        if len(version_matches) == 1:
            return version_matches[0]
        if len(version_matches) > 1:
            if fail_on_missing:
                logger.error(f"Multiple bundle entries found for {bundle_key} version {normalized_requested_version}")
            return None
        if fail_on_missing:
            available_versions = _format_available_bundle_versions(matching_bundles)
            logger.error(
                f"Bundle key {bundle_key} with version {normalized_requested_version} not found in bundles. "
                f"Available versions: {available_versions}"
            )
        return None

    if len(matching_bundles) == 1:
        return matching_bundles[0]

    latest_bundle = _select_latest_bundle(matching_bundles)
    if fail_on_missing:
        logger.info(
            f"Multiple bundle entries found for {bundle_key}. "
            f"Selecting latest version {get_bundle_version(latest_bundle)} by default"
        )
    return latest_bundle

def parse_include_ref(include_ref):
    if isinstance(include_ref, str):
        return include_ref, None
    if isinstance(include_ref, dict):
        include_name = include_ref.get("name")
        if not include_name:
            logger.error("Include entry missing name")
            exit(1)
        include_version = include_ref.get("version")
        return include_name, normalize_bundle_version(include_version, fail_on_missing=False)
    logger.error(f"Unsupported include type: {type(include_ref)}")
    exit(1)

def format_include_ref(include_ref):
    include_name, include_version = parse_include_ref(include_ref)
    if include_version is None:
        return include_name
    return f"{include_name}@{include_version}"

def resolve_included_bundle_info(include_ref, bundles, requested_bundle_version):
    include_name, include_version = parse_include_ref(include_ref)
    if include_version is not None:
        return get_bundle_info(include_name, bundles, include_version)
    bundle_info = get_bundle_info(include_name, bundles, requested_bundle_version, fail_on_missing=False)
    if bundle_info is not None:
        return bundle_info
    return get_bundle_info(include_name, bundles)

def get_inheritable_value(bundle_info, key, bundles):
    value = bundle_info.get(key)
    if value is not None:
        return value
    # Try to get value from the bundle's includes
    requested_bundle_version = get_bundle_version(bundle_info)
    if "includes" in bundle_info:
        queue = list(bundle_info["includes"])
        visited = set()
        while len(queue) > 0:
            include_ref = queue.pop(0)
            other_conf = resolve_included_bundle_info(include_ref, bundles, requested_bundle_version)
            if other_conf is None:
                logger.error(f"Depending bundle {format_include_ref(include_ref)} not found in bundles")
                exit(1)
            bundle_identity = (other_conf.get("name"), get_bundle_version(other_conf))
            if bundle_identity in visited:
                continue
            visited.add(bundle_identity)
            value = other_conf.get(key)
            if value is not None:
                return value
            queue.extend(other_conf.get("includes", []))
    return value



def find_nodos_version(bundle_info, bundles, platform_arch : PlatformArch):
    """The Nodos version a bundle asks for on one platform, or None when it asks for
    none there. A bundle with no Nodos version on a platform is not published for it."""
    nodos_config = get_inheritable_value(bundle_info, "nodos", bundles)
    if not nodos_config:
        return None
    if isinstance(nodos_config, str):
        return nodos_config
    if isinstance(nodos_config, dict):
        return nodos_config.get(platform_arch.key()) or nodos_config.get("version")
    logger.error(f"Unexpected nodos configuration type: {type(nodos_config)}")
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

NODOS_PACKAGE_NAME = "nodos"

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

# A release with no platform group applies to every target platform.
ANY_PLATFORM = "any"

# `nosman list --store` prints a "Nodos Store versions" header, then one indented
# "  <version>" line per release, each optionally followed by a "(<platform>)" group
# and whatever else it knows about the release. Only the first two groups are read;
# a release with no platform group matches ANY_PLATFORM. The version must start with
# a digit so the header line itself is never mistaken for a release.
STORE_RELEASE_LINE = re.compile(r"^\s*(\d\S*)(?:\s+\(([0-9a-z_]+-[a-z]+)\))?")

_store_releases_cache = {}

def ensure_workspace():
    """A nosman workspace for the store calls to run in. Nothing is installed into it;
    it only gives nosman somewhere to keep its index and credentials."""
    if os.path.exists(f"{WORKSPACE_FOLDER}/.nosman/index"):
        return
    os.makedirs(WORKSPACE_FOLDER, exist_ok=True)
    result = run(["nosman", "-w", WORKSPACE_FOLDER, "init", "--allow-nested"],
                 stdout=stdout, stderr=stderr, universal_newlines=True)
    if result.returncode != 0:
        logger.error(f"nosman init returned with {result.returncode}")
        exit(result.returncode)

def list_store_releases(package_name):
    """Every release of a package on the store, as (version, platform) pairs. A
    release with no platform group is paired with ANY_PLATFORM."""
    if package_name in _store_releases_cache:
        return _store_releases_cache[package_name]
    ensure_workspace()
    logger.info(f"Listing {package_name} releases on the store")
    result = run(["nosman", "-w", WORKSPACE_FOLDER, "list", "--store", "-p", package_name],
                 capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"nosman list returned with {result.returncode}: {result.stderr}")
        exit(result.returncode)
    releases = []
    for line in result.stdout.splitlines():
        match = STORE_RELEASE_LINE.match(ANSI_ESCAPE.sub("", line))
        if match is not None:
            release_platform = match.group(2) if match.group(2) is not None else ANY_PLATFORM
            releases.append((match.group(1), release_platform))
    if len(releases) == 0:
        # nosman warns on stderr and exits 0 when the store or auth call fails, so a
        # failed listing looks just like a package with no releases. Treat finding
        # nothing as a failure instead of silently resolving no version anywhere.
        logger.error(f"nosman list returned no releases for {package_name}")
        logger.error(f"stdout: {result.stdout}")
        logger.error(f"stderr: {result.stderr}")
        exit(1)
    _store_releases_cache[package_name] = releases
    return releases

def _parse_store_version(version_str):
    """Split a store version or version prefix into its numeric parts and an
    optional build number, matching nosman's SemVer parsing (index.rs:168-174): a
    fourth part, written "bNNN" or as a plain integer, is the build number, so
    "1.2.3.4" and "1.2.3.b4" name the same version. Raises ValueError if a numeric
    part is not an integer.
    """
    parts = version_str.split(".")
    if len(parts) > 4:
        raise ValueError(f"{version_str} has more than four parts")
    build_number = None
    if len(parts) > 3:
        build_part = parts[3][1:] if parts[3].startswith("b") else parts[3]
        build_number = int(build_part)
        parts = parts[:3]
    return tuple(int(p) for p in parts), build_number

def version_sort_key(version):
    """Orders store versions oldest first. The build number separates two releases
    that share a semantic version."""
    numeric_parts, build_number = _parse_store_version(version)
    return (numeric_parts, build_number if build_number is not None else 0)

def version_matches_prefix(version, prefix):
    """True if version matches prefix the way nosman's SemVer::matches_prefix does:
    major must match, and each further part the prefix carries (minor, patch, build)
    must equal version's. A prefix that carries a build number is an exact pin: it
    matches only that build, not every build sharing the same major.minor.patch.
    """
    version_parts, version_build = _parse_store_version(version)
    prefix_parts, prefix_build = _parse_store_version(prefix)
    if version_parts[:len(prefix_parts)] != prefix_parts:
        return False
    if prefix_build is not None and version_build != prefix_build:
        return False
    return True

def version_prefixes_agree(a, b):
    """True when two version prefixes can name the same release: every part they both
    write is equal. "1.5" agrees with "1.5.0" and "1.5.0.b4711"; "1.5" and "1.6" do
    not, nor do "1.5.0.b1" and "1.5.0.b2". Raises ValueError on an unparseable part."""
    a_parts, a_build = _parse_store_version(a)
    b_parts, b_build = _parse_store_version(b)
    common = min(len(a_parts), len(b_parts))
    if a_parts[:common] != b_parts[:common]:
        return False
    if a_build is not None and b_build is not None and a_build != b_build:
        return False
    return True

def resolve_package_version(package_name, version_prefix, platform_arch : PlatformArch):
    """The newest release of a package matching a version prefix on one platform, or
    None when that platform has none."""
    try:
        _parse_store_version(version_prefix)
    except ValueError:
        logger.error(f"Cannot parse version prefix for {package_name}: {version_prefix}")
        exit(1)
    candidates = []
    for version, release_platform in list_store_releases(package_name):
        if release_platform != ANY_PLATFORM and release_platform != platform_arch.key():
            continue
        try:
            if version_matches_prefix(version, version_prefix):
                candidates.append(version)
        except ValueError:
            logger.warning(f"Skipping {package_name} release with an unparseable version: {version}")
    if len(candidates) == 0:
        return None
    resolved = max(candidates, key=version_sort_key)
    if resolved != version_prefix:
        logger.info(f"Resolved {package_name} {version_prefix} -> {resolved} for {platform_arch.key()}")
    return resolved

def get_bundle_version(bundle_info):
    bundle_version = bundle_info.get("version")
    if bundle_version is None:
        logger.error("Missing bundle version in bundle info. Add a 'version' field to the bundle YAML")
        exit(1)
    return normalize_bundle_version(bundle_version)

def get_bundle_publish_version(nodos_version, bundle_version, build_number):
    major, minor = get_nodos_version_major_minor(nodos_version)
    return f"{major}.{minor}.{bundle_version}.b{build_number}"

BUNDLE_MANIFEST_SCHEMA_VERSION = 1

def get_bundle_package_name(bundle_info):
    package_name = bundle_info.get("package_name")
    if package_name is not None:
        return package_name
    short_name = bundle_info.get("short_name")
    if short_name is None:
        short_name = bundle_info.get("name")
    return f"nodos.bundle.{short_name}"

def bundle_chain(bundle_info, bundles):
    """Every bundle a bundle needs, each before the bundles that include it, ending with
    the bundle itself. This is the order the manifests are published in."""
    chain = []
    visited = set()
    in_progress_names = []
    in_progress = set()

    def visit(info):
        identity = (info.get("name"), get_bundle_version(info))
        if identity in visited:
            return
        if identity in in_progress:
            cycle = in_progress_names + [info.get("name")]
            logger.error(f"Include cycle: {' -> '.join(cycle)}")
            exit(1)
        in_progress.add(identity)
        in_progress_names.append(info.get("name"))
        for include_ref in info.get("includes", []):
            included = resolve_included_bundle_info(include_ref, bundles, get_bundle_version(info))
            if included is None:
                logger.error(f"Included bundle {format_include_ref(include_ref)} not found in bundles")
                exit(1)
            visit(included)
        in_progress_names.pop()
        in_progress.discard(identity)
        visited.add(identity)
        chain.append(info)

    visit(bundle_info)

    # Two entries with one package name would publish two versions of it and pin
    # whichever came last, whatever the includer asked for.
    by_package_name = {}
    for info in chain:
        package_name = get_bundle_package_name(info)
        if package_name in by_package_name:
            logger.error(
                f"{bundle_info.get('name')} would publish {package_name} at two bundle "
                f"versions: {get_bundle_version(by_package_name[package_name])} and "
                f"{get_bundle_version(info)}. Make its includes agree on one.")
            exit(1)
        by_package_name[package_name] = info
    return chain

# The folder patterns a manifest groups its packages under, in the order they are
# written. {name} and {version} are filled in per package by whoever installs it.
MODULE_PATTERN = "Module/{name}/{version}"
SAMPLE_PATTERN = "Samples/{name}"
APP_PATTERN = "Apps/{name}"
PACKAGE_PATTERNS = (MODULE_PATTERN, SAMPLE_PATTERN, APP_PATTERN)

PATTERN_BY_TYPE = {"sample": SAMPLE_PATTERN, "app": APP_PATTERN}

def package_pattern(package):
    return PATTERN_BY_TYPE.get(package.get("type"), MODULE_PATTERN)

def member_path(pattern, name, version):
    return pattern.replace("{name}", name).replace("{version}", version)

def check_nodos_pin(bundle_info, bundles, platform_arch : PlatformArch, nodos_version):
    """A bundle that includes another one takes its Nodos release from an include-less
    base in its chain: its own pin if it has one, or whichever base resolves first
    otherwise. Two different include-less bases disagreeing, or an own pin disagreeing
    with a base, would put two Nodos releases in the expansion, which the store refuses,
    so say so before anything is published, whether or not this bundle pins one itself."""
    own_pin = bundle_info.get("nodos") is not None
    for included in bundle_chain(bundle_info, bundles)[:-1]:
        if len(included.get("includes", [])) > 0:
            continue
        base_version = find_nodos_version(included, bundles, platform_arch)
        if base_version is None:
            # This base has no Nodos version on this platform at all, so it says
            # nothing about whether the pin is right; keep checking the other bases.
            continue
        try:
            agree = version_prefixes_agree(base_version, nodos_version)
        except ValueError:
            logger.error(f"Cannot parse a Nodos version of {bundle_info.get('name')} or "
                         f"{included.get('name')}: {nodos_version}, {base_version}")
            exit(1)
        if not agree:
            if own_pin:
                logger.error(
                    f"{bundle_info.get('name')} pins Nodos {nodos_version} but takes "
                    f"{base_version} from {included.get('name')}. Move the pin to "
                    f"{included.get('name')} or drop it.")
            else:
                logger.error(
                    f"{bundle_info.get('name')} would take two different Nodos versions "
                    f"from its includes: {nodos_version} and {base_version} from "
                    f"{included.get('name')}. Pin one Nodos version on "
                    f"{bundle_info.get('name')} or make its includes agree.")
            exit(1)

def check_no_conflicting_packages(bundle_info, bundles, platform_arch : PlatformArch):
    """A bundle's expanded member set is its own bundled packages plus every bundle it
    includes, however deeply. A package pinned at two different versions somewhere in
    that set would collide on the same Module/<name>/<version> path, or leave two
    versions installed side by side, so refuse it before anything is written."""
    resolved_by_name = {}
    for info in bundle_chain(bundle_info, bundles):
        for package in get_own_bundled_packages(info, platform_arch).values():
            resolved = resolve_package_version(package["name"], package["version"], platform_arch)
            if resolved is None:
                continue
            owner = info.get("name")
            if package["name"] not in resolved_by_name:
                resolved_by_name[package["name"]] = (owner, resolved)
                continue
            prev_owner, prev_version = resolved_by_name[package["name"]]
            if prev_version != resolved:
                logger.error(
                    f"{bundle_info.get('name')} would install two versions of "
                    f"{package['name']}: {prev_version} from {prev_owner} and "
                    f"{resolved} from {owner}.")
                exit(1)

def build_bundle_manifest(bundle_info, bundles, platform_arch : PlatformArch, published_versions):
    """The manifest for one bundle on one platform, or None when the bundle has no Nodos
    version there. published_versions holds the version this run publishes for each
    bundle, keyed by package name."""
    nodos_version = find_nodos_version(bundle_info, bundles, platform_arch)
    if nodos_version is None:
        return None

    # Plain dicts: yaml.safe_dump cannot represent an OrderedDict, and dicts keep
    # insertion order, which is the order the keys are written in.
    manifest = {"schema_version": BUNDLE_MANIFEST_SCHEMA_VERSION}
    include_refs = bundle_info.get("includes", [])
    if len(include_refs) == 0:
        resolved = resolve_package_version(NODOS_PACKAGE_NAME, nodos_version, platform_arch)
        if resolved is None:
            logger.error(f"No {NODOS_PACKAGE_NAME} release matches {nodos_version} on {platform_arch.key()}")
            exit(1)
        manifest["nodos"] = resolved
    else:
        check_nodos_pin(bundle_info, bundles, platform_arch, nodos_version)
        includes = {}
        for include_ref in include_refs:
            included = resolve_included_bundle_info(include_ref, bundles, get_bundle_version(bundle_info))
            if included is None:
                logger.error(f"Included bundle {format_include_ref(include_ref)} not found in bundles")
                exit(1)
            package_name = get_bundle_package_name(included)
            if package_name not in published_versions:
                logger.error(f"{package_name} has no version published in this run")
                exit(1)
            if package_name in includes:
                logger.error(f"{bundle_info.get('name')} includes {included.get('name')} twice")
                exit(1)
            includes[package_name] = published_versions[package_name]
        manifest["includes"] = includes

    groups = dict((pattern, {}) for pattern in PACKAGE_PATTERNS)
    for package in get_own_bundled_packages(bundle_info, platform_arch).values():
        resolved = resolve_package_version(package["name"], package["version"], platform_arch)
        if resolved is None:
            logger.error(f"No {package['name']} release matches {package['version']} on {platform_arch.key()}")
            exit(1)
        groups[package_pattern(package)][package["name"]] = resolved
    packages = dict((pattern, versions) for pattern, versions in groups.items() if len(versions) > 0)
    if len(packages) > 0:
        manifest["packages"] = packages

    check_no_conflicting_packages(bundle_info, bundles, platform_arch)

    return manifest

def build_manifests(bundle_info, bundles, platform_arch : PlatformArch, build_number):
    """Every manifest this run publishes for one platform, each bundle after the bundles
    it includes. Returns (package name, version, manifest) triples."""
    published_versions = {}
    manifests = []
    for info in bundle_chain(bundle_info, bundles):
        nodos_version = find_nodos_version(info, bundles, platform_arch)
        if nodos_version is None:
            logger.info(f"{info.get('name')} has no Nodos version for {platform_arch.key()}, leaving the platform out")
            continue
        manifest = build_bundle_manifest(info, bundles, platform_arch, published_versions)
        if manifest is None:
            continue
        package_name = get_bundle_package_name(info)
        version = get_bundle_publish_version(nodos_version, get_bundle_version(info), build_number)
        published_versions[package_name] = version
        manifests.append((package_name, version, manifest))
    return manifests

def platforms_to_publish(bundle_info, bundles, platform_archs, build_number):
    """Every selected platform the requested bundle can actually be built for, paired with
    its manifests and Nodos version, in the order given. A platform the bundle itself has
    no Nodos release for is left out entirely: the bundles it includes do not publish there
    either, even though they might have a release of their own on that platform."""
    package_name = get_bundle_package_name(bundle_info)
    result = []
    for platform_arch in platform_archs:
        nodos_version = find_nodos_version(bundle_info, bundles, platform_arch)
        if nodos_version is None:
            logger.info(f"{package_name} has no Nodos version for {platform_arch.key()}, skipping the platform")
            continue
        logger.info(f"Bundling {package_name} for {platform_arch.key()}")
        manifests = build_manifests(bundle_info, bundles, platform_arch, build_number)
        if len(manifests) == 0:
            logger.info(f"Nothing to publish for {platform_arch.key()}")
            continue
        result.append((platform_arch, manifests, nodos_version))
    return result

def lookup_nodos_version(to_publish, host_platform_arch):
    """The Nodos version the previous-release lookup runs on: the host platform's when
    the bundle publishes there, otherwise the first published platform's. A bundle the
    host does not target still has a Nodos line to look the previous release up on."""
    for platform_arch, _manifests, nodos_version in to_publish:
        if platform_arch.key() == host_platform_arch.key():
            return nodos_version
    return to_publish[0][2]

def write_manifest(manifest, path):
    # os.makedirs("", exist_ok=True) raises even with exist_ok=True, so a bare
    # filename with no directory part needs no makedirs call at all.
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False, default_flow_style=False)

def manifest_file_path(out_dir, package_name, platform_arch : PlatformArch):
    return os.path.join(out_dir, platform_arch.key(), package_name, "bundle.yaml")

def release_notes_file_path(out_dir, platform_arch : PlatformArch):
    return os.path.join(out_dir, f"release-notes-{platform_arch.key()}.md")

def publish_manifest(package_name, version, manifest_path, platform_arch : PlatformArch, dry_run,
                     changelog=None):
    """Publishes one manifest as a bundle release. nosman refuses a real upload until the
    store client knows the Bundle type, so only a dry run gets through today."""
    nosman_args = ["nosman", "-w", WORKSPACE_FOLDER, "publish",
                   "--type", "bundle",
                   "--path", os.path.abspath(manifest_path),
                   "--name", package_name,
                   "--version", version,
                   "--target-platform", platform_arch.key(),
                   "--no-tag", "--no-fetch-tags"]
    if changelog is not None:
        nosman_args += ["--changelog", changelog]
    if dry_run:
        nosman_args.append("--dry-run")
    logger.info(f"Publishing {package_name} {version} for {platform_arch.key()}")
    result = run(nosman_args, stdout=stdout, stderr=stderr, universal_newlines=True)
    if result.returncode != 0:
        logger.error(f"nosman publish of {package_name} {version} for "
                     f"{platform_arch.key()} returned with {result.returncode}")
        exit(result.returncode)

def publish_manifests(manifests, out_dir, platform_arch : PlatformArch, dry_run, changelog_for=None):
    """Writes and publishes each manifest in the order given, which puts a bundle after
    every bundle it includes. changelog_for's own release notes, if written for this
    platform, go along as its changelog so nosman never falls back to the bundler repo's
    git log; the bundles it includes publish with no changelog, since the notes describe
    the requested bundle, not them."""
    changelog = None
    if changelog_for is not None:
        notes_path = release_notes_file_path(out_dir, platform_arch)
        if os.path.exists(notes_path):
            with open(notes_path, "r") as f:
                changelog = f.read()
    for package_name, version, manifest in manifests:
        path = manifest_file_path(out_dir, package_name, platform_arch)
        write_manifest(manifest, path)
        entry_changelog = changelog if package_name == changelog_for else None
        publish_manifest(package_name, version, path, platform_arch, dry_run, entry_changelog)

def read_store_bundle_members(package_name, version):
    """What a published bundle holds, as name -> version. nosman info expands a bundle
    for the platform it runs on. Call this only when a previous version really exists;
    a first publish has nothing to read and skips the call entirely."""
    ensure_workspace()
    result = run(["nosman", "-w", WORKSPACE_FOLDER, "info", package_name, version],
                 capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"nosman info for {package_name} {version} returned with "
                     f"{result.returncode}: {result.stderr}")
        exit(1)
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        logger.error(f"Could not parse nosman info output for {package_name} {version}: {exc}")
        exit(1)
    return OrderedDict((member["name"], member["version"]) for member in info.get("members", []))

def previous_bundle_version(package_name, nodos_version, given_version):
    """The bundle release the notes compare against. given_version=None means look up the
    newest release on this Nodos line, and a nosman failure while doing that is an error,
    the same as read_store_bundle_members: it says nothing about whether a previous release
    exists, only that the question could not be answered. An explicit empty string is the
    only way to say there is no previous release, for a bundle's first ever publish. Read
    before anything is published, so the run's own release never answers."""
    if given_version is not None:
        return given_version
    major, minor = get_nodos_version_major_minor(nodos_version)
    result = run(["nosman", "-w", WORKSPACE_FOLDER, "info", package_name, f"{major}.{minor}"],
                 capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"nosman info for {package_name} on the {major}.{minor} line "
                     f"returned with {result.returncode}: {result.stderr}")
        exit(1)
    try:
        return json.loads(result.stdout).get("version", "")
    except json.JSONDecodeError as exc:
        logger.error(f"Could not parse nosman info output for {package_name}: {exc}")
        exit(1)

def manifest_members(manifest):
    """A manifest's members as {name, version, path} rows in install order: the engine
    at the root, then the included bundles at the root, then each packages group with
    its pattern filled in."""
    members = []
    if "nodos" in manifest:
        members.append({"name": NODOS_PACKAGE_NAME, "version": manifest["nodos"], "path": ""})
    for name, version in manifest.get("includes", {}).items():
        members.append({"name": name, "version": version, "path": ""})
    for pattern, packages in manifest.get("packages", {}).items():
        for name, version in packages.items():
            members.append({"name": name, "version": version,
                            "path": member_path(pattern, name, version)})
    return members

def expand_manifest_members(package_name, manifests):
    """Every package a bundle installs, with the members of the bundles it includes folded
    in, in the order they appear."""
    by_name = dict((name, manifest) for name, _version, manifest in manifests)
    expanded = []
    for member in manifest_members(by_name[package_name]):
        if member["name"] in by_name:
            expanded.extend(expand_manifest_members(member["name"], manifests))
        else:
            expanded.append(member)
    return expanded

def direct_manifest_includes(package_name, manifests):
    """The bundles this one includes directly, as (name, version) pairs, in the order
    they appear in its own manifest. A bundle nested two levels deep is named only
    under the bundle that includes it directly, not here."""
    by_name = dict((name, manifest) for name, _version, manifest in manifests)
    return list(by_name[package_name].get("includes", {}).items())

def format_release_notes(package_name, version, previous_version, platform_arch : PlatformArch,
                         members, previous_members, includes=()):
    engine = []
    modules = []
    samples = []
    for member in members:
        if member["name"] == NODOS_PACKAGE_NAME:
            engine.append(member)
        elif member["path"].startswith("Samples/"):
            samples.append(member)
        else:
            modules.append(member)

    previous_casefold = dict((name.casefold(), member_version)
                             for name, member_version in previous_members.items())

    def change(member):
        old_version = _lookup_old_version(previous_members, previous_casefold, member["name"])
        return _format_version_change(member["version"], old_version)

    notes = f"## {package_name} {version} ({platform_arch.key()})\n\n"
    if len(engine) > 0:
        notes += "### Engine\n"
        for member in engine:
            notes += f"- Version: {change(member)}\n"
        notes += "\n"
    notes += f"### Modules ({len(modules)})\n"
    for member in modules:
        notes += f"- {member['name']}: {change(member)}\n"
    if len(samples) > 0:
        notes += f"\n### Samples ({len(samples)})\n"
        for member in samples:
            notes += f"- {member['name']}: {change(member)}\n"
    if len(includes) > 0:
        notes += "\n### Includes\n"
        for name, include_version in includes:
            notes += f"- {name}: {include_version}\n"

    if platform_arch.key() == get_cur_platform_arch().key():
        current_names = set(member["name"] for member in members)
        removed = [name for name in previous_members if name not in current_names]
        if len(removed) > 0:
            notes += f"\n### Removed ({len(removed)})\n"
            for name in removed:
                notes += f"- {name}: {previous_members[name]}\n"
    # else: nosman info only expands a bundle for the platform it runs on, so a
    # previous release read while writing notes for another platform can't be
    # trusted to say what that platform actually had, and removals are left out
    # rather than guessed at.

    if previous_version:
        notes += f"\n### Previous Release\n- {package_name} {previous_version}\n"
    else:
        notes += "\n### Previous Release\n- First publish\n"
    return notes

def write_release_notes(text, path):
    # os.makedirs("", exist_ok=True) raises even with exist_ok=True, so a bare
    # filename with no directory part needs no makedirs call at all.
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    logger.info(f"Release notes written to {path}")
    for line in text.splitlines():
        logger.info(line)

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

def get_own_bundled_packages(bundle_info, platform_arch : PlatformArch):
    """The packages a bundle adds itself, for one platform. Packages an included bundle
    brings are not here: they travel in that bundle's own manifest."""
    packages = OrderedDict()
    for package_name, package in normalize_bundled_packages(bundle_info.get("bundled_packages", {})).items():
        if isinstance(package, str):
            packages[package_name] = {"name": package_name, "version": package, "type": None}
            continue
        if not isinstance(package, dict):
            logger.error(f"Unsupported entry for package {package_name}: {type(package)}")
            exit(1)
        version = package.get(platform_arch.key())
        if version is None:
            version = package.get("version")
        if version is None:
            logger.info(f"{package_name} has no version for {platform_arch.key()}, leaving it out")
            continue
        packages[package_name] = {"name": package_name, "version": version,
                                  "type": package.get("type")}
    return packages

if __name__ == "__main__":
    logger.remove()
    logger.add(stdout, format="<green>[Distribute Nodos]</green> <level>{time:HH:mm:ss.SSS}</level> <level>{level}</level> <level>{message}</level>")

    parser = argparse.ArgumentParser(
        description="Publish Nodos bundle manifests to the Nodos Store")
    parser.add_argument("--version",
                        help="The nodos version (1.4, 1.5, etc.)",
                        action="store",
                        required=False)
    parser.add_argument("--bundle-key",
                        help="The key of the bundle to publish",
                        action="store",
                        required=False)
    parser.add_argument("--bundle-version",
                        help="The bundle version to select when multiple entries share the same bundle name",
                        action="store",
                        required=False)
    parser.add_argument("--bundles-yaml-path",
                        help="The path to the bundles YAML file",
                        action="store",
                        required=False)
    parser.add_argument("--platforms",
                        help="Comma separated target platforms to publish for, "
                             "for example x86_64-windows,x86_64-linux,aarch64-macos. "
                             "Defaults to the platform this runs on.",
                        action="store",
                        default="")
    parser.add_argument("--out-dir",
                        help="Where the manifests and release notes are written",
                        action="store",
                        default=ARTIFACTS_FOLDER)
    parser.add_argument("--previous-version",
                        help="The bundle release the notes compare against, as a published "
                             "version like 1.5.0.b4711. If not given, the newest release on "
                             "the same Nodos line is used, and nosman failing to find one is "
                             "an error. Pass an empty string to say this is the first publish.",
                        action="store",
                        default=None)
    parser.add_argument("--dry-run",
                        action="store_true",
                        default=False,
                        help="Ask nosman what it would publish instead of publishing")

    args = parser.parse_args()

    # Fail on a host nosman has no release for before reading or publishing anything.
    host_platform_arch = get_cur_platform_arch()

    if args.bundles_yaml_path:
        bundles_data = load_bundles_data(args.bundles_yaml_path)
    elif args.version:
        yaml_path = f"nodos-{args.version}.yaml"
        if not os.path.exists(yaml_path):
            logger.error(f"Bundle file {yaml_path} not found")
            exit(1)
        bundles_data = load_bundles_data(yaml_path)
    else:
        logger.error("Either --version or --bundles-yaml-path must be specified")
        exit(1)

    bundles = bundles_data.get("bundles")
    if bundles is None:
        logger.error("Failed to read bundles. Missing 'bundles' key")
        exit(1)
    if not args.bundle_key:
        logger.error("--bundle-key is required")
        exit(1)
    bundle_info = get_bundle_info(args.bundle_key, bundles, args.bundle_version)
    if bundle_info is None:
        logger.error(f"Failed to read bundle info for key {args.bundle_key}")
        exit(1)

    platform_archs = parse_platform_keys(args.platforms)

    build_number = get_build_number()
    package_name = get_bundle_package_name(bundle_info)
    force_delete_folder(args.out_dir)
    os.makedirs(args.out_dir, exist_ok=True)
    ensure_workspace()

    # Resolve and build every selected platform's manifests first, before anything is
    # published: a later platform's release notes must never compare against the
    # release this run just published for an earlier one.
    to_publish = platforms_to_publish(bundle_info, bundles, platform_archs, build_number)
    if len(to_publish) == 0:
        requested = ", ".join(platform_arch.key() for platform_arch in platform_archs)
        logger.error(f"Nothing was published for {package_name}: no release on any of {requested}")
        exit(1)

    # nosman info only ever answers for the platform it runs on, so the previous release
    # and its members are looked up once for the whole run, not once per target platform.
    host_nodos_version = lookup_nodos_version(to_publish, host_platform_arch)
    previous_version = previous_bundle_version(package_name, host_nodos_version, args.previous_version)
    previous_members = read_store_bundle_members(package_name, previous_version) if previous_version else OrderedDict()

    for platform_arch, manifests, _nodos_version in to_publish:
        version = next(v for name, v, _m in manifests if name == package_name)
        notes = format_release_notes(
            package_name, version, previous_version, platform_arch,
            expand_manifest_members(package_name, manifests),
            previous_members,
            direct_manifest_includes(package_name, manifests))
        write_release_notes(notes, release_notes_file_path(args.out_dir, platform_arch))

    for platform_arch, manifests, _nodos_version in to_publish:
        publish_manifests(manifests, args.out_dir, platform_arch, args.dry_run,
                          changelog_for=package_name)
