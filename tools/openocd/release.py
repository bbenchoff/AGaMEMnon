#!/usr/bin/env python3
"""Prepare, verify, and package the pinned AGaMEMnon OpenOCD release."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import tempfile
import uuid
import zipfile


HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "manifest.json"


def manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def run(args, cwd=None, capture=False, env=None):
    result = subprocess.run(
        [str(item) for item in args],
        cwd=cwd,
        check=True,
        text=True,
        encoding="utf-8",
        capture_output=capture,
        env=env,
    )
    return result.stdout.strip() if capture else result


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha1(path):
    digest = hashlib.sha1()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text_lf(path, text, encoding="utf-8"):
    """Write text with deterministic LF endings on every supported Python."""
    with Path(path).open("w", encoding=encoding, newline="\n") as stream:
        stream.write(text)


def patch_hashes(data=None):
    data = data or manifest()
    return {
        item: sha256(HERE / item)
        for item in data["openocd"]["patches"]
    }


def verify_environment(platform_name):
    expected = manifest()["build_environment"][platform_name]["packages"]
    # Windows (pacman) and Linux (dpkg) build on pinned CI runners, so a version
    # mismatch is fatal. macOS builds against Homebrew, which has no pinnable
    # distribution snapshot, so its manifest versions are a reference: a missing
    # package fails, but a rolled version only warns.
    lenient = platform_name == "macos"
    strict_macos_runtime = {"hidapi", "libusb"}
    mismatches = []
    warnings = []
    for package, version in expected.items():
        try:
            if platform_name == "windows":
                actual = run(["pacman", "-Q", package], capture=True).rsplit(" ", 1)[-1]
            elif platform_name == "macos":
                actual = run(["brew", "list", "--versions", package], capture=True).split()[-1]
            else:
                actual = run(
                    ["dpkg-query", "-W", "-f=${Version}", package],
                    capture=True,
                )
        except (OSError, subprocess.CalledProcessError, IndexError):
            actual = "not installed"
        if actual != version:
            if lenient and package not in strict_macos_runtime and actual != "not installed":
                warnings.append(f"{package}: {actual} (reference {version})")
            else:
                mismatches.append(f"{package}: {actual} (expected {version})")
    for line in warnings:
        print(f"warning: build tool version differs from reference: {line}")
    if mismatches:
        raise SystemExit("build environment does not match manifest:\n  " +
                         "\n  ".join(mismatches))
    label = "reference" if lenient else "locked"
    print(f"{platform_name} build environment matches {len(expected)} {label} packages")


def source_provenance(source):
    data = manifest()
    patched_commit = run(["git", "rev-parse", "HEAD"], cwd=source, capture=True)
    return {
        "schema": 1,
        "release": data["release"],
        "official_repository": data["openocd"]["repository"],
        "official_base_commit": data["openocd"]["base_commit"],
        "agamemnon_patched_commit": patched_commit,
        "gerrit": {
            "change": data["openocd"]["gerrit_change"],
            "patchset": data["openocd"]["gerrit_patchset"],
            "commit": data["openocd"]["gerrit_commit"],
            "ref": data["openocd"]["gerrit_ref"],
        },
        "patch_sha256": patch_hashes(data),
        "submodules": data["submodules"],
        "source_date_epoch": data["source_date_epoch"],
        "oracle": data["oracle"],
    }


def prepare(source):
    source = Path(source).resolve()
    data = manifest()
    if source.exists() and any(source.iterdir()):
        raise SystemExit(f"refusing to prepare into non-empty directory: {source}")
    source.parent.mkdir(parents=True, exist_ok=True)
    git_env = dict(os.environ)
    git_env.update({
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "core.autocrlf",
        "GIT_CONFIG_VALUE_0": "false",
        "GIT_CONFIG_KEY_1": "core.filemode",
        "GIT_CONFIG_VALUE_1": "false",
    })
    run(["git", "clone", "-c", "core.autocrlf=false", "-c", "core.filemode=false", "--no-checkout",
         data["openocd"]["repository"], source], env=git_env)
    run(["git", "fetch", "--no-tags", "origin", data["openocd"]["gerrit_ref"]],
        cwd=source, env=git_env)
    fetched = run(["git", "rev-parse", "FETCH_HEAD"], cwd=source, capture=True)
    if fetched != data["openocd"]["gerrit_commit"]:
        raise SystemExit(f"Gerrit ref resolved to {fetched}; expected {data['openocd']['gerrit_commit']}")
    parent = run(["git", "rev-parse", "FETCH_HEAD^"], cwd=source, capture=True)
    if parent != data["openocd"]["base_commit"]:
        raise SystemExit(f"Gerrit parent is {parent}; expected {data['openocd']['base_commit']}")
    run(["git", "checkout", "--detach", data["openocd"]["base_commit"]],
        cwd=source, env=git_env)
    run(["git", "submodule", "sync", "--recursive"], cwd=source, env=git_env)
    run(["git", "submodule", "update", "--init", "--recursive"], cwd=source, env=git_env)
    run(["git", "submodule", "foreach", "--recursive",
         "git config core.autocrlf false && git config core.filemode false"], cwd=source)
    for relative in data["openocd"]["patches"]:
        run(["git", "apply", "--index", "--whitespace=error-all", HERE / relative], cwd=source)
    commit_env = dict(os.environ)
    timestamp = f"@{data['source_date_epoch']} +0000"
    commit_env.update({
        "GIT_AUTHOR_NAME": "AGaMEMnon release builder",
        "GIT_AUTHOR_EMAIL": "release@agamemnon.invalid",
        "GIT_AUTHOR_DATE": timestamp,
        "GIT_COMMITTER_NAME": "AGaMEMnon release builder",
        "GIT_COMMITTER_EMAIL": "release@agamemnon.invalid",
        "GIT_COMMITTER_DATE": timestamp,
    })
    run(["git", "commit", "--no-gpg-sign", "-m",
         "target/riscv: apply Gerrit 9590 and AGaMEMnon config fix"],
        cwd=source, env=commit_env)
    verify_source(source)
    provenance = source_provenance(source)
    write_text_lf(
        source / "AGAMEMNON-PROVENANCE.json",
        json.dumps(provenance, indent=2) + "\n",
    )
    patch_dir = source / "AGAMEMNON-PATCHES"
    patch_dir.mkdir(exist_ok=True)
    for relative in data["openocd"]["patches"]:
        shutil.copy2(HERE / relative, patch_dir / Path(relative).name)
    print(f"prepared verified source: {source}")


def verify_source(source):
    source = Path(source).resolve()
    data = manifest()
    head = run(["git", "rev-parse", "HEAD"], cwd=source, capture=True)
    parent = run(["git", "rev-parse", "HEAD^"], cwd=source, capture=True)
    if parent != data["openocd"]["base_commit"]:
        raise SystemExit(f"patched source parent is {parent}; expected {data['openocd']['base_commit']}")
    expected_head = data["openocd"].get("patched_commit")
    if expected_head and head != expected_head:
        raise SystemExit(f"patched source HEAD is {head}; expected {expected_head}")
    status = run(["git", "submodule", "status", "--recursive"], cwd=source, capture=True)
    actual = {}
    for line in status.splitlines():
        fields = line.lstrip(" +-U").split()
        if len(fields) >= 2:
            actual[fields[1]] = fields[0]
    for path, expected in data["submodules"].items():
        if actual.get(path) != expected:
            raise SystemExit(f"submodule {path} is {actual.get(path)}; expected {expected}")
    run(["git", "diff", "--check", "HEAD"], cwd=source)
    diff = run(["git", "diff", "HEAD^", "HEAD", "--", "src/target/riscv"],
               cwd=source, capture=True)
    required = (
        "adiv5_jim_configure_ext",
        "alternative_dmi",
        "struct adiv5_private_config *pc = &config->adi_pc",
    )
    missing = [marker for marker in required if marker not in diff and marker not in
               (source / "src/target/riscv/riscv.c").read_text(encoding="utf-8")]
    if missing:
        raise SystemExit(f"patched source is missing markers: {', '.join(missing)}")
    print(f"source verified: patched {head}, official parent {parent}, "
          f"{len(data['openocd']['patches'])} patches")


def tracked_files(source):
    output = run(
        ["git", "-c", "core.quotepath=false", "ls-files", "--cached",
         "--recurse-submodules"],
        cwd=source,
        capture=True,
    )
    files = [Path(line) for line in output.splitlines() if line]
    extras = [
        Path("AGAMEMNON-PROVENANCE.json"),
        *[Path("AGAMEMNON-PATCHES") / Path(item).name
          for item in manifest()["openocd"]["patches"]],
    ]
    return sorted(set(files + extras), key=lambda item: item.as_posix())


def copy_source_tree(source, destination):
    source = Path(source)
    destination = Path(destination)
    for relative in tracked_files(source):
        src = source / relative
        if not src.is_file():
            raise SystemExit(f"source archive input is missing {relative}")
        dst = destination / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def normalized_zip(root, archive, epoch):
    stamp = dt.datetime.fromtimestamp(max(epoch, 315532800), tz=dt.timezone.utc)
    date_time = (stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute,
                 stamp.second - stamp.second % 2)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if not path.is_file():
                continue
            relative = path.relative_to(root.parent).as_posix()
            info = zipfile.ZipInfo(relative, date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if os.access(path, os.X_OK) else 0o644) << 16
            out.writestr(info, path.read_bytes(), compresslevel=9)


def normalized_tar_gz(root, archive, epoch):
    with Path(archive).open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch, compresslevel=9) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as out:
                for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                    if not path.is_file():
                        continue
                    relative = Path(root.name) / path.relative_to(root)
                    info = out.gettarinfo(str(path), arcname=relative.as_posix())
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = epoch
                    info.mode = 0o755 if os.access(path, os.X_OK) else 0o644
                    with path.open("rb") as stream:
                        out.addfile(info, stream)


def make_sbom(root, platform_name):
    data = manifest()
    files = []
    relationships = []
    analyzed_packages = set()
    package_file_sha1 = {}
    for index, path in enumerate(sorted(root.rglob("*"), key=lambda item: item.as_posix())):
        if not path.is_file() or path.name == "openocd.spdx.json":
            continue
        relative = path.relative_to(root).as_posix()
        lowered = relative.lower()
        if (
            "libusb" in path.name.lower()
            or lowered.startswith("share/licenses/libusb/")
            or lowered.startswith("share/sources/libusb-")
        ):
            package_id = "SPDXRef-Package-libusb"
        elif (
            "hidapi" in path.name.lower()
            or lowered.startswith("share/licenses/hidapi/")
            or lowered.startswith("share/sources/hidapi-")
        ):
            package_id = "SPDXRef-Package-hidapi"
        else:
            package_id = "SPDXRef-Package-OpenOCD"
        analyzed_packages.add(package_id)
        package_file_sha1.setdefault(package_id, []).append(sha1(path))
        spdx_id = f"SPDXRef-File-{index}"
        files.append({
            "SPDXID": spdx_id,
            "fileName": "./" + relative,
            "checksums": [{"algorithm": "SHA256", "checksumValue": sha256(path)}],
            "licenseConcluded": "NOASSERTION",
            "licenseInfoInFiles": ["NOASSERTION"],
            "copyrightText": "NOASSERTION",
        })
        relationships.append({
            "spdxElementId": package_id,
            "relationshipType": "CONTAINS",
            "relatedSpdxElement": spdx_id,
        })
    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{data['release']}-{platform_name}",
        "documentNamespace": f"https://github.com/bbenchoff/AGaMEMnon/sbom/{uuid.uuid5(uuid.NAMESPACE_URL, data['release'] + platform_name)}",
        "creationInfo": {
            "created": dt.datetime.fromtimestamp(
                data["source_date_epoch"], tz=dt.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "creators": ["Tool: AGaMEMnon tools/openocd/release.py"],
        },
        "packages": [{
            "name": "OpenOCD",
            "SPDXID": "SPDXRef-Package-OpenOCD",
            "versionInfo": data["openocd"]["gerrit_commit"][:12],
            "downloadLocation": data["openocd"]["repository"],
            "filesAnalyzed": True,
            "licenseConcluded": "GPL-2.0-only",
            "licenseDeclared": "GPL-2.0-only",
            "copyrightText": "NOASSERTION",
            "externalRefs": [{
                "referenceCategory": "VCS",
                "referenceType": "vcs",
                "referenceLocator": data["openocd"]["repository"] + "@" +
                                    data["openocd"]["base_commit"],
            }],
        }, {
            "name": "Jim Tcl",
            "SPDXID": "SPDXRef-Package-JimTcl",
            "versionInfo": data["submodules"]["jimtcl"][:12],
            "downloadLocation": "https://github.com/msteveb/jimtcl",
            "filesAnalyzed": False,
            "licenseConcluded": "BSD-2-Clause",
            "licenseDeclared": "BSD-2-Clause",
            "copyrightText": "NOASSERTION",
        }, {
            "name": "libjaylink",
            "SPDXID": "SPDXRef-Package-libjaylink",
            "versionInfo": data["submodules"]["src/jtag/drivers/libjaylink"][:12],
            "downloadLocation": "https://gitlab.zapb.de/libjaylink/libjaylink",
            "filesAnalyzed": False,
            "licenseConcluded": "GPL-2.0-or-later",
            "licenseDeclared": "GPL-2.0-or-later",
            "copyrightText": "NOASSERTION",
        }, {
            "name": "libusb",
            "SPDXID": "SPDXRef-Package-libusb",
            "downloadLocation": "https://github.com/libusb/libusb",
            "filesAnalyzed": "SPDXRef-Package-libusb" in analyzed_packages,
            "licenseConcluded": "LGPL-2.1-or-later",
            "licenseDeclared": "LGPL-2.1-or-later",
            "copyrightText": "NOASSERTION",
        }, {
            "name": "hidapi",
            "SPDXID": "SPDXRef-Package-hidapi",
            "downloadLocation": "https://github.com/libusb/hidapi",
            "filesAnalyzed": "SPDXRef-Package-hidapi" in analyzed_packages,
            "licenseConcluded": "BSD-3-Clause",
            "licenseDeclared": "BSD-3-Clause",
            "copyrightText": "NOASSERTION",
        }],
        "files": files,
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-Package-OpenOCD",
            },
            {
                "spdxElementId": "SPDXRef-Package-OpenOCD",
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": "SPDXRef-Package-libusb",
            },
            {
                "spdxElementId": "SPDXRef-Package-OpenOCD",
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": "SPDXRef-Package-hidapi",
            },
            *relationships,
        ],
    }
    for package in document["packages"]:
        package_id = package["SPDXID"]
        if package.get("filesAnalyzed"):
            concatenated = "".join(sorted(package_file_sha1[package_id])).encode("ascii")
            package["packageVerificationCode"] = {
                "packageVerificationCodeValue": hashlib.sha1(concatenated).hexdigest()
            }
    write_text_lf(
        root / "openocd.spdx.json",
        json.dumps(document, indent=2) + "\n",
    )


def write_file_manifest(root):
    entries = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_file() and path.name != "SHA256SUMS":
            entries.append(f"{sha256(path)}  {path.relative_to(root).as_posix()}")
    write_text_lf(root / "SHA256SUMS", "\n".join(entries) + "\n")


def package(platform_name, source, prefix, output):
    source = Path(source).resolve()
    prefix = Path(prefix).resolve()
    output = Path(output).resolve()
    verify_source(source)
    executable = prefix / "bin" / ("openocd.exe" if platform_name.startswith("windows") else "openocd")
    if not executable.is_file():
        raise SystemExit(f"built OpenOCD not found: {executable}")
    output.mkdir(parents=True, exist_ok=True)
    data = manifest()
    epoch = data["source_date_epoch"]
    with tempfile.TemporaryDirectory(prefix="agamemnon-openocd-") as temporary:
        temporary = Path(temporary)
        binary_root = temporary / f"agamemnon-openocd-{platform_name}"
        shutil.copytree(prefix, binary_root)
        shutil.copy2(source / "COPYING", binary_root / "COPYING")
        shutil.copy2(MANIFEST_PATH, binary_root / "AGAMEMNON-BUILD-MANIFEST.json")
        shutil.copy2(HERE / "README.md", binary_root / "BUILD.md")
        shutil.copytree(HERE / "patches", binary_root / "patches")
        tool_dir = binary_root / "build-tools"
        tool_dir.mkdir()
        shutil.copy2(HERE / "release.py", tool_dir / "release.py")
        shutil.copy2(HERE / "build.sh", tool_dir / "build.sh")
        shutil.copy2(MANIFEST_PATH, tool_dir / "manifest.json")
        shutil.copytree(HERE / "patches", tool_dir / "patches")
        provenance = source_provenance(source)
        provenance["platform"] = platform_name
        provenance["openocd_sha256"] = sha256(executable)
        write_text_lf(
            binary_root / "AGAMEMNON-PROVENANCE.json",
            json.dumps(provenance, indent=2) + "\n",
        )
        make_sbom(binary_root, platform_name)
        write_file_manifest(binary_root)
        if platform_name.startswith("windows"):
            archive = output / f"agamemnon-openocd-{platform_name}.zip"
            normalized_zip(binary_root, archive, epoch)
        else:
            archive = output / f"agamemnon-openocd-{platform_name}.tar.gz"
            normalized_tar_gz(binary_root, archive, epoch)

        source_root = temporary / "agamemnon-openocd-source"
        source_root.mkdir()
        copy_source_tree(source, source_root)
        write_text_lf(
            source_root / "AGAMEMNON-PROVENANCE.json",
            json.dumps(source_provenance(source), indent=2) + "\n",
        )
        shutil.copy2(MANIFEST_PATH, source_root / "AGAMEMNON-BUILD-MANIFEST.json")
        shutil.copy2(HERE / "README.md", source_root / "AGAMEMNON-BUILD.md")
        tool_dir = source_root / "AGAMEMNON-BUILD-TOOLS"
        tool_dir.mkdir()
        shutil.copy2(HERE / "release.py", tool_dir / "release.py")
        shutil.copy2(HERE / "build.sh", tool_dir / "build.sh")
        shutil.copy2(MANIFEST_PATH, tool_dir / "manifest.json")
        shutil.copytree(HERE / "patches", tool_dir / "patches")
        source_archive = output / "agamemnon-openocd-source.tar.gz"
        normalized_tar_gz(source_root, source_archive, epoch)

    for item in (archive, source_archive):
        write_text_lf(
            Path(str(item) + ".sha256"),
            f"{sha256(item)}  {item.name}\n",
            encoding="ascii",
        )
        print(f"{item.name}: {sha256(item)}")


def parse_args():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--source", required=True)
    verify = sub.add_parser("verify-source")
    verify.add_argument("--source", required=True)
    environment = sub.add_parser("verify-environment")
    environment.add_argument("--platform", required=True, choices=("windows", "linux", "macos"))
    pack = sub.add_parser("package")
    pack.add_argument("--platform", required=True,
                      choices=("windows-x64", "linux-x64", "macos-arm64", "macos-x64"))
    pack.add_argument("--source", required=True)
    pack.add_argument("--prefix", required=True)
    pack.add_argument("--output", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    if args.command == "prepare":
        prepare(args.source)
    elif args.command == "verify-source":
        verify_source(args.source)
    elif args.command == "verify-environment":
        verify_environment(args.platform)
    else:
        package(args.platform, args.source, args.prefix, args.output)


if __name__ == "__main__":
    main()
