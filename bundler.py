import argparse
import io
from subprocess import CompletedProcess, call, run
import subprocess
from sys import stderr, stdout
import zipfile
from loguru import logger
import os
import shutil
import json
import pathlib
import glob
import platform
import requests


WORKSPACE_FOLDER = "./workspace"
ARTIFACTS_FOLDER = "./Artifacts/"

def getenv(var_name):
	val = os.getenv(var_name)
	if val is None:
		logger.error(f"Environment variable {var_name} is not set!")
		exit(1)
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

def get_nodos_version(bundle_info, bundles):
	nodos_version = bundle_info.get("nodos_version")
	if nodos_version is not None:
		return nodos_version
# Try to get nodos_version from the bundle's includes
	if "includes" in bundle_info:
		queue = list(bundle_info["includes"])
		while len(queue) > 0:
			current = queue.pop(0)
			other_conf = bundles.get(current)
			if other_conf is None:
				logger.error(f"Depending bundle key {current} not found in bundles.json")
				exit(1)
			nodos_version = other_conf.get("nodos_version")
			if nodos_version is not None:
				return nodos_version
			queue.extend(other_conf["includes"] if "includes" in other_conf else [])
	return nodos_version

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

def get_release_artifacts(dir):
	files = glob.glob(f"{dir}/*.zip")
	return files

def download_nodos(bundle_info, nodos_version):
	shutil.rmtree(WORKSPACE_FOLDER, ignore_errors=True)
	logger.info("Reading Nodos version from bundle")

	logger.info(f"Downloading Nodos version {nodos_version} using nosman")
	# Download Nodos
	result = run(["nodos", "-w", WORKSPACE_FOLDER, "get", "--version", nodos_version, "-y"], stdout=stdout, stderr=stderr, universal_newlines=True)
	if result.returncode != 0:
		logger.error(f"nosman get returned with {result.returncode}")
		exit(result.returncode)

def get_bundled_modules(bundle_info, bundles):
	bundled_modules = list(bundle_info["bundled_modules"] if "bundled_modules" in bundle_info else [])
	if "includes" in bundle_info:
		queue = list(bundle_info["includes"])
		includes = set([])
		while len(queue) > 0:
			current = queue.pop(0)
			includes.update([current])
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
			others = list(conf["bundled_modules"] if "bundled_modules" in conf else [])
			bundled_modules.extend(others)

	modules_map = {}
	for module in bundled_modules:
		modules_map[module["name"]] = module
	return modules_map

def download_modules(bundle_info, bundles, nodos_version):
	logger.info("Deleting old modules")
	shutil.rmtree(f"{WORKSPACE_FOLDER}/Module/", ignore_errors=True)
	os.makedirs(f"{WORKSPACE_FOLDER}/Module/", exist_ok=True)
	logger.info("Collecting module information from bundle")
	
	modules_map = get_bundled_modules(bundle_info, bundles)

	downloading_modules_str = ""
	for module in modules_map.keys():
		downloading_modules_str += f"{module} "
	logger.info(f"Downloading modules: {downloading_modules_str}")
	
	included_modules = []
	for module in modules_map.values():
		module_name = module["name"]
		module_version = module["version"]
		logger.info(f"Downloading module {module_name} version {module_version} using nosman")
		result = run(["nodos", "-w", WORKSPACE_FOLDER, "install", module_name, module_version, "--out-dir", f"./Module/{module_name}", "--prefix", module_version], stdout=stdout, stderr=stderr, universal_newlines=True)
		if result.returncode != 0:
			logger.error(f"nosman install returned with {result.returncode}")
			exit(result.returncode)
		included_modules.append({"name": module_name, "version": module_version})

	# Write included modules to Profile.json
	profile_json_path = f"{WORKSPACE_FOLDER}/Engine/{nodos_version}/Config/Profile.json"
	profile = {}
	if "loaded_modules" not in profile:
		profile["loaded_modules"] = []
	profile["loaded_modules"].extend(included_modules)
	with open(f"{profile_json_path}", "w") as f:
		json.dump(profile, f, indent=2)

def package(bundle_key, bundle_info, nodos_version):
	logger.info("Packaging Nodos")
	shutil.rmtree(ARTIFACTS_FOLDER, ignore_errors=True)
	shutil.rmtree(f"{WORKSPACE_FOLDER}/.nosman", ignore_errors=True)
	run([f"{WORKSPACE_FOLDER}/nodos", "-w", WORKSPACE_FOLDER, "init"], stdout=stdout, stderr=stderr, universal_newlines=True)
	engine_folder = f"{WORKSPACE_FOLDER}/Engine/{nodos_version}"
	engine_settigns_path = f"{engine_folder}/Config/EngineSettings.json"
	with open(engine_settigns_path, "r") as f:
		engine_settings = json.load(f)
		engine_settings["remote_modules"] = bundle_info["module_index_urls"]
		engine_settings["engine_index_url"] = bundle_info["engine_index_url"]

	with open(engine_settigns_path, "w") as f:
		json.dump(engine_settings, f, indent=2)

	major, minor, patch = get_semver_from_version(nodos_version)
	# Zip everything under workspace_folder
	shutil.make_archive(f"{ARTIFACTS_FOLDER}/Nodos-{major}.{minor}.{patch}.b{get_build_number()}-bundle-{bundle_key}", 'zip', f"{WORKSPACE_FOLDER}")

def create_nodos_release(gh_release_repo, gh_release_target_branch, dry_run_release, skip_nosman_publish, bundle_info, nodos_version, bundle_key):
	short_name = bundle_info.get("short_name")
	if short_name is None:
		logger.info("Missing short name in bundle info, choosing short name as bundle key")
		short_name = bundle_key
	release_repo, target_branch = gh_release_repo, gh_release_target_branch
	artifacts = get_release_artifacts(ARTIFACTS_FOLDER)
	for path in artifacts:
		logger.info(f"Release artifact: {path}")
	major, minor, patch = get_semver_from_version(nodos_version)
	build_number = get_build_number()
	tag = f"v{major}.{minor}.{patch}.b{build_number}-{short_name}"
	title = f"{tag}"

	modules = get_bundled_modules(bundle_info, bundles)
	release_notes = f"## Nodos {nodos_version}\n\n"
	release_notes += f"### Modules\n"
	for module in modules.values():
		release_notes += f"* {module['name']} - {module['version']}\n"

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
		print(result.stderr)
		logger.error(f"GitHub CLI returned with {result.returncode}")
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
			dist_key = file_name.split("-bundle-")[1].split(".zip")[0]
		# Use nosman to publish Nodos:
		logger.info("Running nosman publish")
		nosman_args = [f"nodos", "-w", WORKSPACE_FOLDER, "publish", "--path", path, "--name", package_name, "--version", f"{major}.{minor}.{patch}", "--version-suffix", f".b{build_number}", "--type", "nodos", "--vendor", "Nodos", "--publisher-name", "Nodos", "--publisher-email",
					"bot@nodos.dev"]
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
