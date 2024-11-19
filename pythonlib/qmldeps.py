#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2023 Sandro Knauß <hefee@debian.org>
# SPDX-License-Identifier: LGPL-2.0-or-later

import argparse
import collections
from dataclasses import dataclass
import itertools
import json
import logging
import os
import pathlib
import re
import subprocess
import sys
import yaml

from debian import deb822

logging.basicConfig(format='%(levelname).1s: dh_qmldeps '
                           '%(module)s:%(lineno)d: %(message)s')
log = logging.getLogger('dh_qmldeps')

PATHS = [pathlib.Path(__file__).parent/"datalib",
         pathlib.Path('/usr/share/pkg-kde-tools/lib')
        ]

@dataclass
class QtConfig:
    """Config class to be able to switch configs for different QT versions."""
    version: str
    qmlimportscanner: str
    basepath: str

    @property
    def substvar_basename(self):
        return f"qml{self.version}"

    @property
    def qt_name(self):
        return f"qt{self.version}"

    def substvar_name(self, name):
        return f"{self.substvar_basename}:{name}"

def get_config():
    """Read config file and return a dict with version: QtConfig"""
    for path in PATHS:
        config_name = "qt_version_info.yml"
        p = path/config_name
        if p.exists():
            c = yaml.load(p.read_text(), yaml.BaseLoader)
            for qt_version in c:
                c[qt_version] = QtConfig(version=qt_version,**c[qt_version])
            return c

    raise FileNotFoundError(f"Did't find '{config_name}' in {PATHS}")


class DebianControl:
    """ Simple class for debian/control file.

    source: with point to the source entry in contrile file
    packages: dict with all binary packages in control file

    """
    def __init__(self, path: pathlib.Path) -> None:
        self.path = path

        self.read_path(path)

    def read_path(self, path:pathlib.Path) -> None:
        self.source = None
        self.packages = {}
        with path.open() as cl:
            for block in deb822.Deb822.iter_paragraphs(cl):
                if block.get("Source"):
                    self.source = block
                else:
                    self.packages[block.get("Package")] = block

    def isSinglePackage(self) -> bool:
        """Is there only one binary package?"""
        return len(self.packages) == 1


def set_substvar(path:pathlib.Path, substvars: dict):
    """ handles a debian/substvars file.

        path: path to substvars file.
        substsvars: is a dict to set key,value in the substvars file.
    """
    data = ''
    if path.exists():
        data = path.read_text()

    for name, values in substvars.items():
        p = data.find(f"{name}=")
        items = set()
        if p > -1:
            e = data[p:].find('\n')
            line = data[p + len(f"{name}="):p + e if e > -1 else None]
            items = set(i.strip() for i in line.split(',') if i)
        else:
            p = len(data)
            e = -1

        if values - items:
            items |= values

            new_line = ",".join(sorted(items))
            start = data[:p]
            end = ""
            if e > -1:
                end = data[p + e:]

            data = start

            if data:
                data += "\n"

            data += f"{name}={new_line}\n"

            if end.strip():
                data += end

    data = data.replace('\n\n', '\n')
    if data:
        path.write_text(data)


def iter_part_over_version(part: str, version: str):
    """ iter over version variants.

    >>> gen = iter_part_over_version("test", "1.2")
    >>> list(gen)
    ["test.1.2",
     "test.1",
     "test"
    ]
    """
    pos = None

    v = version
    while pos != -1:
        v = v[:pos]
        pos = v.rfind(".")
        yield f"{part}.{v}"
    yield part

def iter_tail(parts: list, version: str):
    """iter over all version parants of the tail part of the parts.

    >>> gen = iter_tail(["a","b"], "1")
    >>> list(gen)
    [["a.1","b.1],
     ["a.1", "b"],
     ["a", "b.1"],
     ["a", "b"]
    ]
    """

    item = parts[0]
    tail = parts[1:]
    for i in iter_part_over_version(item, version):
        if tail:
            for t in iter_tail(tail, version):
                yield[i, *t]
        else:
            yield [i,]


@dataclass
class QMLModule:
    name: str
    relpath: str
    debian_pkg: str


