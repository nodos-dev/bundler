import json
import os
import platform
import runpy
import subprocess
import sys
from collections import OrderedDict
from subprocess import CalledProcessError, CompletedProcess

import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bundler

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
BUILD_NUMBER = "4711"


# What `nosman list --store -p <name>` prints: one line per version and, when the
# release is platform-specific, a "(<platform>)" group, then whatever else it knows
# about the release. Colour is off because the bundler captures the output instead
# of writing to a terminal, and the parser strips the escapes anyway.
STORE_LISTING = """Nodos Store versions
  3.0.0.b900 (x86_64-windows)
  3.0.7.b912 (x86_64-windows) (Nodos API version: 1.4.0) (07 Sep 2025)
  3.1.0.b930 (x86_64-windows)
  3.0.5.b905 (x86_64-linux)
"""


@pytest.fixture(autouse=True)
def clear_store_cache():
    bundler._store_releases_cache.clear()
    yield
    bundler._store_releases_cache.clear()


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    # Every test gets its own scratch "nosman workspace", never the repo's real
    # ./workspace, so ensure_workspace() has somewhere to act on.
    monkeypatch.setattr(bundler, "WORKSPACE_FOLDER", str(tmp_path / "workspace"))


def fake_nosman(calls, list_output=STORE_LISTING, list_returncode=0, list_stderr=""):
    """Fakes both nosman commands list_store_releases can run: `init`, which marks
    the workspace ready by creating the index file ensure_workspace() checks for,
    and `list --store`, which returns the given output."""
    def run(args, **kwargs):
        calls.append(args)
        if "init" in args:
            nosman_dir = os.path.join(bundler.WORKSPACE_FOLDER, ".nosman")
            os.makedirs(nosman_dir, exist_ok=True)
            open(os.path.join(nosman_dir, "index"), "w").close()
            return CompletedProcess(args, 0, "", "")
        return CompletedProcess(args, list_returncode, list_output, list_stderr)
    return run


def test_resolves_the_newest_release_matching_the_prefix(monkeypatch):
    monkeypatch.setattr(bundler, "run", fake_nosman([]))
    resolved = bundler.resolve_package_version(
        "nos.filters", "3.0", bundler.PlatformArch("x86_64-windows"))
    assert resolved == "3.0.7.b912"


def test_resolves_a_different_version_per_platform(monkeypatch):
    monkeypatch.setattr(bundler, "run", fake_nosman([]))
    resolved = bundler.resolve_package_version(
        "nos.filters", "3.0", bundler.PlatformArch("x86_64-linux"))
    assert resolved == "3.0.5.b905"


def test_a_platform_without_a_matching_release_resolves_to_nothing(monkeypatch):
    monkeypatch.setattr(bundler, "run", fake_nosman([]))
    resolved = bundler.resolve_package_version(
        "nos.filters", "3.1", bundler.PlatformArch("x86_64-linux"))
    assert resolved is None


def test_a_package_is_looked_up_once(monkeypatch):
    calls = []
    monkeypatch.setattr(bundler, "run", fake_nosman(calls))
    windows = bundler.PlatformArch("x86_64-windows")
    linux = bundler.PlatformArch("x86_64-linux")
    bundler.resolve_package_version("nos.filters", "3.0", windows)
    bundler.resolve_package_version("nos.filters", "3.0", linux)
    list_calls = [call for call in calls if "list" in call]
    assert len(list_calls) == 1
    assert list_calls[0] == ["nosman", "-w", bundler.WORKSPACE_FOLDER, "list",
                             "--store", "-p", "nos.filters"]


def test_a_nonzero_nosman_exit_is_a_failure(monkeypatch):
    monkeypatch.setattr(bundler, "run", fake_nosman(
        [], list_returncode=1, list_stderr="not authenticated"))
    with pytest.raises(SystemExit):
        bundler.resolve_package_version(
            "nos.filters", "3.0", bundler.PlatformArch("x86_64-windows"))


def test_an_empty_listing_is_a_failure(monkeypatch):
    # nosman warns on stderr and exits 0 when the store or auth call fails, so the
    # listing comes back with only its header line and no releases.
    monkeypatch.setattr(bundler, "run", fake_nosman(
        [], list_output="Nodos Store versions\n"))
    with pytest.raises(SystemExit):
        bundler.resolve_package_version(
            "nos.filters", "3.0", bundler.PlatformArch("x86_64-windows"))


def test_an_exact_build_pin_does_not_match_a_different_build(monkeypatch):
    listing = "Nodos Store versions\n" \
              "  0.4.0.b60 (x86_64-windows)\n" \
              "  0.4.0.b61 (x86_64-windows)\n"
    monkeypatch.setattr(bundler, "run", fake_nosman([], list_output=listing))
    resolved = bundler.resolve_package_version(
        "nos.filters", "0.4.0.b60", bundler.PlatformArch("x86_64-windows"))
    assert resolved == "0.4.0.b60"


def test_a_short_prefix_does_not_match_a_longer_numeric_part(monkeypatch):
    listing = "Nodos Store versions\n  1.50.0.b1 (x86_64-windows)\n"
    monkeypatch.setattr(bundler, "run", fake_nosman([], list_output=listing))
    resolved = bundler.resolve_package_version(
        "nos.filters", "1.5", bundler.PlatformArch("x86_64-windows"))
    assert resolved is None


def test_an_unparseable_version_is_skipped(monkeypatch):
    listing = "Nodos Store versions\n" \
              "  3.0.0-rc1 (x86_64-windows)\n" \
              "  3.0.1.b1 (x86_64-windows)\n"
    monkeypatch.setattr(bundler, "run", fake_nosman([], list_output=listing))
    resolved = bundler.resolve_package_version(
        "nos.filters", "3.0", bundler.PlatformArch("x86_64-windows"))
    assert resolved == "3.0.1.b1"


def test_a_fifth_version_part_is_not_dropped(monkeypatch):
    with pytest.raises(ValueError):
        bundler._parse_store_version("1.2.3.b4.5")
    # As a prefix it is refused; as a store release it is skipped, not read as 1.2.3.b4.
    monkeypatch.setattr(bundler, "run", fake_nosman(
        [], list_output="Nodos Store versions\n  1.2.3.b4.5 (x86_64-windows)\n"))
    with pytest.raises(SystemExit):
        bundler.resolve_package_version(
            "nos.filters", "1.2.3.b4.5", bundler.PlatformArch("x86_64-windows"))
    assert bundler.resolve_package_version(
        "nos.filters", "1.2", bundler.PlatformArch("x86_64-windows")) is None


