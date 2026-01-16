import argparse
from subprocess import CompletedProcess, call, run, CalledProcessError
from sys import stderr, stdout
from loguru import logger
import os
import shutil
import json
import glob
import platform
from collections import OrderedDict
import yaml


WORKSPACE_FOLDER = "./workspace"
ARTIFACTS_FOLDER = "./Artifacts/"

COMPRESSED_FILE_EXTENSION = ".zip"

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

def get_current_target_platform():
	# x86_64-windows, x86_64-linux, arm64-linux etc.
	arch, os = platform.machine().lower(), platform.system().lower()
	if arch == "amd64":
		arch = "x86_64"
	return f"{arch}-{os}"

def get_versions_platform_key():
	arch, os = platform.machine().lower(), platform.system().lower()
	if arch in ("amd64", "x86_64"):
		arch = "x64"
	elif arch in ("aarch64", "arm64"):
		arch = "arm64"
	return f"{arch}-{os}"

def get_package_version(package):
	if "versions" in package:
		versions = package["versions"]
		platform_key = get_versions_platform_key()
		if platform_key in versions:
			return versions[platform_key]
		arch, os = platform.machine().lower(), platform.system().lower()
		if arch == "amd64":
			arch = "x86_64"
		fallback_keys = [
			f"{arch}-{os}",
		]
		if arch == "x86_64":
			fallback_keys.append(f"x64-{os}")
		if arch in ("aarch64", "arm64"):
			fallback_keys.append(f"arm64-{os}")
		for key in fallback_keys:
			if key in versions:
				return versions[key]
		logger.error(f"Missing version for platform {platform_key} in package {package.get('name')}")
		exit(1)
	if "version" in package:
		return package["version"]
	logger.error(f"Missing version/versions for package {package.get('name')}")
	exit(1)

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
	if bundles.get(bundle_key) is None:
		logger.error(f"Bundle key {bundle_key} not found in bundles file")
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
			other_conf = bundles.get(current)
			if other_conf is None:
				logger.error(f"Depending bundle key {current} not found in bundles file")
				exit(1)
			value = other_conf.get(key)
			if value is not None:
				return value
			queue.extend(other_conf["includes"] if "includes" in other_conf else [])
	return value

def get_nodos_github_url(bundle_info, bundles):
	return get_inheritable_value(bundle_info, "nodos_github_url", bundles)


def get_nodos_version(bundle_info, bundles):
	return get_inheritable_value(bundle_info, "nodos_version", bundles)

def get_semver_from_version(version):
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

def get_compressed_file_extension():
	if platform.system() == "Linux":
		return ".tar.gz"
	return ".zip"

def get_release_artifacts(dir):
	files = glob.glob(f"{dir}/*{get_compressed_file_extension()}")
	return files

def read_bundles_file(path, file_contents=None):
	try:
		if file_contents is None:
			with open(path, "r") as f:
				file_contents = f.read()
		if path.lower().endswith((".yaml", ".yml")):
			bundles_doc = yaml.safe_load(file_contents)
		else:
			bundles_doc = json.loads(file_contents)
	except Exception as e:
		logger.error(f"Failed to parse {path}. Error: {e}")
		return None
	if bundles_doc is None or bundles_doc.get("bundles") is None:
		logger.error(f"Failed to read {path}. Missing 'bundles' key")
		return None
	return bundles_doc["bundles"]

def get_bundles_paths(bundles_path):
	if bundles_path is None:
		return []
	if os.path.isdir(bundles_path):
		return sorted(glob.glob(os.path.join(bundles_path, "bundles*.yml")) + glob.glob(os.path.join(bundles_path, "bundles*.yaml")))
	if "*" in bundles_path or "?" in bundles_path:
		return sorted(glob.glob(bundles_path))
	if os.path.isfile(bundles_path):
		base = os.path.basename(bundles_path)
		if base.startswith("bundles") and bundles_path.lower().endswith((".yaml", ".yml")):
			parent = os.path.dirname(bundles_path) or "."
			return sorted(glob.glob(os.path.join(parent, "bundles*.yml")) + glob.glob(os.path.join(parent, "bundles*.yaml")))
		return [bundles_path]
	return []

