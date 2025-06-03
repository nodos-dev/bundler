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
		logger.error(f"Bundle key {bundle_key} not found in bundle.json")
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
				logger.error(f"Depending bundle key {current} not found in bundles.json")
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

def download_nodos(bundle_info, nodos_version):
	force_delete_folder(WORKSPACE_FOLDER)
	logger.info("Reading Nodos version from bundle")

	logger.info(f"Downloading Nodos version {nodos_version} using nosman")
	# Download Nodos
	result = run(["./nodos", "-w", WORKSPACE_FOLDER, "get", "--version", nodos_version, "-y"], stdout=stdout, stderr=stderr, universal_newlines=True)
	if result.returncode != 0:
		logger.error(f"nosman get returned with {result.returncode}")
		exit(result.returncode)

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
				logger.error(f"Depending bundle key {current} not found in bundles.json")
				exit(1)
			queue.extend(other_conf["includes"] if "includes" in other_conf else [])
		logger.info(f"Adding modules from: {' '.join(includes)}")
		for include in includes:
			conf = bundles.get(include)
			if conf is None:
				logger.error(f"Include bundle key {include} not found in bundles.json")
				exit(1)
			others = list(conf["bundled_packages"] if "bundled_packages" in conf else [])
			bundled_packages = others + bundled_packages

	packages_map = OrderedDict()
	for package in bundled_packages:
		packages_map[package["name"]] = package
	return packages_map

def download_modules(bundle_info, bundles, nodos_version):
	logger.info("Deleting old modules")
	force_delete_folder(f"{WORKSPACE_FOLDER}/Module/")
	os.makedirs(f"{WORKSPACE_FOLDER}/Module/", exist_ok=True)
	logger.info("Collecting module information from bundle")
	result = run(["./nodos", "-w", WORKSPACE_FOLDER, "rescan"], stdout=stdout, stderr=stderr, universal_newlines=True)
	if result.returncode != 0:
		logger.error(f"nosman rescan returned with {result.returncode}")
		exit(result.returncode)
	
	packages_map = get_bundled_packages(bundle_info, bundles)

	downloading_packages_str = ""
	for package in packages_map.keys():
		downloading_packages_str += f"{package} "
	logger.info(f"Downloading packages: {downloading_packages_str}")
	
	included_packages = []
	for package in packages_map.values():
		package_name = package["name"]
		package_version = package["version"]
		logger.info(f"Downloading package {package_name} version {package_version} using nosman")
		out_dir = f"Module/{package_name}"
		if "type" in package and package["type"] == "sample":
			out_dir = f"Samples/{package_name}"
		result = run(["./nodos", "-w", WORKSPACE_FOLDER, "install", package_name, package_version, "--out-dir", out_dir, "--prefix", package_version, "--without-deps"], stdout=stdout, stderr=stderr, universal_newlines=True)
		if result.returncode != 0:
			logger.error(f"nosman install returned with {result.returncode}")
			exit(result.returncode)
		included_packages.append({"name": package_name, "version": package_version})
	# Write included modules to Profile.json
	profile_json_path = f"{WORKSPACE_FOLDER}/Engine/{nodos_version}/Config/Profile.json"
	profile = {}
	loaded_plugins_key = "loaded_plugins"
	major, minor, patch = get_semver_from_version(nodos_version)
	# If version lower than 1.4.0 use loaded_modules key
	if int(major) < 1 or (int(major) == 1 and int(minor) < 4):
		loaded_plugins_key = "loaded_modules"
	if loaded_plugins_key not in profile:
		profile[loaded_plugins_key] = []
	included_plugins = [package for package in included_packages if ("type" not in package or package["type"] != "sample")]
	profile[loaded_plugins_key].extend(included_plugins)
	with open(f"{profile_json_path}", "w") as f:
		json.dump(profile, f, indent=2)

def package(bundle_key, bundle_info, nodos_version):
	logger.info("Packaging Nodos")
	force_delete_folder(ARTIFACTS_FOLDER)
	force_delete_folder(f"{WORKSPACE_FOLDER}/.nosman")
	run([f"{WORKSPACE_FOLDER}/nodos", "-w", WORKSPACE_FOLDER, "init"], stdout=stdout, stderr=stderr, universal_newlines=True)
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