def test_a_malformed_version_prefix_is_a_failure(monkeypatch):
    monkeypatch.setattr(bundler, "run", fake_nosman([]))
    with pytest.raises(SystemExit):
        bundler.resolve_package_version(
            "nos.filters", "1.x", bundler.PlatformArch("x86_64-windows"))


def test_a_platformless_release_counts_as_any_platform(monkeypatch):
    listing = "Nodos Store versions\n  5.0.0.b1\n"
    monkeypatch.setattr(bundler, "run", fake_nosman([], list_output=listing))
    windows = bundler.resolve_package_version(
        "nos.filters", "5.0", bundler.PlatformArch("x86_64-windows"))
    linux = bundler.resolve_package_version(
        "nos.filters", "5.0", bundler.PlatformArch("x86_64-linux"))
    assert windows == "5.0.0.b1"
    assert linux == "5.0.0.b1"


def test_a_plain_fourth_part_is_the_same_as_a_build_suffix(monkeypatch):
    listing = "Nodos Store versions\n  1.2.3.4 (x86_64-windows)\n"
    monkeypatch.setattr(bundler, "run", fake_nosman([], list_output=listing))
    resolved = bundler.resolve_package_version(
        "nos.filters", "1.2.3.b4", bundler.PlatformArch("x86_64-windows"))
    assert resolved == "1.2.3.4"


def test_ensure_workspace_is_idempotent(monkeypatch):
    calls = []
    monkeypatch.setattr(bundler, "run", fake_nosman(calls))
    bundler.ensure_workspace()
    bundler.ensure_workspace()
    init_calls = [call for call in calls if "init" in call]
    assert len(init_calls) == 1


def fake_resolve(package_name, version_prefix, platform_arch):
    """Every prefix resolves to itself padded to three components, with one build
    number. The versions in the golden manifests are this rule applied to
    nodos-1.5.yaml."""
    parts = version_prefix.split(".")
    while len(parts) < 3:
        parts.append("0")
    return ".".join(parts) + ".b" + BUILD_NUMBER


@pytest.fixture
def bundles_1_5():
    return bundler.load_bundles_data(os.path.join(REPO_ROOT, "nodos-1.5.yaml"))["bundles"]


@pytest.fixture
def resolved(monkeypatch):
    monkeypatch.setattr(bundler, "resolve_package_version", fake_resolve)


def assert_matches_golden(manifest, name, tmp_path):
    """Writes the manifest the way a publish does and compares the text to the golden
    file, so key and group order are pinned, not just the parsed content. Both sides
    are read in text mode, which normalises line endings on either platform."""
    written_path = str(tmp_path / "bundle.yaml")
    bundler.write_manifest(manifest, written_path)
    with open(written_path, "r") as f:
        written_text = f.read()
    with open(os.path.join(GOLDEN_DIR, name), "r") as f:
        golden_text = f.read()
    assert written_text == golden_text


def manifest_for(bundle_key, bundles, platform_key):
    bundle_info = bundler.get_bundle_info(bundle_key, bundles)
    platform_arch = bundler.PlatformArch(platform_key)
    manifests = bundler.build_manifests(bundle_info, bundles, platform_arch, BUILD_NUMBER)
    package_name = bundler.get_bundle_package_name(bundle_info)
    for name, _version, manifest in manifests:
        if name == package_name:
            return manifest
    return None


def test_minimal_matches_its_golden_manifest(bundles_1_5, resolved, tmp_path):
    manifest = manifest_for("minimal", bundles_1_5, "x86_64-windows")
    assert_matches_golden(manifest, "minimal-x86_64-windows.yaml", tmp_path)


def test_standard_nests_minimal_at_the_root(bundles_1_5, resolved, tmp_path):
    manifest = manifest_for("standard", bundles_1_5, "x86_64-windows")
    assert_matches_golden(manifest, "standard-x86_64-windows.yaml", tmp_path)
    assert manifest["includes"] == {"nodos.bundle.minimal": "1.5.0.b4711"}


def test_broadcast_nests_standard_two_levels_deep(bundles_1_5, resolved, tmp_path):
    manifest = manifest_for("broadcast", bundles_1_5, "x86_64-windows")
    assert_matches_golden(manifest, "broadcast-x86_64-windows.yaml", tmp_path)
    assert manifest["includes"] == {"nodos.bundle.standard": "1.5.0.b4711"}


def test_a_sample_lands_under_samples(bundles_1_5, resolved):
    manifest = manifest_for("standard", bundles_1_5, "x86_64-windows")
    assert manifest["packages"]["Samples/{name}"] == {"nos.sample.dxapp": "1.1.0.b4711"}
    assert "nos.sample.dxapp" not in manifest["packages"]["Module/{name}/{version}"]


def test_a_bundle_with_samples_writes_the_module_group_then_the_samples_group(bundles_1_5, resolved):
    manifest = manifest_for("standard", bundles_1_5, "x86_64-windows")
    assert list(manifest["packages"]) == ["Module/{name}/{version}", "Samples/{name}"]


def test_a_bundle_without_samples_omits_the_samples_group(bundles_1_5, resolved):
    manifest = manifest_for("minimal", bundles_1_5, "x86_64-windows")
    assert list(manifest["packages"]) == ["Module/{name}/{version}"]


def test_the_module_group_comes_first_even_when_a_sample_is_listed_first(resolved):
    bundles = [
        {"name": "base", "version": 0, "nodos": "1.5",
         "bundled_packages": OrderedDict([
             ("nos.sample.dxapp", {"version": "1.1", "type": "sample"}),
             ("nos.reflect", "4.0"),
         ])},
    ]
    manifest = manifest_for("base", bundles, "x86_64-windows")
    assert list(manifest["packages"]) == ["Module/{name}/{version}", "Samples/{name}"]


def test_a_bundle_with_no_packages_of_its_own_omits_the_packages_key(resolved):
    bundles = [
        {"name": "base", "version": 0, "nodos": "1.5",
         "bundled_packages": {"nos.reflect": "4.0"}},
        {"name": "top", "version": 0, "includes": ["base"]},
    ]
    manifest = manifest_for("top", bundles, "x86_64-windows")
    assert list(manifest) == ["schema_version", "includes"]