def load_bundles_from_paths(paths):
	bundles = OrderedDict()
	for path in paths:
		bundles_in_file = read_bundles_file(path)
		if bundles_in_file is None:
			return None
		for key, value in bundles_in_file.items():
			if key in bundles:
				logger.error(f"Duplicate bundle key {key} found in {path}")
				return None
			bundles[key] = value
	return bundles

def is_full_version(version):
	parts = version.split(".")
	if len(parts) < 3:
		return False
	for i, part in enumerate(parts):
		if i == 3:
			if part.startswith("b"):
				return part[1:].isdigit()
			return part.isdigit()
		if not part.isdigit():
			return False
	return True

def parse_semver(version):
	parts = version.split(".")
	try:
		major = int(parts[0])
	except (IndexError, ValueError):
		return None
	minor = None
	patch = None
	build = None
	if len(parts) > 1:
		try:
			minor = int(parts[1])
		except ValueError:
			return None
	if len(parts) > 2:
		try:
			patch = int(parts[2])
		except ValueError:
			return None
	if len(parts) > 3:
		part = parts[3]
		if part.startswith("b"):
			part = part[1:]
		try:
			build = int(part)
		except ValueError:
			return None
	return (major, minor, patch, build)

def matches_prefix(version, prefix):
	version_parts = parse_semver(version)
	prefix_parts = parse_semver(prefix)
	if version_parts is None or prefix_parts is None:
		return False
	v_major, v_minor, v_patch, v_build = version_parts
	p_major, p_minor, p_patch, p_build = prefix_parts
	if v_major != p_major:
		return False
	if p_minor is None:
		return True
	if v_minor != p_minor:
		return False
	if p_patch is None:
		return True
	if v_patch != p_patch:
		return False
	if p_build is None:
		return True
	return v_build == p_build

def version_sort_key(version):
	parts = parse_semver(version)
	if parts is None:
		return (-1, -1, -1, -1)
	major, minor, patch, build = parts
	return (major, minor or -1, patch or -1, build or -1)

def resolve_nodos_version_from_workspace(version_prefix):
	if is_full_version(version_prefix):
		return version_prefix
	engine_dir = os.path.join(WORKSPACE_FOLDER, "Engine")
	if not os.path.isdir(engine_dir):
		return None
	candidates = []
	for entry in os.listdir(engine_dir):
		full_path = os.path.join(engine_dir, entry)
		if not os.path.isdir(full_path):
			continue
		if matches_prefix(entry, version_prefix):
			candidates.append(entry)
	if not candidates:
		return None
	return sorted(candidates, key=version_sort_key, reverse=True)[0]

def ensure_full_nodos_version(nodos_version, action_name):
	resolved = resolve_nodos_version_from_workspace(nodos_version)
	if resolved is None:
		logger.error(f"Failed to resolve Nodos version for {action_name}. Run with --download-nodos first.")
		exit(1)
	if not is_full_version(resolved):
		logger.error(f"Resolved Nodos version {resolved} is not a full version for {action_name}.")
		exit(1)
	return resolved

def get_installed_package_version(package_name, version_prefix):
	args = ["./nodos", "-w", WORKSPACE_FOLDER, "info", package_name, version_prefix, "--relaxed"]
	result = run(args, capture_output=True, text=True, env=os.environ.copy())
	if result.returncode != 0:
		logger.error(f"nosman info returned with {result.returncode}: {result.stderr}")
		exit(result.returncode)
	try:
		info = json.loads(result.stdout)
	except json.JSONDecodeError as e:
		logger.error(f"Failed to parse nosman info output for {package_name}: {e}")
		exit(1)
	return info["info"]["id"]["version"]

def resolve_package_versions(packages_map):
	resolved = OrderedDict()
	for package in packages_map.values():
		package_name = package["name"]
		version = package["version"]
		if not is_full_version(version):
			version = get_installed_package_version(package_name, version)
		resolved_package = dict(package)
		resolved_package["version"] = version
		resolved[package_name] = resolved_package
	return resolved