def get_previous_bundles(previous_commit):
	# Retrieve the previous bundles.json file from the specified commit
	result = run(["git", "show", f"{previous_commit}:bundles.json"], capture_output=True, text=True)
	if result.returncode != 0:
		logger.error(f"Failed to retrieve bundles.json from commit {previous_commit}. Error: {result.stderr}")
		return None
	previous_bundles_json = json.loads(result.stdout)
	if previous_bundles_json.get("bundles") is None:
		logger.error(f"Failed to read bundles.json from commit {previous_commit}. Missing 'bundles' key")
		return None
	return previous_bundles_json["bundles"]

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

	packages = get_bundled_packages(bundle_info, bundles)

	# Retrieve the previous bundle info
	previous_commit = getenv("PREVIOUS_COMMIT", False)
	previous_bundles = None
	if previous_commit is not None:
		previous_bundles = get_previous_bundles(previous_commit)
	previous_packages = None
	previous_nodos_version = None
	if previous_bundles is None:
		logger.error(f"Failed to read bundles.json from commit {previous_commit}")
	else:
		if previous_bundles.get(bundle_key) is None:
			logger.error(f"Bundle key {bundle_key} not found in bundles.json from commit {previous_commit}")
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
		nodos_github_url = get_nodos_github_url(bundle_info, bundles)
		if nodos_github_url is not None:
			comparison_url = fill_github_url_static_info(nodos_github_url).replace("%%old_version%%", previous_nodos_version).replace("%%new_version%%", nodos_version)
			release_notes += f"* Engine version: {nodos_version} (prev: {previous_nodos_version}, [Compare]({comparison_url}))\n"
		else:			
			release_notes += f"* Engine version: {nodos_version} (prev: {previous_nodos_version})\n"
	else:
		release_notes += f"* Engine version: {nodos_version}\n"


	nodos_github_url = get_nodos_github_url(bundle_info, bundles)

	release_notes += f"### Modules\n"


	for package in packages.values():
		old_version = None
		if previous_packages is not None:
			old_version = previous_packages.get(package['name'], {}).get('version')
		if old_version and old_version != package['version']:
			if 'github_url' in package:
				old_build = old_version.split(".b")[-1]
				new_build = package['version'].split(".b")[-1]
				comparison_url = fill_github_url_static_info(package['github_url']).replace("%%old_build%%", old_build).replace("%%new_build%%", new_build)
				release_notes += f"* {package['name']} - {package['version']} (prev: {old_version}, [Compare]({comparison_url}))\n"
			else:
				release_notes += f"* {package['name']} - {package['version']} (prev: {old_version})\n"
		elif old_version:
			release_notes += f"* {package['name']} - {package['version']} (no change)\n"
		else:
			release_notes += f"* {package['name']} - {package['version']} (new)\n"

	if previous_commit is not None:
		#check if this is a tag
		if previous_commit.startswith("v"):
			release_notes += f"\n\n Previous release: {gh_release_repo}/releases/tag/{previous_commit}\n"
		else:
			#try to find the tag of the previous commit
			result = run(["git", "describe", "--tags", "--abbrev=0", previous_commit], capture_output=True, text=True)
			if result.returncode == 0:
				previous_tag = result.stdout.strip()
				release_notes += f"\n\n Previous release: {gh_release_repo}/releases/tag/{previous_tag}\n"


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
	parser.add_argument("--bundles-json-path",
					 	help="The path to the bundles.json file",
						action="store",
						required=True)

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

	parser.add_argument('--download-modules',
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

	with open(args.bundles_json_path, 'r') as f:
		bundles_json = json.load(f)
		if bundles_json is None:
			logger.error("Failed to read bundles.json")
			exit(1)
		if bundles_json.get("bundles") is None:
			logger.error("Failed to read bundles.json. Missing 'bundles' key")
			exit(1)
		bundles = bundles_json.get("bundles")
		bundle_info = get_bundle_info(args.bundle_key, bundles)

	nodos_version = get_nodos_version(bundle_info, bundles)

	if bundles is None:
		logger.error("Failed to read bundles.json. Missing 'bundles' key")
		exit(1)

	if bundle_info is None:
		logger.error(f"Failed to read bundle info for key {args.bundle_key}")
		exit(1)

	if args.download_nodos:
		download_nodos(bundle_info, nodos_version)

	if args.download_modules:
		download_modules(bundle_info, bundles, nodos_version)

	if args.pack:
		package(args.bundle_key, bundle_info, nodos_version)

	if args.gh_release:
		create_nodos_release(args.gh_release_repo, args.gh_release_target_branch, args.dry_run_release, args.skip_nosman_publish, bundle_info, nodos_version, args.bundle_key)