def test_a_bundle_that_takes_nodos_from_an_include_has_no_nodos_key(bundles_1_5, resolved):
    manifest = manifest_for("standard", bundles_1_5, "x86_64-windows")
    assert "nodos" not in manifest
    assert list(manifest) == ["schema_version", "includes", "packages"]


def test_a_bundle_with_no_includes_has_no_includes_key(bundles_1_5, resolved):
    manifest = manifest_for("minimal", bundles_1_5, "x86_64-windows")
    assert "includes" not in manifest
    assert list(manifest) == ["schema_version", "nodos", "packages"]


def test_a_written_manifest_loads_back_with_its_pattern_keys(bundles_1_5, resolved, tmp_path):
    manifest = manifest_for("standard", bundles_1_5, "x86_64-windows")
    written_path = str(tmp_path / "bundle.yaml")
    bundler.write_manifest(manifest, written_path)
    with open(written_path, "r") as f:
        written_text = f.read()
    # Block style only: no flow mappings, and the pattern keys written plain, so
    # PyYAML and serde_yaml both read the same strings back.
    assert not any(line.lstrip().startswith(("{", "- {")) for line in written_text.splitlines())
    assert "  Module/{name}/{version}:\n" in written_text
    assert "  Samples/{name}:\n" in written_text
    loaded = yaml.safe_load(written_text)
    assert loaded == manifest
    assert list(loaded["packages"]) == ["Module/{name}/{version}", "Samples/{name}"]


def test_a_windows_only_package_is_absent_on_linux(bundles_1_5, resolved, tmp_path):
    manifest = manifest_for("standard", bundles_1_5, "x86_64-linux")
    assert_matches_golden(manifest, "standard-x86_64-linux.yaml", tmp_path)
    assert "nos.webcam" not in manifest["packages"]["Module/{name}/{version}"]


def test_vs_is_not_published_off_windows(bundles_1_5, resolved):
    assert manifest_for("vs", bundles_1_5, "x86_64-linux") is None
    assert manifest_for("vs", bundles_1_5, "x86_64-windows") is not None


def test_a_bundle_is_built_after_the_bundles_it_includes(bundles_1_5, resolved):
    bundle_info = bundler.get_bundle_info("vs", bundles_1_5)
    manifests = bundler.build_manifests(bundle_info, bundles_1_5,
                                        bundler.PlatformArch("x86_64-windows"),
                                        BUILD_NUMBER)
    assert [name for name, _version, _manifest in manifests] == [
        "nodos.bundle.minimal",
        "nodos.bundle.standard",
        "nodos.bundle.broadcast",
        "nodos.bundle.vs",
    ]


def test_the_includes_of_a_windows_only_bundle_still_build_on_linux(bundles_1_5, resolved):
    bundle_info = bundler.get_bundle_info("vs", bundles_1_5)
    manifests = bundler.build_manifests(bundle_info, bundles_1_5,
                                        bundler.PlatformArch("x86_64-linux"),
                                        BUILD_NUMBER)
    assert [name for name, _version, _manifest in manifests] == [
        "nodos.bundle.minimal",
        "nodos.bundle.standard",
        "nodos.bundle.broadcast",
    ]


def test_a_package_pinned_at_two_versions_is_refused(resolved):
    # "base" and "top" both pin nos.reflect, at different versions. Expanding "top"
    # would install both, so the second one must be refused before anything is
    # written, not just silently override the first.
    bundles = [
        {"name": "base", "version": 0, "nodos": "1.5",
         "bundled_packages": {"nos.reflect": "4.0"}},
        {"name": "top", "version": 0, "includes": ["base"],
         "bundled_packages": {"nos.reflect": "4.1"}},
    ]
    bundle_info = bundler.get_bundle_info("top", bundles)
    with pytest.raises(SystemExit):
        bundler.build_manifests(bundle_info, bundles,
                                bundler.PlatformArch("x86_64-windows"), BUILD_NUMBER)


def test_an_include_listed_twice_is_refused(resolved):
    # includes is written as a mapping keyed by bundle name, so a second entry for
    # the same bundle would vanish silently instead of appearing twice. Refuse it.
    bundles = [
        {"name": "base", "version": 0, "nodos": "1.5",
         "bundled_packages": {"nos.reflect": "4.0"}},
        {"name": "top", "version": 0, "includes": ["base", {"name": "base", "version": 0}]},
    ]
    bundle_info = bundler.get_bundle_info("top", bundles)
    with pytest.raises(SystemExit):
        bundler.build_manifests(bundle_info, bundles,
                                bundler.PlatformArch("x86_64-windows"), BUILD_NUMBER)


def test_a_pin_that_only_writes_more_parts_than_the_base_agrees_with_it():
    # "1.5" on the base and "1.5.0" on the includer name the same line; only the
    # parts both write are compared.
    bundles = [
        {"name": "base", "version": 0, "nodos": "1.5"},
        {"name": "top", "version": 0, "includes": ["base"], "nodos": "1.5.0"},
    ]
    bundle_info = bundler.get_bundle_info("top", bundles)
    bundler.check_nodos_pin(bundle_info, bundles, bundler.PlatformArch("x86_64-windows"), "1.5.0")


def test_a_pin_that_differs_in_a_part_both_write_is_refused():
    bundles = [
        {"name": "base", "version": 0, "nodos": "1.5"},
        {"name": "top", "version": 0, "includes": ["base"], "nodos": "1.6.0"},
    ]
    bundle_info = bundler.get_bundle_info("top", bundles)
    with pytest.raises(SystemExit):
        bundler.check_nodos_pin(bundle_info, bundles, bundler.PlatformArch("x86_64-windows"), "1.6.0")


def test_version_prefixes_agree_on_the_parts_both_write():
    assert bundler.version_prefixes_agree("1.5", "1.5.0.b4711")
    assert bundler.version_prefixes_agree("1.5.0.b4711", "1.5")
    assert not bundler.version_prefixes_agree("1.5.0.b1", "1.5.0.b2")
    assert not bundler.version_prefixes_agree("1.5.1", "1.5.0")
    with pytest.raises(ValueError):
        bundler.version_prefixes_agree("1.x", "1.5")