def download_nodos(bundle_info, nodos_version):
	force_delete_folder(WORKSPACE_FOLDER)
	logger.info("Reading Nodos version from bundle")

	logger.info(f"Downloading Nodos version {nodos_version} using nosman")
	# Download Nodos
	result = run(["./nodos", "-w", WORKSPACE_FOLDER, "get", "--version", nodos_version, "-y"], stdout=stdout, stderr=stderr, universal_newlines=True)
	if result.returncode != 0:
		logger.error(f"nosman get returned with {result.returncode}")
		exit(result.returncode)
	resolved = resolve_nodos_version_from_workspace(nodos_version)
	if resolved is None:
		logger.error(f"Failed to resolve installed Nodos version for prefix {nodos_version}")
		exit(1)
	return resolved

def get_bundled_packages(bundle_info, bundles):
	bundled_packages = list(bundle_info["bundled_packages"] if "bundled_packages" in bundle_info else [])
	if "includes" in bundle_info:
		queue = list(bundle_info["includes"])
		includes = list([])
		while len(queue) > 0:
			current = queue.pop(0)
			includes.extend([current])
			other_conf = bundles.get(current)
			if other_conf is None:
				logger.error(f"Depending bundle key {current} not found in bundles file")
				exit(1)
			queue.extend(other_conf["includes"] if "includes" in other_conf else [])
		logger.info(f"Adding modules from: {' '.join(includes)}")
		for include in includes:
			conf = bundles.get(include)
			if conf is None:
				logger.error(f"Include bundle key {include} not found in bundles file")
				exit(1)
			others = list(conf["bundled_packages"] if "bundled_packages" in conf else [])
			bundled_packages = others + bundled_packages

	packages_map = OrderedDict()
	for package in bundled_packages:
		resolved_package = dict(package)
		resolved_package["version"] = get_package_version(package)
		packages_map[resolved_package["name"]] = resolved_package
	return packages_map

def download_packages(bundle_info, bundles, nodos_version):
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
	
	resolved_nodos_version = resolve_nodos_version_from_workspace(nodos_version)
	if resolved_nodos_version is None:
		logger.error(f"Failed to resolve installed Nodos version for prefix {nodos_version}. Run with --download-nodos first.")
		exit(1)

	packages_map = get_bundled_packages(bundle_info, bundles)

	downloading_packages_str = ""
	for package in packages_map.keys():
		downloading_packages_str += f"{package} "
	logger.info(f"Downloading packages: {downloading_packages_str}")
	
	included_packages = []
	for package in packages_map.values():
		package_name = package["name"]
		requested_version = package["version"]
		logger.info(f"Downloading package {package_name} version {requested_version} using nosman")
		out_dir = f"./Module/{package_name}"
		if "type" in package and package["type"] == "sample":
			out_dir = f"./Samples/{package_name}"
		result = run(["./nodos", "-w", WORKSPACE_FOLDER, "install", package_name, requested_version, "--out-dir", out_dir, "--prefix", requested_version, "--without-deps"], stdout=stdout, stderr=stderr, universal_newlines=True)
		if result.returncode != 0:
			logger.error(f"nosman install returned with {result.returncode}")
			exit(result.returncode)
		resolved_version = requested_version
		if not is_full_version(requested_version):
			resolved_version = get_installed_package_version(package_name, requested_version)
		incl = {"name": package_name, "version": resolved_version}
		if "type" in package:
			incl["type"] = "sample"
		included_packages.append(incl)
	# Write included modules to Profile.json
	profile_json_path = f"{WORKSPACE_FOLDER}/Engine/{resolved_nodos_version}/Config/Profile.json"
	profile = {}
	loaded_plugins_key = "loaded_plugins"
	major, minor, patch = get_semver_from_version(resolved_nodos_version)
	# If version lower than 1.4.0 use loaded_modules key
	if int(major) < 1 or (int(major) == 1 and int(minor) < 4):
		loaded_plugins_key = "loaded_modules"
	if loaded_plugins_key not in profile:
		profile[loaded_plugins_key] = []
	included_plugins = []
	for package in included_packages:
		if "type" not in package or package["type"] != "sample":
			included_plugins.append(package)
	profile[loaded_plugins_key].extend(included_plugins)
	with open(f"{profile_json_path}", "w") as f:
		json.dump(profile, f, indent=2)