class QMLModules:
    """Dict of QML modules with QML module name as key and QMLModule as value."""
    def __init__(self, base_path: pathlib.Path, apt_file:bool):
        self.base_path = base_path
        self._fill_modules(apt_file)

    def _fill_modules(self, apt_file:bool):
        modules = collections.defaultdict(dict)
        try:
            output = subprocess.check_output(["dpkg-query", "-S", self.base_path/"**/qmldir"], text=True)
            for line in output.splitlines():
                package, *_ ,path = line.split(":")
                path = pathlib.Path(path.strip())
                name = self._qmlname(path)
                module = QMLModule(name, self._relpath(path), package)
                modules[module.name][module.relpath] = module
        except subprocess.CalledProcessError:
            pass

        if apt_file:
            _ = str(self.base_path/"*/qmldir")
            search_path = _.replace("*",".*")
            output = subprocess.check_output(["apt-file", "search", "-x", search_path], text=True)
            for line in output.splitlines():
                package, *_ ,path = line.split(":")
                path = pathlib.Path(path.strip())
                name = self._qmlname(path)
                module = QMLModule(name, self._relpath(path), package)
                print(module.name)
                modules[module.name][module.relpath] = module


        glob = str(self.base_path.relative_to("/")/"**/qmldir")
        for package in DebianControl(pathlib.Path("debian/control")).packages:
            package_path = pathlib.Path(f"debian/{package}")
            for path in package_path.glob(glob):
                # Make path abolute like it would be if installed
                path = pathlib.Path("/")/path.relative_to(package_path)
                name = self._qmlname(path)
                module = QMLModule(name, self._relpath(path), package)
                modules[module.name][module.relpath] = module

        self.modules = dict(modules)

    def _relpath(self, path: pathlib.Path):
        """strip self.basepath from path and remove the qmldir at the end."""
        parts = path.parts
        start = len(self.base_path.parts)
        end = -1 if parts[-1] == "qmldir" else None
        return "/".join(parts[start:end])

    def _qmlname(self, path: pathlib.Path):
        """tranlate a path to QML name.

        e.g. /usr/lib/x86_64-linux-gnu/qt5/qml/org/kde/kirigami.2/templates/qmldir
             -> "org.kde.kirigami.templates"
        """
        relpath = self._relpath(path)
        name = re.sub(r"(\.[0-9])+(/|$)",r"\g<2>", relpath)
        return name.replace("/",".")

    def best_matching_module(self, module_name:str, version: str):
        """the best matching QML module for a specific version.

        QML Modules can be installed in different versions e.g.

        QtQuick.Controls 2.X -> .../qml/QtQuick/Controls.2
        QtQuick.Controls 1.X -> .../qml/QtQuick/Controls

        but there is also KDE Kirigami, that does do the version different:

        org.kde.kirigami.templates 2.X .../kirigami.2/templates

        implements "the selection of different versions of a module in
        subdirectories of its own":

        https://doc.qt.io/qt-6/qtqml-modules-identifiedmodules.html#locally-installed-identified-modules

        """
        module_variants = self.modules[module_name]
        if len(module_variants) == 1:
               return next(iter(module_variants.values()))

        best_matching_module_path = next(i for i in iter_tail(module_name.split("."), version) if "/".join(i) in module_variants)
        return module_variants["/".join(best_matching_module_path)]


def get_overrides() -> dict[str, set[str]]:
    """translate the qmldeps.overrides to an dict."""
    qml_overrides_path = pathlib.Path("debian/qmldeps.overrides")
    overrides = dict()
    if not qml_overrides_path.exists():
        return overrides

    for line in qml_overrides_path.read_text().splitlines():
        parts = line.split(" ")
        overrides[parts[0]] = " ".join(parts[1:])

    return overrides


class Status:
    """track the status.
    the failed propery tells, if the detection failed somewhere"""
    def __init__(self):
        self.failed = False

status = Status()