def test_check_nodos_pin_checks_every_base_not_just_the_first():
    # "base-a" has no Nodos version on Windows at all, so it must be skipped rather
    # than short-circuit the check; "base-b" does conflict with "top"'s own pin and
    # must still be reached and refused.
    bundles = [
        {"name": "base-a", "version": 0, "nodos": {"x86_64-linux": "1.5"}},
        {"name": "base-b", "version": 0, "nodos": "1.6"},
        {"name": "top", "version": 0, "includes": ["base-a", "base-b"], "nodos": "1.5"},
    ]
    bundle_info = bundler.get_bundle_info("top", bundles)
    with pytest.raises(SystemExit):
        bundler.check_nodos_pin(bundle_info, bundles,
                                bundler.PlatformArch("x86_64-windows"), "1.5")


def test_two_include_less_bases_pinning_different_nodos_is_refused():
    # "top" has no Nodos pin of its own and would inherit one from whichever include
    # resolves first; the other include disagreeing must still be refused here, not
    # left for the store to reject after publishing has already started.
    bundles = [
        {"name": "base-a", "version": 0, "nodos": "1.5"},
        {"name": "base-b", "version": 0, "nodos": "1.6"},
        {"name": "top", "version": 0, "includes": ["base-a", "base-b"]},
    ]
    bundle_info = bundler.get_bundle_info("top", bundles)
    windows = bundler.PlatformArch("x86_64-windows")
    nodos_version = bundler.find_nodos_version(bundle_info, bundles, windows)
    with pytest.raises(SystemExit):
        bundler.check_nodos_pin(bundle_info, bundles, windows, nodos_version)


def test_a_bundle_including_two_conflicting_nodos_pins_is_refused(resolved):
    bundles = [
        {"name": "base-a", "version": 0, "nodos": "1.5"},
        {"name": "base-b", "version": 0, "nodos": "1.6"},
        {"name": "top", "version": 0, "includes": ["base-a", "base-b"]},
    ]
    bundle_info = bundler.get_bundle_info("top", bundles)
    with pytest.raises(SystemExit):
        bundler.build_manifests(bundle_info, bundles,
                                bundler.PlatformArch("x86_64-windows"), BUILD_NUMBER)


def test_one_bundle_at_two_versions_in_a_chain_is_refused(resolved):
    # "top" asks for base at version 0 while "mid" brings base at version 1. Both
    # would publish under one package name, the second overwriting the first's
    # manifest file, and top's pin would name whichever came last.
    bundles = [
        {"name": "base", "version": 0, "nodos": "1.5",
         "bundled_packages": {"nos.reflect": "4.0"}},
        {"name": "base", "version": 1, "nodos": "1.5",
         "bundled_packages": {"nos.reflect": "4.0"}},
        {"name": "mid", "version": 0, "includes": [{"name": "base", "version": 1}]},
        {"name": "top", "version": 0, "includes": [{"name": "base", "version": 0}, "mid"]},
    ]
    bundle_info = bundler.get_bundle_info("top", bundles)
    with pytest.raises(SystemExit):
        bundler.build_manifests(bundle_info, bundles,
                                bundler.PlatformArch("x86_64-windows"), BUILD_NUMBER)


def test_an_include_cycle_is_refused():
    bundles = [
        {"name": "cycle-a", "version": 0, "includes": ["cycle-b"]},
        {"name": "cycle-b", "version": 0, "includes": ["cycle-a"]},
    ]
    bundle_info = bundler.get_bundle_info("cycle-a", bundles)
    with pytest.raises(SystemExit):
        bundler.bundle_chain(bundle_info, bundles)


def test_write_manifest_accepts_a_bare_filename(tmp_path, monkeypatch):
    # A path with no directory part at all must not crash os.makedirs.
    monkeypatch.chdir(tmp_path)
    manifest = {"schema_version": 1, "nodos": "1.5.0.b1"}
    bundler.write_manifest(manifest, "bundle.yaml")
    assert os.path.exists("bundle.yaml")