def package(bundle_key, bundle_info, nodos_version):
	logger.info("Packaging Nodos")
	force_delete_folder(ARTIFACTS_FOLDER)
	force_delete_folder(f"{WORKSPACE_FOLDER}/.nosman")
	run([f"{WORKSPACE_FOLDER}/nodos", "-w", WORKSPACE_FOLDER, "init"], stdout=stdout, stderr=stderr, universal_newlines=True)
	force_delete_folder(f"{WORKSPACE_FOLDER}/.nosman/remote")
	engine_folder = f"{WORKSPACE_FOLDER}/Engine/{nodos_version}"
	engine_settings_path = f"{engine_folder}/Config/Defaults/EngineSettings.json"
	if not os.path.exists(engine_settings_path):
		engine_settings_path = f"{engine_folder}/Config/EngineSettings.json"
		if not os.path.exists(engine_settings_path):
			logger.error(f"Engine settings file not found in both {engine_folder}/Config and {engine_folder}/Config/Defaults")
			exit(1)
	with open(engine_settings_path, "r") as f:
		engine_settings = json.load(f)
		engine_settings["remote_modules"] = bundle_info["module_index_urls"]
		engine_settings["engine_index_url"] = bundle_info["engine_index_url"]

	with open(engine_settings_path, "w") as f:
		json.dump(engine_settings, f, indent=2)

	major, minor, patch = get_semver_from_version(nodos_version)
	# Zip everything under workspace_folder
	archive_format = "zip"
	if platform.system() == "Linux":
		archive_format = "gztar"
	shutil.make_archive(f"{ARTIFACTS_FOLDER}/Nodos-{major}.{minor}.{patch}.b{get_build_number()}-bundle-{bundle_key}-{get_current_target_platform()}", archive_format, f"{WORKSPACE_FOLDER}")

def is_bundles_filename(path):
	base = os.path.basename(path).lower()
	return base.startswith("bundles") and base.endswith((".yaml", ".yml", ".json"))

def get_previous_bundles(previous_commit):
	result = run(["git", "ls-tree", "-r", "--name-only", previous_commit], capture_output=True, text=True)
	if result.returncode != 0:
		logger.error(f"Failed to list files for commit {previous_commit}")
		return None
	paths = [line.strip() for line in result.stdout.splitlines() if is_bundles_filename(line.strip())]
	if not paths:
		logger.error(f"Failed to retrieve bundles file from commit {previous_commit}.")
		return None
	bundles = OrderedDict()
	for path in paths:
		show = run(["git", "show", f"{previous_commit}:{path}"], capture_output=True, text=True)
		if show.returncode != 0:
			logger.error(f"Failed to read {path} from commit {previous_commit}")
			return None
		previous_bundles = read_bundles_file(path, show.stdout)
		if previous_bundles is None:
			return None
		for key, value in previous_bundles.items():
			if key in bundles:
				logger.error(f"Duplicate bundle key {key} found in {path} from commit {previous_commit}")
				return None
			bundles[key] = value
	return bundles

def fill_github_url_static_info(url):
	arch, os = platform.machine().lower(), platform.system().lower()
	if arch == "amd64":
		arch = "x86_64"
	return url.replace("%%arch%%", arch).replace("%%os%%", os)