def detect_qml_deps_in_qmldir(qmldir: pathlib.Path, qml_modules: QMLModules) -> set[QMLModule]:
    """transform import and depends line in qmldir files to QMLModules"""
    pkgs = set()
    importline = re.compile(r"^\s*(import|depends)\s+(?P<name>[^ \t]+)(\s+(?P<version>.+))?\s*$")
    for line in qmldir.read_text().splitlines():
        if m := importline.match(line):
            name = m.group("name")
            version = m.group("version")
            if version == "auto":
                version="1"
            elif version is None:
                version="1"
            try:
                module = qml_modules.best_matching_module(name, version)
            except KeyError:
                log.error(f"Missing QML module {name}")
                status.failed = True
            else:
                pkgs.add(module.debian_pkg)
    return pkgs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-v', '--verbose', action='store_true',
        default=os.environ.get('DH_VERBOSE') == '1',
        help='turn verbose mode on')
    parser.add_argument(
        '--show', action='store_true',
        help='Show dependecies on stdout.')
    parser.add_argument(
        '-p', '--package',
        help='pacakge name to act on')
    parser.add_argument(
        '--qt',
        default="6",
        help='choose QT version')
    parser.add_argument(
        '--apt-file', action='store_true',
        help="use apt-file to search for QML modules")
    parser.add_argument(
        'qis', nargs='+',
        help="arguments for qmlimportscanner.")

    options, unused_args = parser.parse_known_args()

    if options.verbose:
        log.setLevel(logging.DEBUG)
        log.debug(f'{sys.argv=}')
        log.debug(f'{options=}')
        log.debug(f'{unused_args=}')
    else:
        log.setLevel(logging.INFO)

    status.failed = False

    config = get_config()
    config_qt = config[options.qt]
    qml_modules = QMLModules(pathlib.Path(config_qt.basepath), options.apt_file)

    for name, pkg in get_overrides().items():
        module = QMLModule(name, "override", pkg.strip())
        qml_modules.modules[name] = {"override": module}

    qmlimportscanner = config_qt.qmlimportscanner
    if not pathlib.Path(qmlimportscanner).exists():
        qmlimportscanner = "debian/tmp/"+qmlimportscanner
        if not pathlib.Path(qmlimportscanner).exists():
            log.error(f"Missing {config_qt.qmlimportscanner}.")
            sys.exit(2)

    output = subprocess.check_output([qmlimportscanner, *options.qis])

    qmldirs = []
    mode = None
    for entry in options.qis:
        if entry.startswith("-"):
            mode = entry
        elif mode == "-rootPath":
            qmldirs.append(pathlib.Path(entry+"/qmldir"))
        elif mode == "-qmlFiles" and entry.endswith("/qmldir"):
            qmldirs.append(pathlib.Path(entry))

    pkgs = set()

    for qmldir in qmldirs:
        pkgs |= detect_qml_deps_in_qmldir(qmldir, qml_modules)

    for dep in json.loads(output):
        if dep["type"] != "module":
            continue
        name = dep.get("name")
        version = dep.get("version")

        try:
            module = qml_modules.best_matching_module(name, version)
        except KeyError:
            log.error(f"Missing QML module {name}")
            status.failed = True
        else:
            pkgs.add(module.debian_pkg)

    try:
        dc = DebianControl(pathlib.Path("debian/control"))
        if dc.isSinglePackage():
            pkg_name = next(iter(dc.packages.keys()))
        else:
            pkg_name = options.package
    except FileNotFoundError:
        pkg_name = None

    if not pkg_name in dc.packages:
        log.error(f"Unknown package name {pkg_name}")
        pkg_name = None
        status.failed = True

    pkgs -= set([pkg_name, ""])

    if pkg_name:
        if not pkgs:
            if not status.failed:
                log.info("No QML depedencies detected.")
                return
            else:
                sys.exit(1)

        pkg = dc.packages[pkg_name]
        if options.show:
            print("depends on:")
            print(", ".join(sorted(pkgs)))

        var_name = config_qt.substvar_name("Depends")
        var = f"${{{var_name}}}"
        recommends = pkg.get("Recommends", "")

        if not var in pkg.get("Depends", "") and not var in recommends:
            log.error(f"cannot insert qml dependency (missing {var} in Depends/Recommends)")
            status.failed = True

        if recommends:
            recommends = deb822.PkgRelation.parse_relations(recommends)
            pkgs -= set(i["name"] for i in itertools.chain.from_iterable(recommends))

        data = {var_name: pkgs}
        substvars_path = pathlib.Path(f"debian/{pkg_name}.substvars")
        log.debug(f"{substvars_path}: add {data}")
        set_substvar(substvars_path, data)
    else:
        print("depends on:")
        print(", ".join(sorted(pkgs)))

    if status.failed:
        sys.exit(1)

if __name__ == '__main__':
    main()