def test_manifests_publish_in_the_order_given(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(bundler, "run", fake_run)
    manifests = [
        ("nodos.bundle.minimal", "1.5.0.b4711",
         {"schema_version": 1, "nodos": "1.5.0.b4711"}),
        ("nodos.bundle.standard", "1.5.0.b4711",
         {"schema_version": 1, "includes": {"nodos.bundle.minimal": "1.5.0.b4711"}}),
    ]
    bundler.publish_manifests(manifests, str(tmp_path),
                              bundler.PlatformArch("x86_64-windows"), True)

    assert [args[args.index("--name") + 1] for args in calls] == [
        "nodos.bundle.minimal", "nodos.bundle.standard"]
    for (package_name, version, _manifest), args in zip(manifests, calls):
        assert args[args.index("--type") + 1] == "bundle"
        assert args[args.index("--target-platform") + 1] == "x86_64-windows"
        assert "--no-tag" in args
        assert "--no-fetch-tags" in args
        assert "--dry-run" in args
        expected_path = bundler.manifest_file_path(
            str(tmp_path), package_name, bundler.PlatformArch("x86_64-windows"))
        assert args[args.index("--path") + 1] == os.path.abspath(expected_path)
        assert args[args.index("--version") + 1] == version


def test_a_bundle_publish_stops_at_the_first_failure(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return CompletedProcess(args, 1, "", "boom")

    monkeypatch.setattr(bundler, "run", fake_run)
    manifests = [
        ("nodos.bundle.minimal", "1.5.0.b4711",
         {"schema_version": 1, "nodos": "1.5.0.b4711"}),
        ("nodos.bundle.standard", "1.5.0.b4711",
         {"schema_version": 1, "includes": {"nodos.bundle.minimal": "1.5.0.b4711"}}),
    ]
    with pytest.raises(SystemExit):
        bundler.publish_manifests(manifests, str(tmp_path),
                                  bundler.PlatformArch("x86_64-windows"), True)
    assert len(calls) == 1


def test_release_notes_become_the_changelog_when_present(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(bundler, "run", fake_run)
    notes_text = "## nodos.bundle.minimal 1.5.0.b4711 (x86_64-windows)\n"
    notes_path = os.path.join(str(tmp_path), "release-notes-x86_64-windows.md")
    os.makedirs(str(tmp_path), exist_ok=True)
    with open(notes_path, "w") as f:
        f.write(notes_text)
    manifest = {"schema_version": 1, "nodos": "1.5.0.b4711"}
    bundler.publish_manifests([("nodos.bundle.minimal", "1.5.0.b4711", manifest)],
                              str(tmp_path), bundler.PlatformArch("x86_64-windows"), True,
                              changelog_for="nodos.bundle.minimal")
    args = calls[0]
    assert args[args.index("--changelog") + 1] == notes_text


def test_no_changelog_flag_without_release_notes(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(bundler, "run", fake_run)
    manifest = {"schema_version": 1, "nodos": "1.5.0.b4711"}
    bundler.publish_manifests([("nodos.bundle.minimal", "1.5.0.b4711", manifest)],
                              str(tmp_path), bundler.PlatformArch("x86_64-windows"), True,
                              changelog_for="nodos.bundle.minimal")
    assert "--changelog" not in calls[0]


def test_only_the_requested_bundles_publish_carries_the_changelog(tmp_path, monkeypatch):
    """The notes describe the requested bundle, standard; minimal is only along for the
    ride as a dependency and must publish with no changelog of its own."""
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(bundler, "run", fake_run)
    notes_text = "## nodos.bundle.standard 1.5.0.b4711 (x86_64-windows)\n"
    notes_path = os.path.join(str(tmp_path), "release-notes-x86_64-windows.md")
    os.makedirs(str(tmp_path), exist_ok=True)
    with open(notes_path, "w") as f:
        f.write(notes_text)
    manifests = [
        ("nodos.bundle.minimal", "1.5.0.b4711",
         {"schema_version": 1, "nodos": "1.5.0.b4711"}),
        ("nodos.bundle.standard", "1.5.0.b4711",
         {"schema_version": 1, "includes": {"nodos.bundle.minimal": "1.5.0.b4711"}}),
    ]
    bundler.publish_manifests(manifests, str(tmp_path), bundler.PlatformArch("x86_64-windows"), True,
                              changelog_for="nodos.bundle.standard")
    minimal_call, standard_call = calls
    assert "--changelog" not in minimal_call
    assert standard_call[standard_call.index("--changelog") + 1] == notes_text


def test_a_published_manifest_is_written_next_to_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(bundler, "run", lambda args, **kwargs: CompletedProcess(args, 0, "", ""))
    manifest = {"schema_version": 1, "nodos": "1.5.0.b4711"}
    bundler.publish_manifests([("nodos.bundle.minimal", "1.5.0.b4711", manifest)],
                              str(tmp_path), bundler.PlatformArch("x86_64-linux"), True)
    written = tmp_path / "x86_64-linux" / "nodos.bundle.minimal" / "bundle.yaml"
    with open(str(written), "r") as f:
        assert yaml.safe_load(f) == manifest


NESTED_MANIFESTS = [
    ("nodos.bundle.minimal", "1.5.0.b4711", {
        "schema_version": 1,
        "nodos": "1.5.2.b4711",
        "packages": {"Module/{name}/{version}": {"nos.reflect": "4.0.0.b4711"}},
    }),
    ("nodos.bundle.standard", "1.5.0.b4711", {
        "schema_version": 1,
        "includes": {"nodos.bundle.minimal": "1.5.0.b4711"},
        "packages": {
            "Module/{name}/{version}": {"nos.filters": "4.0.1.b4711"},
            "Samples/{name}": {"nos.sample.dxapp": "1.1.0.b4711"},
        },
    }),
]


def test_manifest_members_fill_in_each_groups_pattern():
    members = bundler.manifest_members(NESTED_MANIFESTS[1][2])
    assert members == [
        {"name": "nodos.bundle.minimal", "version": "1.5.0.b4711", "path": ""},
        {"name": "nos.filters", "version": "4.0.1.b4711", "path": "Module/nos.filters/4.0.1.b4711"},
        {"name": "nos.sample.dxapp", "version": "1.1.0.b4711", "path": "Samples/nos.sample.dxapp"},
    ]
    assert bundler.manifest_members(NESTED_MANIFESTS[0][2])[0] == {
        "name": "nodos", "version": "1.5.2.b4711", "path": ""}


def test_a_nested_bundle_is_folded_into_its_members():
    members = bundler.expand_manifest_members("nodos.bundle.standard", NESTED_MANIFESTS)
    assert [member["name"] for member in members] == [
        "nodos", "nos.reflect", "nos.filters", "nos.sample.dxapp"]


def test_release_notes_name_what_changed_since_the_previous_bundle():
    members = bundler.expand_manifest_members("nodos.bundle.standard", NESTED_MANIFESTS)
    previous = OrderedDict([
        ("nodos", "1.5.1.b4600"),
        ("nos.reflect", "4.0.0.b4600"),
        ("nos.sample.dxapp", "1.0.9.b4600"),
    ])
    notes = bundler.format_release_notes(
        "nodos.bundle.standard", "1.5.0.b4711", "1.5.0.b4600",
        bundler.PlatformArch("x86_64-windows"), members, previous)

    assert "## nodos.bundle.standard 1.5.0.b4711 (x86_64-windows)" in notes
    assert "- Version: 1.5.2.b4711 <- 1.5.1.b4600" in notes
    assert "### Modules (2)" in notes
    assert "- nos.reflect: 4.0.0.b4711 <- 4.0.0.b4600" in notes
    assert "- nos.filters: 4.0.1.b4711 (new)" in notes
    assert "### Samples (1)" in notes
    assert "- nos.sample.dxapp: 1.1.0.b4711 <- 1.0.9.b4600" in notes
    assert "- nodos.bundle.standard 1.5.0.b4600" in notes


def test_release_notes_say_a_first_publish_has_no_previous_release():
    members = bundler.expand_manifest_members("nodos.bundle.standard", NESTED_MANIFESTS)
    notes = bundler.format_release_notes(
        "nodos.bundle.standard", "1.5.0.b4711", "",
        bundler.PlatformArch("x86_64-windows"), members, OrderedDict())
    assert "### Previous Release\n- First publish" in notes


def test_release_notes_omit_the_engine_heading_with_no_engine_member():
    members = [{"name": "nos.filters", "version": "4.0.1.b4711",
               "path": "Module/nos.filters/4.0.1.b4711"}]
    notes = bundler.format_release_notes(
        "nodos.bundle.standard", "1.5.0.b4711", "1.5.0.b4600",
        bundler.PlatformArch("x86_64-windows"), members, OrderedDict())
    assert "### Engine" not in notes
    assert "### Modules (1)" in notes


def test_release_notes_name_the_bundles_this_one_includes():
    includes = bundler.direct_manifest_includes("nodos.bundle.standard", NESTED_MANIFESTS)
    assert includes == [("nodos.bundle.minimal", "1.5.0.b4711")]

    members = bundler.expand_manifest_members("nodos.bundle.standard", NESTED_MANIFESTS)
    notes = bundler.format_release_notes(
        "nodos.bundle.standard", "1.5.0.b4711", "1.5.0.b4600",
        bundler.PlatformArch("x86_64-windows"), members, OrderedDict(), includes)
    assert "### Includes" in notes
    assert "- nodos.bundle.minimal: 1.5.0.b4711" in notes


def test_release_notes_list_members_removed_on_the_runner_platform(monkeypatch):
    monkeypatch.setattr(bundler, "get_cur_platform_arch",
                        lambda: bundler.PlatformArch("x86_64-windows"))
    members = bundler.expand_manifest_members("nodos.bundle.standard", NESTED_MANIFESTS)
    previous = OrderedDict([
        ("nodos", "1.5.1.b4600"),
        ("nos.reflect", "4.0.0.b4600"),
        ("nos.old_plugin", "1.0.0.b4600"),
    ])
    notes = bundler.format_release_notes(
        "nodos.bundle.standard", "1.5.0.b4711", "1.5.0.b4600",
        bundler.PlatformArch("x86_64-windows"), members, previous)
    assert "### Removed (1)" in notes
    assert "- nos.old_plugin: 1.0.0.b4600" in notes


def test_removed_members_are_not_listed_off_the_runner_platform(monkeypatch):
    monkeypatch.setattr(bundler, "get_cur_platform_arch",
                        lambda: bundler.PlatformArch("x86_64-windows"))
    members = bundler.expand_manifest_members("nodos.bundle.standard", NESTED_MANIFESTS)
    previous = OrderedDict([
        ("nodos", "1.5.1.b4600"),
        ("nos.reflect", "4.0.0.b4600"),
        ("nos.old_plugin", "1.0.0.b4600"),
    ])
    notes = bundler.format_release_notes(
        "nodos.bundle.standard", "1.5.0.b4711", "1.5.0.b4600",
        bundler.PlatformArch("x86_64-linux"), members, previous)
    assert "### Removed" not in notes


def test_the_previous_members_are_read_from_the_store(monkeypatch):
    calls = []
    info = json.dumps({
        "name": "nodos.bundle.standard",
        "version": "1.5.0.b4600",
        "package_type": "Bundle",
        "platform": "x86_64-windows",
        "members": [
            {"name": "nodos", "version": "1.5.1.b4600", "package_type": "Nodos", "path": ""},
            {"name": "nos.reflect", "version": "4.0.0.b4600", "package_type": "Plugin",
             "path": "Module/nos.reflect/4.0.0.b4600"},
        ],
    })

    def fake_run(args, **kwargs):
        calls.append(args)
        return CompletedProcess(args, 0, info, "")

    monkeypatch.setattr(bundler, "run", fake_run)
    members = bundler.read_store_bundle_members("nodos.bundle.standard", "1.5.0.b4600")
    assert members == OrderedDict([("nodos", "1.5.1.b4600"), ("nos.reflect", "4.0.0.b4600")])
    info_calls = [call for call in calls if "info" in call]
    assert info_calls == [["nosman", "-w", bundler.WORKSPACE_FOLDER, "info",
                           "nodos.bundle.standard", "1.5.0.b4600"]]


def test_a_nonzero_nosman_info_exit_is_a_failure(monkeypatch):
    def fake_run(args, **kwargs):
        if "info" in args:
            return CompletedProcess(args, 1, "", "not found on the store")
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(bundler, "run", fake_run)
    with pytest.raises(SystemExit):
        bundler.read_store_bundle_members("nodos.bundle.standard", "1.5.0.b4600")


def test_unparseable_nosman_info_output_is_a_failure(monkeypatch):
    def fake_run(args, **kwargs):
        if "info" in args:
            return CompletedProcess(args, 0, "not json", "")
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(bundler, "run", fake_run)
    with pytest.raises(SystemExit):
        bundler.read_store_bundle_members("nodos.bundle.standard", "1.5.0.b4600")


def test_the_previous_version_falls_back_to_the_published_line(monkeypatch):
    asked = []

    def fake_run(args, **kwargs):
        asked.append(args)
        return CompletedProcess(args, 0, json.dumps(
            {"name": "nodos.bundle.standard", "version": "1.5.0.b4600", "members": []}), "")

    monkeypatch.setattr(bundler, "run", fake_run)
    assert bundler.previous_bundle_version("nodos.bundle.standard", "1.5", None) == "1.5.0.b4600"
    assert asked[0][-2:] == ["nodos.bundle.standard", "1.5"]


def test_a_given_previous_version_is_taken_as_is(monkeypatch):
    def fail(args, **kwargs):
        raise AssertionError("the store should not be asked")

    monkeypatch.setattr(bundler, "run", fail)
    assert bundler.previous_bundle_version("nodos.bundle.standard", "1.5", "1.5.0.b4321") == "1.5.0.b4321"


def test_an_explicit_empty_previous_version_is_a_first_publish(monkeypatch):
    def fail(args, **kwargs):
        raise AssertionError("the store should not be asked")

    monkeypatch.setattr(bundler, "run", fail)
    assert bundler.previous_bundle_version("nodos.bundle.standard", "1.5", "") == ""


def test_a_failed_previous_version_lookup_is_a_failure_not_first_publish(monkeypatch):
    monkeypatch.setattr(bundler, "run", lambda args, **kwargs: CompletedProcess(
        args, 1, "", "not authenticated"))
    with pytest.raises(SystemExit):
        bundler.previous_bundle_version("nodos.bundle.standard", "1.5", None)


def test_unparseable_previous_version_output_is_a_failure(monkeypatch):
    monkeypatch.setattr(bundler, "run", lambda args, **kwargs: CompletedProcess(
        args, 0, "not json", ""))
    with pytest.raises(SystemExit):
        bundler.previous_bundle_version("nodos.bundle.standard", "1.5", None)


def test_the_removed_zip_path_is_gone():
    for name in ["create_bundle", "package", "create_nodos_release", "check_dependencies",
                 "list_github_releases", "get_bundled_packages", "get_nodos_version"]:
        assert not hasattr(bundler, name), f"{name} should be gone"


STORE_LISTINGS_BY_PACKAGE = {
    "nodos": "Nodos Store versions\n  1.5.2.b9000\n",
    "nos.reflect": "Nodos Store versions\n  4.0.3.b9001\n",
    "nos.filters": "Nodos Store versions\n  4.0.1.b9002\n",
}


def test_main_publishes_every_bundle_for_every_platform_as_a_dry_run(tmp_path, monkeypatch):
    """Runs bundler.py as a script, the way the workflow does, with every nosman call
    faked. Two platforms times two bundles (standard includes minimal) must publish in
    dependency order, and a manifest and one set of release notes must land on disk."""
    yaml_path = tmp_path / "nodos-1.5.yaml"
    yaml_path.write_text(
        "bundles:\n"
        "- name: minimal\n"
        "  version: 0\n"
        "  nodos: '1.5'\n"
        "  bundled_packages:\n"
        "    nos.reflect: '4.0'\n"
        "- name: standard\n"
        "  version: 0\n"
        "  includes:\n"
        "  - minimal\n"
        "  bundled_packages:\n"
        "    nos.filters: '4.0'\n")

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if "init" in args:
            nosman_dir = os.path.join(str(tmp_path / "workspace"), ".nosman")
            os.makedirs(nosman_dir, exist_ok=True)
            open(os.path.join(nosman_dir, "index"), "w").close()
            return CompletedProcess(args, 0, "", "")
        if "list" in args:
            return CompletedProcess(args, 0, STORE_LISTINGS_BY_PACKAGE[args[-1]], "")
        if "info" in args:
            raise AssertionError("an explicit --previous-version should skip the lookup")
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BUILD_NUMBER", "9500")
    monkeypatch.setattr(sys, "argv", [
        "bundler.py",
        "--bundles-yaml-path", str(yaml_path),
        "--bundle-key", "standard",
        "--platforms", "x86_64-windows,x86_64-linux",
        "--out-dir", "Artifacts",
        # A brand new bundle package: this is its first ever publish, said explicitly
        # since nosman info would just fail to find anything on a nonexistent package.
        "--previous-version", "",
        "--dry-run",
    ])

    runpy.run_path(os.path.join(REPO_ROOT, "bundler.py"), run_name="__main__")

    publish_calls = [call for call in calls if "publish" in call]
    published_names = [call[call.index("--name") + 1] for call in publish_calls]
    assert published_names == [
        "nodos.bundle.minimal", "nodos.bundle.standard",
        "nodos.bundle.minimal", "nodos.bundle.standard",
    ]
    for call in publish_calls:
        assert "--dry-run" in call

    artifacts = tmp_path / "Artifacts"
    for platform_key in ["x86_64-windows", "x86_64-linux"]:
        for package_name in ["nodos.bundle.minimal", "nodos.bundle.standard"]:
            assert (artifacts / platform_key / package_name / "bundle.yaml").exists()
    windows_notes = (artifacts / "release-notes-x86_64-windows.md").read_text()
    assert windows_notes.startswith("## nodos.bundle.standard")
    assert "### Previous Release\n- First publish" in windows_notes
    assert (artifacts / "release-notes-x86_64-linux.md").exists()


def test_a_bundle_with_no_nodos_release_is_skipped_for_that_platform(bundles_1_5, resolved):
    # "vs" only pins Nodos for Windows, so Linux must publish nothing for it at all --
    # not even the bundles it includes, which do have a Linux release of their own.
    bundle_info = bundler.get_bundle_info("vs", bundles_1_5)
    result = bundler.platforms_to_publish(
        bundle_info, bundles_1_5,
        [bundler.PlatformArch("x86_64-windows"), bundler.PlatformArch("x86_64-linux")],
        BUILD_NUMBER)
    assert [platform_arch.key() for platform_arch, _manifests, _nodos_version in result] == [
        "x86_64-windows"]


def test_the_lookup_uses_the_host_nodos_version_when_the_host_is_published():
    to_publish = [
        (bundler.PlatformArch("x86_64-linux"), [], "1.5"),
        (bundler.PlatformArch("x86_64-windows"), [], "1.6"),
    ]
    assert bundler.lookup_nodos_version(to_publish, bundler.PlatformArch("x86_64-windows")) == "1.6"


def test_the_lookup_falls_back_to_the_first_published_platform():
    to_publish = [(bundler.PlatformArch("x86_64-linux"), [], "1.5")]
    assert bundler.lookup_nodos_version(to_publish, bundler.PlatformArch("x86_64-windows")) == "1.5"


def test_a_bundle_the_host_does_not_target_still_looks_up_its_previous_release(tmp_path, monkeypatch):
    """The runner is an Apple Silicon Mac here and the bundle only targets Windows, so
    the host has no Nodos version to name a line with. The lookup must use the published
    platform's line instead of failing on a missing version."""
    yaml_path = tmp_path / "nodos-1.5.yaml"
    yaml_path.write_text(
        "bundles:\n"
        "- name: minimal\n"
        "  version: 0\n"
        "  nodos:\n"
        "    x86_64-windows: '1.5'\n"
        "  bundled_packages:\n"
        "    nos.reflect: '4.0'\n")

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if "init" in args:
            nosman_dir = os.path.join(str(tmp_path / "workspace"), ".nosman")
            os.makedirs(nosman_dir, exist_ok=True)
            open(os.path.join(nosman_dir, "index"), "w").close()
            return CompletedProcess(args, 0, "", "")
        if "list" in args:
            return CompletedProcess(args, 0, STORE_LISTINGS_BY_PACKAGE[args[-1]], "")
        if "info" in args:
            return CompletedProcess(args, 0, json.dumps(
                {"name": "nodos.bundle.minimal", "version": "1.5.0.b4600", "members": []}), "")
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BUILD_NUMBER", "9500")
    monkeypatch.setattr(sys, "argv", [
        "bundler.py",
        "--bundles-yaml-path", str(yaml_path),
        "--bundle-key", "minimal",
        "--platforms", "x86_64-windows",
        "--out-dir", "Artifacts",
        "--dry-run",
    ])

    runpy.run_path(os.path.join(REPO_ROOT, "bundler.py"), run_name="__main__")

    info_calls = [call for call in calls if "info" in call]
    assert info_calls[0][-2:] == ["nodos.bundle.minimal", "1.5"]
    assert any("publish" in call for call in calls)


def test_nothing_published_on_any_selected_platform_is_a_failure(tmp_path, monkeypatch):
    """Selecting only platforms the bundle has no release for must not exit quietly with
    nothing done -- that is a failure naming the bundle and the platforms asked for."""
    yaml_path = tmp_path / "nodos-1.5.yaml"
    yaml_path.write_text(
        "bundles:\n"
        "- name: minimal\n"
        "  version: 0\n"
        "  nodos:\n"
        "    x86_64-windows: '1.5'\n"
        "  bundled_packages:\n"
        "    nos.reflect: '4.0'\n")

    monkeypatch.setattr(subprocess, "run",
                        lambda args, **kwargs: CompletedProcess(args, 0, "", ""))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BUILD_NUMBER", "9500")
    monkeypatch.setattr(sys, "argv", [
        "bundler.py",
        "--bundles-yaml-path", str(yaml_path),
        "--bundle-key", "minimal",
        "--platforms", "x86_64-linux",
        "--out-dir", "Artifacts",
        "--dry-run",
    ])

    with pytest.raises(SystemExit):
        runpy.run_path(os.path.join(REPO_ROOT, "bundler.py"), run_name="__main__")


def test_an_unsupported_host_platform_is_refused_up_front(monkeypatch):
    # An ARM Windows host would otherwise get as far as the store and die with a
    # "no release" message that says nothing about the host.
    monkeypatch.setattr(platform, "machine", lambda: "ARM64")
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    with pytest.raises(SystemExit):
        bundler.get_cur_platform_arch()


def test_platforms_argument_is_validated_against_the_supported_list():
    with pytest.raises(SystemExit):
        bundler.parse_platform_keys("x86_64-windows,bogus-platform")


def test_an_empty_platforms_argument_uses_the_host_platform(monkeypatch):
    monkeypatch.setattr(bundler, "get_cur_platform_arch",
                        lambda: bundler.PlatformArch("x86_64-linux"))
    result = bundler.parse_platform_keys("")
    assert [platform_arch.key() for platform_arch in result] == ["x86_64-linux"]


def test_platforms_argument_is_split_and_trimmed():
    result = bundler.parse_platform_keys(" x86_64-windows , x86_64-linux ")
    assert [platform_arch.key() for platform_arch in result] == [
        "x86_64-windows", "x86_64-linux"]


def test_out_dir_refuses_the_current_directory_or_a_parent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert bundler.is_cwd_or_an_ancestor(".")
    assert bundler.is_cwd_or_an_ancestor("..")
    assert not bundler.is_cwd_or_an_ancestor("Artifacts")


def test_force_delete_folder_refuses_to_delete_the_current_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        bundler.force_delete_folder(".")


def test_force_delete_folder_exits_on_a_failed_delete(tmp_path, monkeypatch):
    def fail(args, **kwargs):
        raise CalledProcessError(1, args)

    monkeypatch.setattr(bundler, "run", fail)
    target = tmp_path / "Artifacts"
    target.mkdir()
    with pytest.raises(SystemExit):
        bundler.force_delete_folder(str(target))


def test_the_unused_version_helpers_are_gone():
    for name in ["getenv", "parse_version_tuple", "get_semver_from_full_version"]:
        assert not hasattr(bundler, name), f"{name} should be gone"


def test_previous_versions_are_read_once_before_any_publish(tmp_path, monkeypatch):
    """A later platform must never compare against the release this run just published, and
    nosman info only ever answers for the host platform anyway, so the previous-version and
    previous-members lookups happen exactly once for the whole run, before the first
    publish, no matter how many platforms are selected."""
    yaml_path = tmp_path / "nodos-1.5.yaml"
    yaml_path.write_text(
        "bundles:\n"
        "- name: minimal\n"
        "  version: 0\n"
        "  nodos: '1.5'\n"
        "  bundled_packages:\n"
        "    nos.reflect: '4.0'\n")

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if "init" in args:
            nosman_dir = os.path.join(str(tmp_path / "workspace"), ".nosman")
            os.makedirs(nosman_dir, exist_ok=True)
            open(os.path.join(nosman_dir, "index"), "w").close()
            return CompletedProcess(args, 0, "", "")
        if "list" in args:
            return CompletedProcess(args, 0, STORE_LISTINGS_BY_PACKAGE[args[-1]], "")
        if "info" in args:
            if args[-1] == "1.5":
                # The previous-version lookup: an earlier release exists on this line.
                return CompletedProcess(args, 0, json.dumps(
                    {"name": "nodos.bundle.minimal", "version": "1.5.0.b4600"}), "")
            # The previous-members read, keyed by the full version above.
            return CompletedProcess(args, 0, json.dumps(
                {"name": "nodos.bundle.minimal", "version": args[-1], "members": []}), "")
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BUILD_NUMBER", "9500")
    monkeypatch.setattr(sys, "argv", [
        "bundler.py",
        "--bundles-yaml-path", str(yaml_path),
        "--bundle-key", "minimal",
        "--platforms", "x86_64-windows,x86_64-linux",
        "--out-dir", "Artifacts",
        "--dry-run",
    ])

    runpy.run_path(os.path.join(REPO_ROOT, "bundler.py"), run_name="__main__")

    info_indexes = [i for i, call in enumerate(calls) if "info" in call]
    publish_indexes = [i for i, call in enumerate(calls) if "publish" in call]
    assert info_indexes and publish_indexes
    assert max(info_indexes) < min(publish_indexes)
    # One previous-version lookup (args[-1] == "1.5") and one previous-members read
    # (args[-1] == "1.5.0.b4600"): two platforms must not double either of them.
    assert len(info_indexes) == 2
    assert max(info_indexes) < min(publish_indexes)