def create_nodos_release(gh_release_repo, gh_release_target_branch, dry_run_release, skip_nosman_publish, bundle_info, nodos_version, bundle_key):
	short_name = bundle_info.get("short_name")
	if short_name is None:
		logger.info("Missing short name in bundle info, choosing short name as bundle key")
		short_name = bundle_key
	release_repo, target_branch = gh_release_repo, gh_release_target_branch
	artifacts = get_release_artifacts(ARTIFACTS_FOLDER)
	if len(artifacts) == 0:
		logger.error("No artifacts found to release")
		exit(1)
	for path in artifacts:
		logger.info(f"Release artifact: {path}")
	major, minor, patch = get_semver_from_version(nodos_version)
	build_number = get_build_number()
	tag = f"v{major}.{minor}.{patch}.b{build_number}-{short_name}-{get_current_target_platform()}"
	title = f"{tag}"

	packages = resolve_package_versions(get_bundled_packages(bundle_info, bundles))

	# Retrieve the previous bundle info
	previous_commit = getenv("PREVIOUS_COMMIT", False)
	previous_bundles = None
	if previous_commit is not None:
		previous_bundles = get_previous_bundles(previous_commit)
	previous_packages = None
	previous_nodos_version = None
	if previous_bundles is None:
		logger.error(f"Failed to read bundles file from commit {previous_commit}")
	else:
		if previous_bundles.get(bundle_key) is None:
			logger.error(f"Bundle key {bundle_key} not found in bundles file from commit {previous_commit}")
		else:
			previous_bundle_info = previous_bundles.get(bundle_key)
			if previous_bundle_info is None:
				logger.error(f"Failed to read bundle info for key {bundle_key} from commit {previous_commit}")
			else:
				previous_packages = get_bundled_packages(previous_bundle_info, previous_bundles)
				previous_nodos_version = get_nodos_version(previous_bundle_info, previous_bundles)

	release_notes = f"## Nodos {nodos_version}\n\n"
	release_notes += f"### Engine\n"
	if previous_nodos_version is not None and previous_nodos_version != nodos_version:
		release_notes += f"* Engine version: {nodos_version} (prev: {previous_nodos_version})\n"
	else:
		release_notes += f"* Engine version: {nodos_version}\n"

	release_notes += f"### Modules\n"


	for package in packages.values():
		old_version = None
		if previous_packages is not None:
			old_version = previous_packages.get(package['name'], {}).get('version')
		if old_version and old_version != package['version']:
			release_notes += f"* {package['name']} - {package['version']} (prev: {old_version})\n"
		elif old_version:
			release_notes += f"* {package['name']} - {package['version']} (no change)\n"
		else:
			release_notes += f"* {package['name']} - {package['version']} (new)\n"


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
			dist_key = file_name.split("-bundle-")[1].split(get_compressed_file_extension())[0]
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
	parser.add_argument("--bundle-key",
					 	help="The key of the bundle to package",
						action="store",
						required=True)
	bundles_path_group = parser.add_mutually_exclusive_group(required=True)
	bundles_path_group.add_argument("--bundles-path",
					 	help="The path to the bundles YAML/JSON file",
						action="store")
	bundles_path_group.add_argument("--bundles-json-path",
					 	help="(Deprecated) The path to the bundles.json file",
						action="store")
	bundles_path_group.add_argument("--bundles-json",
					 	help="(Deprecated) The path to the bundles.json file",
						action="store")

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

	bundles = None
	bundle_info = None

	bundles_path = args.bundles_path or args.bundles_json_path or args.bundles_json
	bundles_paths = get_bundles_paths(bundles_path)
	if not bundles_paths:
		logger.error(f"Failed to find bundles files from {bundles_path}")
		exit(1)
	bundles = load_bundles_from_paths(bundles_paths)
	if bundles is None:
		logger.error("Failed to read bundles file(s)")
		exit(1)
	bundle_info = get_bundle_info(args.bundle_key, bundles)

	nodos_version = get_nodos_version(bundle_info, bundles)

	if bundles is None:
		logger.error("Failed to read bundles file. Missing 'bundles' key")
		exit(1)

	if bundle_info is None:
		logger.error(f"Failed to read bundle info for key {args.bundle_key}")
		exit(1)

	if args.download_nodos:
		nodos_version = download_nodos(bundle_info, nodos_version)

	if args.download_packages:
		nodos_version = ensure_full_nodos_version(nodos_version, "package download")
		download_packages(bundle_info, bundles, nodos_version)

	if args.pack:
		nodos_version = ensure_full_nodos_version(nodos_version, "packaging")
		package(args.bundle_key, bundle_info, nodos_version)

	if args.gh_release:
		nodos_version = ensure_full_nodos_version(nodos_version, "release notes")
		create_nodos_release(args.gh_release_repo, args.gh_release_target_branch, args.dry_run_release, args.skip_nosman_publish, bundle_info, nodos_version, args.bundle_key)
