#!/usr/bin/env python3
# https://docs.brew.sh/Manpage#commands
# https://docs.brew.sh/Formula-Cookbook#homebrew-terminology
# https://stackoverflow.com/questions/78164818/how-to-download-a-file-from-github-container-registry-cli-command-github-packa
# https://github.com/Homebrew/homebrew-core/pkgs/container/core%2Fwget
# https://github.com/orgs/Homebrew/packages
'''
A lightweight replacement for Homebrew
'''
import os
import re  # compile, findall
import sys  # stdout, stderr, stdout.isatty()
import json  # load, loads
import math  # ceil
import shutil  # rmtre, get_terminal_size
import hashlib  # sha256
import platform  # machine, mac_ver
import subprocess as shell  # otool, install_name_tool, codesign
from datetime import datetime  # now()
from io import StringIO  # Log summary
from tarfile import TarInfo, open as openTarfile
from urllib import request as Req  # build_opener, install_opener, urlretrieve
from urllib.error import HTTPError
from configparser import ConfigParser as IniFile
from webbrowser import open as launchBrowser
from functools import cached_property
from argparse import (
    ArgumentParser, Action, BooleanOptionalAction,
    Namespace as ArgParams,
    _ActionsContainer as ArgsContainer,
    _MutuallyExclusiveGroup as ArgsXorGroup,
)
from typing import (
    Any, Callable, Iterator, NamedTuple, Optional, TypedDict, TypeVar
)


class Env:
    IS_TTY = sys.stdout.isatty()
    CELLAR_PATH = os.environ.get('BREW_PY_CELLAR', '').rstrip('/')


def main() -> None:
    Cellar.init()
    args = parseArgs()
    Log.LEVEL = 3 if args.verbose else Log.LEVEL - args.quiet
    Arch.detect(args)
    args.func(args)
    return


# -----------------------------------
#  CLI functions
# -----------------------------------


# https://docs.brew.sh/Manpage#info-abv-options-formulacask-
def cli_info(args: ArgParams) -> None:
    ''' List versions, dependencies, platforms, etc. '''
    if args.version is True:  # can be either bool or string (not both)
        Log.main(Brew.info(args.package, force=True).version)
        return

    if args.tags is True:
        for tag in sorted(Brew.ghcrTags(args.package, force=True)):
            Log.main(tag)
        return

    if args.digest is True or args.platforms is True:
        if args.version:
            manifest = Brew.ghcrInfo(args.package, args.version, force=True)
        else:
            manifest = Brew.info(args.package, force=True)

        if args.digest:
            Log.main(manifest.digest)
        else:
            for arch in manifest.platforms:
                Log.main(arch)
        return

    Log.info('Package:', args.package)
    pkg = LocalPackage(args.package)
    Log.info('Installed:', 'yes' if pkg.installed else 'no')

    # local information
    if pkg.installed:
        Log.info(' Active version:', pkg.activeVersion or '–')
        Log.info(' Inactive versions:', ', '.join(pkg.inactiveVersions) or '–')

        ver = args.version or pkg.activeVersion
        if ver:
            Log.info(f' Dependencies[{ver}]:')
            vpkg = pkg.version(ver)
            if not vpkg.installed:
                Log.info('  <not installed>')
            else:
                Log.info(' ', ', '.join(sorted(vpkg.dependencies)) or '<none>')

    Log.info()
    Utils.ask('search online?') or exit(0)

    # remote information
    if args.version:
        mode = 'GHCR'
        manifest = Brew.ghcrInfo(args.package, args.version, force=True)
    else:
        mode = 'Brew'
        manifest = Brew.info(args.package, force=True)

    Log.info('Online version:', manifest.version)
    Log.info()
    Log.info(f'{mode}:')
    Log.info(' Digest:')
    Log.info(Txt.prettyList([manifest.digest or '<architecture not found>']))
    Log.info(' Dependencies:')
    deps = manifest.dependencies
    if deps is None:
        deps = ['<architecture not found>']
    Log.info(Txt.prettyList(sorted(deps)) or '  <none>')
    Log.info(' Platforms:')
    Log.info(Txt.prettyList(sorted(manifest.platforms)) or '  <none>')

    if mode == 'Brew':
        Log.info('GHCR:')
        Log.info(' Tags:')
        tags = Brew.ghcrTags(args.package, force=True)
        Utils.printInColumns(sorted(tags), prefix='  ', sep='  |  ')


# https://docs.brew.sh/Manpage#home-homepage---formula---cask-formulacask-
def cli_home(args: ArgParams) -> None:
    ''' Open a project's homepage in a browser. '''
    url = LocalPackage(args.package).homepageUrl
    if not url:
        if not Utils.ask('package not installed. Search online?'):
            return
        url = Brew.info(args.package).homepage
    launchBrowser(url)


# https://docs.brew.sh/Manpage#fetch-options-formulacask-
def cli_fetch(args: ArgParams) -> None:
    ''' Download bottle (binary tar) for package. '''
    Log.info('==> Download', args.package)

    if args.digest:
        Log.info('use provided digest')
        tag = None
        digest = args.digest
    else:
        if args.tag:
            Log.info('use provided tag')
            Log.info('query digest from ghcr ...')
            manifest = Brew.ghcrInfo(args.package, args.tag)
        elif args.ghcr:
            Log.info('query tag from Brew.sh ...')
            tag = Brew.info(args.package).version
            Log.info('query digest from ghcr ...')
            manifest = Brew.ghcrInfo(args.package, tag)
        else:
            Log.info('query digest from Brew.sh ...')
            manifest = Brew.info(args.package)

        tag = manifest.version
        digest = manifest.digest

        if not digest:
            arch = Arch.GHCR if args.tag or args.ghcr else Arch.BREW
            Log.error(f'architecture "{arch}" not found (use -arch).')
            Log.info('Available platforms:')
            Log.info(Txt.prettyList(manifest.platforms))
            exit(1)

    Log.info(' tag:', tag)
    Log.info(' digest:', digest)

    path = Brew.downloadBottle(args.package, tag or digest, digest,
                               askOverwrite=True)
    Log.info('==> ', end='')
    Log.main(path)


# https://docs.brew.sh/Manpage#list-ls-options-installed_formulainstalled_cask-
def cli_list(args: ArgParams) -> None:
    ''' List installed packages. '''
    packages = Cellar.infoAll(assertInstalled=True)
    if args.multiple:
        packages = [x for x in packages if len(x.allVersions) > 1]
    if args.pinned:
        packages = [x for x in packages if x.pinned]
    if args.primary:
        packages = [x for x in packages if x.primary]
    if not packages:
        Log.main('no package found.')
        return

    if args.versions:
        for pkg in packages:
            txt = '{}: {}'.format(pkg.name, pkg.activeVersion or 'not linked')
            if pkg.inactiveVersions:
                txt += ' ({})'.format(', '.join(pkg.inactiveVersions))
            Log.main(txt)
    else:
        Utils.printInColumns([x.name for x in packages],
                             plainList=not Env.IS_TTY or args.__dict__['1'])


# https://docs.brew.sh/Manpage#outdated-options-formulacask-
def cli_outdated(args: ArgParams) -> None:
    ''' Show packages with an updated version available. '''
    hasUpdate = False
    for pkg in Cellar.infoAll():
        if args.all or pkg.primary:
            if pkg.pinned:
                update = False
                onlineVer = '[pinned]'
            else:
                onlineVer = Brew.info(pkg.name, force=args.force).version
                update = onlineVer not in pkg.allVersions

            hasUpdate |= update
            if update or args.unchanged:
                op = '<' if update else '='
                Log.info('{} ({}) {} {}'.format(
                    pkg.name, ', '.join(pkg.allVersions), op, onlineVer))
    if not hasUpdate:
        Log.info('all {} are up to date.'.format(
            'packages and dependencies' if args.all else 'primary packages'))


# https://docs.brew.sh/Manpage#upgrade-options-installed_formulainstalled_cask-
def cli_upgrade(args: ArgParams) -> None:
    '''
    Upgrade outdated packages.
    Will delete old versions, unless package is pinned.
    Pinned packages are skipped by default but can be upgraded if provided
    '''
    if args.packages and args.all:
        Log.error('You cannot use both, use either <package> param or --all')
        return

    Log.info('==> {} package manifests ...'.format(
        'download latest' if args.force else 'get'))
    queue = InstallQueue(dryRun=args.dry, force=False)

    for pkg in Cellar.infoAll(args.packages, assertInstalled=True):
        userRequested = pkg.name in args.packages
        if not (pkg.primary or userRequested or args.all):
            continue
        if pkg.pinned and not (userRequested or args.pinned):
            continue

        bundle = Brew.info(pkg.name, force=args.force)
        if bundle.version in pkg.allVersions:
            continue

        Log.info('{} ({}) -> {}'.format(
            pkg.name, ', '.join(pkg.allVersions), bundle.version))

        if args.all or args.no_dependencies:
            queue.add(pkg.name, bundle.version, bundle.digest)
        else:
            queue.addRecursive(pkg.name)

    if not queue.downloadQueue:
        Log.info('All packages are up-to-date')
        return

    queue.validateQueue()
    queue.download()
    queue.install(isUpgrade=True)

    if args.keep or args.dry:
        return

    Log.info()
    Log.info('==> Delete old versions')
    for pkgName, ver in queue.finished:
        pkg = LocalPackage(pkgName)
        if pkg.pinned:
            Log.warn(f'keeping old version of {pkg.name} (reason: pinned)')
        else:
            pkg.cleanup()


# https://docs.brew.sh/Manpage#deps-options-formulacask-
def cli_deps(args: ArgParams) -> None:
    ''' Show dependencies for package. '''
    depTree = Cellar.getDependencyTree()
    depTree.forward.assertExist(args.packages)

    if args.dot:
        depTree.forward.dotGraph(args.packages or depTree.reverse.directEnd())
    elif args.tree:
        depTree.forward.printTree(
            args.packages or sorted(depTree.forward), depth=args.depth)
    else:
        depTree.forward.printFlat(
            args.packages or sorted(depTree.forward), ' => ',
            leaves=args.leaves, direct=args.depth == 1)


# https://docs.brew.sh/Manpage#upgrade-options-installed_formulainstalled_cask-
def cli_uses(args: ArgParams) -> None:
    ''' Show dependents of package (reverse dependencies). '''
    depTree = Cellar.getDependencyTree()
    depTree.reverse.assertExist(args.packages)

    if args.missing:
        args.packages = sorted(depTree.getMissing(args.packages))
        if not args.packages:
            return

    if args.dot:
        depTree.reverse.dotGraph(
            args.packages or depTree.forward.directEnd(), reverse=True)
    elif args.tree:
        depTree.reverse.printTree(
            args.packages or sorted(depTree.reverse), depth=args.depth)
    else:
        depTree.reverse.printFlat(
            args.packages or sorted(depTree.reverse), ' := ',
            leaves=args.leaves, direct=args.depth == 1)


# https://docs.brew.sh/Manpage#leaves---installed-on-request---installed-as-dependency
def cli_leaves(args: ArgParams) -> None:
    '''List installed packages that are not dependencies of another package.'''
    depTree = Cellar.getDependencyTree()
    Utils.printInColumns(sorted(depTree.reverse.directEnd()),
                         plainList=not Env.IS_TTY or args.__dict__['1'])


# https://docs.brew.sh/Manpage#missing---hide-formula-
def cli_missing(args: ArgParams) -> None:
    '''
    Check the given packages for missing dependencies.
    If no packages are provided, check all kegs.
    Will exit with a non-zero status if any are found to be missing.
    '''
    depTree = Cellar.getDependencyTree()
    depTree.reverse.assertExist(args.packages)
    missing = depTree.getMissing(args.packages)

    if args.no_dependencies:
        Utils.printInColumns(
            sorted(missing), plainList=not Env.IS_TTY or args.__dict__['1'])
    else:
        for pkg in sorted(missing):
            direct = depTree.reverse.direct[pkg]
            leaves = depTree.reverse.getLeaves(pkg)
            Log.main('{} (dependency of: {} ... {})'.format(
                pkg, ', '.join(direct - leaves), ', '.join(leaves)))

    if missing:
        if Log.LEVEL >= 2:
            Log.error(f'missing {len(missing)} dependencies')
        exit(1)
    else:
        Log.info('all dependencies installed')


# https://docs.brew.sh/Manpage#install-options-formulacask-
def cli_install(args: ArgParams) -> None:
    ''' Install package(s) with all dependencies. '''
    needsInstall = []  # type: list[str]
    if args.force:
        needsInstall = args.packages
    else:
        for pkgName in args.packages:
            if LocalPackage(pkgName).installed:
                Log.info(pkgName, 'already installed')
            else:
                needsInstall.append(pkgName)
    if not needsInstall:
        return

    queue = InstallQueue(dryRun=args.dry, force=args.force)
    for pkgName in needsInstall:
        queue.init(pkgName, recursive=not args.no_dependencies)
    queue.validateQueue()
    queue.download()
    queue.install(skipLink=args.skip_link, linkExe=args.binaries)


# https://docs.brew.sh/Manpage#uninstall-remove-rm-options-installed_formulainstalled_cask-
def cli_uninstall(args: ArgParams) -> None:
    ''' Remove / uninstall a package. '''
    queue = UninstallQueue()
    queue.collect(args.packages, args.ignore, leaves=args.leaves,
                  ignoreDependencies=args.no_dependencies)
    if not queue.uninstallQueue:
        return
    if not args.force:
        # hard-fail check. no direct dependencies
        queue.validateQueue()
    # show potential changes
    if not args.dry:
        queue.printUninstallQueue()
    # soft-fail check. warning for any doubly used dependencies
    queue.printSkipped()
    # if interactive, ask user to continue
    if args.dry or args.yes or Utils.ask('Do you want to continue?', 'n'):
        queue.uninstall(dryRun=args.dry)
    else:
        Log.info('abort.')


# https://docs.brew.sh/Manpage#link-ln-options-installed_formula-
def cli_link(args: ArgParams) -> None:
    ''' Link a specific package version (activate). '''
    pkg = LocalPackage(args.package).assertInstalled()
    if pkg.activeVersion:
        # must unlink before relinking (except --bin)
        if args.bin:
            args.version = pkg.activeVersion
        else:
            Log.error(f'already linked to {pkg.activeVersion}. Unlink first.')
            return

    # auto-fill version if there is only one installed
    if not args.version:
        if len(pkg.allVersions) == 1:
            args.version = pkg.allVersions[0]
        else:
            Log.info('Multiple versions found:')
            Log.info(Txt.prettyList(pkg.allVersions))
            Log.error('no package version provided.')
            return

    vpkg = pkg.version(args.version)

    # check if package is really installed
    if not vpkg.installed:
        Log.error('package version', vpkg.version, 'not found')
        return

    if not args.force and vpkg.isKegOnly:
        Log.error(pkg.name, 'is keg-only. Use -f to force linking.')
        return

    # perform link
    vpkg.link(linkOpt=not args.bin, linkBin=not args.no_bin, dryRun=args.dry)
    Log.main('==> Linked', 'binaries for' if args.bin else 'to', vpkg.version)


# https://docs.brew.sh/Manpage#unlink---dry-run-installed_formula-
def cli_unlink(args: ArgParams) -> None:
    ''' Remove symlinks for package to (temporarily) disable it. '''
    pkg = LocalPackage(args.package).assertInstalled()
    if not (prev := pkg.activeVersion):
        Log.error(pkg.name, 'is not active')
        return

    # perform unlink
    pkg.unlink(unlinkOpt=not args.bin, unlinkBin=True, dryRun=args.dry)
    Log.main('==> Unlinked', 'binaries from' if args.bin else '', prev)


def cli_switch(args: ArgParams) -> None:
    ''' Change package version. '''
    pkg = LocalPackage(args.package).assertInstalled()
    if not pkg.activeVersion:
        Log.error('cannot switch, package is not active')
        return
    if pkg.activeVersion == args.version:
        Log.main('already on', pkg.activeVersion)
        return

    # convenience toggle
    if not args.version and len(pkg.inactiveVersions) == 1:
        args.version = pkg.inactiveVersions[0]

    # convenience list print
    if not args.version:
        Log.info('Available versions:')
        Utils.printInColumns(pkg.allVersions, prefix='  ')
        Log.error('no version provided')
        return

    hasBinLinks = bool(pkg.binLinks)
    pkg.unlink(unlinkOpt=True, unlinkBin=hasBinLinks)
    pkg.version(args.version).link(linkOpt=True, linkBin=hasBinLinks)
    Log.main('==> switched to version', pkg.activeVersion)
    if not hasBinLinks:
        Log.warn('no binary links found. Skipped for new version as well.')


def cli_toggle(args: ArgParams) -> None:
    '''
    Link/unlink all binaries of a single package.
    Can be used to switch between versioned packages
    (automatically disables other versions, e.g. node <=> node@22).
    '''
    pkg = LocalPackage(args.package).assertInstalled()
    if not pkg.activeVersion:
        Log.error('Only active packages can be toggled (link first)')
        return

    isActive = bool(pkg.binLinks)
    baseName = pkg.name.split('@')[0]
    allVersions = [x for x in Cellar.infoAll()
                   if x.name == baseName or x.name.startswith(baseName + '@')]

    for prev in allVersions:
        prev.unlink(unlinkOpt=False, unlinkBin=True)

    if isActive:
        Log.info('==> disabled', pkg.name)
    else:
        pkg.version(pkg.activeVersion).link(linkOpt=False, linkBin=True)
        Log.info('==> enabled', pkg.name, pkg.activeVersion)


# https://docs.brew.sh/Manpage#pin-installed_formula-
def cli_pin(args: ArgParams) -> None:
    ''' Prevent specified packages from being upgraded. '''
    for pkg in Cellar.infoAll(args.packages, assertInstalled=True):
        if pkg.pin(True):
            Log.info('pinned', pkg.name)


# https://docs.brew.sh/Manpage#unpin-installed_formula-
def cli_unpin(args: ArgParams) -> None:
    ''' Allow specified packages to be upgraded. '''
    for pkg in Cellar.infoAll(args.packages, assertInstalled=True):
        if pkg.pin(False):
            Log.info('unpinned', pkg.name)


# https://docs.brew.sh/Manpage#cleanup-options-formulacask-
def cli_cleanup(args: ArgParams) -> None:
    '''
    Remove old versions of installed packages.
    If arguments are specified, only do this for the given packages.
    Removes all downloads older than 21 days (see config.ini).
    '''
    total_savings = 0
    packages = Cellar.infoAll(args.packages, assertInstalled=True)
    if args.packages and not packages:
        Log.error('no package found')
        return

    if not args.packages:
        Log.info('==> Removing cached files')
        total_savings += Cellar.cleanup(args.prune, dryRun=args.dry)

    # remove all non-active versions
    Log.info('==> Removing old versions')
    for pkg in packages:
        total_savings += pkg.cleanup(dryRun=args.dry)

    # remove dangling dependencies
    if not args.packages:
        Log.info('==> Removing dangling dependencies')
        depTree = Cellar.getDependencyTree()
        depsOnly = set(x.name for x in packages if not x.primary)
        while dangling := depTree.reverse.directEnd() & depsOnly:
            for dang in dangling:
                total_savings += File.remove(
                    LocalPackage(dang).path, dryRun=args.dry)
                depsOnly.remove(dang)
                del depTree.reverse.direct[dang]
            # update internal dependency tree structure
            for k, v in depTree.reverse.direct.items():
                v.difference_update(dangling)

    # should never happen but just in case, remove symlinks which point nowhere
    Log.info('==> Removing dead links')
    links = Cellar.allBinLinks() + Cellar.allOptLinks()
    if args.packages:
        deadPaths = [pkg.path + '/' for pkg in packages]
        links = [lnk for lnk in links
                 if any(lnk.target.startswith(x) for x in deadPaths)]

    for link in links:
        if not os.path.exists(link.target):
            total_savings += File.remove(link.path, dryRun=args.dry)

    Log.main(Txt.freedDiskSpace(total_savings, dryRun=args.dry))


def cli_export(args: ArgParams) -> None:
    '''
    Take binary and all referenced libs to another folder (relink all dylib)
    '''
    queue = [x for x in args.binaries]
    done = []
    while queue:
        src = os.path.realpath(queue.pop(0))

        if not os.path.exists(src):
            Log.error('file not found', src)
            continue

        isLib = src.split('.')[-1] in ('dylib', 'bundle', 'so')
        tgtDir = os.path.join(args.outdir, 'lib') if isLib else args.outdir
        tgt = os.path.join(tgtDir, os.path.basename(src))

        if os.path.exists(tgt) and not args.force:
            Log.info('[skip] exists', tgt)
            continue

        os.makedirs(tgtDir, exist_ok=True)
        Log.info('copy', tgt)
        shutil.copy2(src, tgt)

        # detect linked libs and collect changes
        cmd_args = []  # type: list[str]
        exe = Dylib(src)
        for oldRef in exe.dylibs:
            lnkRef = exe.expand_path(oldRef)
            assert os.path.exists(lnkRef)
            lnkTgt = os.path.realpath(lnkRef)
            if lnkTgt not in done:
                queue.append(lnkTgt)
                done.append(lnkTgt)
            # link only goes one-way, a lib cannot link back to binary
            newRef = '@loader_path/' + ('' if isLib else 'lib/') \
                + os.path.basename(lnkTgt)
            if oldRef != newRef:
                cmd_args.extend(['-change', oldRef, newRef])

        # fix dylib
        if cmd_args:
            Log.debug('  relink dylib:', cmd_args)
            Bash.install_name_tool(tgt, cmd_args)
            Log.debug('  codesign')
            Bash.codesign(tgt)
            os.utime(tgt, (os.path.getatime(src), os.path.getmtime(src)))


# -----------------------------------
#  CLI
# -----------------------------------

def parseArgs() -> ArgParams:
    cli = Cli(description=__doc__)
    cli.arg_bool('-v', '--verbose', help='increase verbosity')
    cli.arg('-q', '--quiet', action='count', default=0, help='''
        reduce verbosity (-q up to -qqq)''')
    cli.arg('--version', action='version', version='%(prog)s 0.9 beta')

    # info
    cmd = cli.subcommand('info', cli_info)
    cmd.arg('package', help='Brew package name')
    cmd.arg('version', nargs='?', help='If set, search ghcr instead of brew')
    grp = cmd.xor_group()
    grp.arg_bool('--version', help='Retrieve current online version (Brew.sh)')
    grp.arg_bool('--tags', help='Retrieve available online tags (ghcr)')
    grp.arg_bool('--digest', help='''
        Retrieve digest for current architecture (Brew.sh & ghcr)''')
    grp.arg_bool('--platforms', help='''
        List available platform architectures (Brew.sh & ghcr)''')
    cmd.arg('-arch', help='''Manually provide platform architecture
        (e.g. 'arm64_sequoia' (brew), 'arm64|darwin|macOS 15' (ghcr))''')

    # home
    cmd = cli.subcommand('home', cli_home, aliases=['homepage'])
    cmd.arg('package', help='Brew package name')

    # fetch
    cmd = cli.subcommand('fetch', cli_fetch, aliases=['download', 'bottle'])
    cmd.arg('package', help='Brew package name')
    grp = cmd.xor_group()
    grp.arg_bool('-ghcr', help='''
        Download from ghcr registry instead of Brew.sh''')
    grp.arg('-tag', help='Manually provide tag / version (uses ghcr)')
    grp.arg('-digest', help='''
        Manually provide digest hash (direct download, skips tag query)''')
    cmd.arg('-arch', help='''Download for the given platform architecture.
        (e.g. 'arm64_sequoia' (brew), 'arm64|darwin|macOS 15' (ghcr))''')
    cmd.epilog = '''
    If no -ghcr/-tag/-digest is provided, use DIGEST hash of Brew.sh.
    Otherwise, DIGEST hash will be queried from Github registry.'''

    # list
    cmd = cli.subcommand('list', cli_list, aliases=['ls'])
    cmd.arg_bool('--versions', help='Include version numbers in list')
    cmd.arg_bool('-1', help='''
        Force output to be one entry per line.
        This is the default when output is not to a terminal.''')
    cmd.arg_bool('--primary', help='''
        Only show packages which were requested by user, no dependencies.''')
    cmd.arg_bool('--multiple', help='''
        Only show packages with multiple versions installed''')
    cmd.arg_bool('--pinned', help='''
        Only show pinned packages. See also pin, unpin.''')

    # outdated
    cmd = cli.subcommand('outdated', cli_outdated, aliases=['old'])
    cmd.arg_bool('-f', '--force', help='''
        Ignore cache to request latest online version (usually not needed)''')
    cmd.arg_bool('-a', '--all', help='''
        Include all dependencies while checking for outdated versions''')
    cmd.arg_bool('-v', '--verbose', dest='unchanged', help='''
        List all packages in output, even they are up-to-date''')

    # upgrade
    cmd = cli.subcommand('upgrade', cli_upgrade, aliases=['update', 'up'])
    cmd.arg('packages', nargs='*', help='Brew package name')
    cmd.arg_bool('-k', '--keep', help='Do not remove outdated versions')
    cmd.arg_bool('-f', '--force', help='''
        Ignore cache to request latest online version (usually not needed)''')
    cmd.arg_bool('-n', '--dry-run', dest='dry', help='''
        Show what would be upgraded without doing anything''')
    cmd.arg_bool('-a', '--all', help='''
        Upgrade all dependencies regardless of primary package upgrade''')
    cmd.arg_bool('--pinned', help='Include pinned packages in upgrade')
    cmd.arg_bool('--no-dependencies', help='''
        Do not upgrade dependencies (overridden by --all)''')
    cmd.arg('-arch', help='''Manually set platform architecture
        (e.g. 'arm64_sequoia' (brew), 'arm64|darwin|macOS 15' (ghcr))''')

    # deps
    cmd = cli.subcommand('deps', cli_deps)
    cmd.arg('packages', nargs='*', help='Brew package name')
    cmd.arg('-depth', type=int, help='Limit tree to N levels (only --tree)')
    grp = cmd.xor_group()
    grp.arg_bool('--tree', help='Print dependencies as structured tree')
    grp.arg_bool('--dot', help='''
        Text-based graph description in DOT format (pipe to "|pbcopy")''')
    grp.arg_bool('--leaves', help='''
        Show only dependencies with no subdependencies''')

    # uses
    cmd = cli.subcommand('uses', cli_uses)
    cmd.arg('packages', nargs='*', help='Brew package name')
    cmd.arg('-depth', type=int, help='Limit tree to N levels (only --tree)')
    cmd.arg_bool('--missing', help='''
        Only list packages that are not currently installed''')
    grp = cmd.xor_group()
    grp.arg_bool('--tree', help='Print dependencies as structured tree')
    grp.arg_bool('--dot', help='''
        Text-based graph description in DOT format (pipe to "|pbcopy")''')
    grp.arg_bool('--leaves', help='Show only top-most uses, no intermediates')

    # leaves
    cmd = cli.subcommand('leaves', cli_leaves)
    cmd.arg_bool('-1', help='''
        Force output to be one entry per line.
        This is the default when output is not to a terminal.''')

    # missing
    cmd = cli.subcommand('missing', cli_missing)
    cmd.arg('packages', nargs='*', help='Brew package name')
    cmd.arg_bool('--no-dependencies', help='Do not print dependencies')
    cmd.arg_bool('-1', help='''
        Force output to be one entry per line.
        This is the default when output is not to a terminal.''')

    # install
    cmd = cli.subcommand('install', cli_install, aliases=['add'])
    cmd.arg('packages', nargs='+', help='Brew package name')
    cmd.arg_bool('-f', '--force', help='Install even if already installed')
    cmd.arg_bool('-n', '--dry-run', dest='dry', help='''
        Show what would be installed, but do not actually install anything''')
    cmd.arg_bool('--no-dependencies', help='Do not install dependencies')
    cmd.arg_bool('--skip-link', help='Install but skip linking to opt')
    cmd.arg('--binaries', action=BooleanOptionalAction, help='''
        Enable/disable linking of helper executables (default: enabled,
        see config.ini)''')
    cmd.arg('-arch', help='''Manually set platform architecture
        (e.g. 'arm64_sequoia' (brew), 'arm64|darwin|macOS 15' (ghcr))''')

    # uninstall
    cmd = cli.subcommand('uninstall', cli_uninstall, aliases=['remove', 'rm'])
    cmd.arg('packages', nargs='+', help='Brew package name')
    cmd.arg_bool('-y', '--yes', help='Do not ask for confirmation')
    cmd.arg_bool('-f', '--force', help='''
        Remove package even if it is a direct dependency of another package''')
    cmd.arg_bool('-n', '--dry-run', dest='dry', help='''
        List packages which would be uninstalled, without actually removing''')
    cmd.arg_bool('--leaves', help='''
        Print top-most dependencies instead of direct dependencies''')
    cmd.arg_bool('--no-dependencies', help='''
        Do not uninstall any of the dependencies of package''')
    cmd.arg('--ignore', nargs='*', default=[], help='''
        Treat IGNORE packages as if they are not installed. Will remove all
        dependencies which (after uninstall) are used exclusively by IGNORE.
        This will remove more packages than --force.''')

    # link
    cmd = cli.subcommand('link', cli_link, aliases=['ln'])
    cmd.arg('package', help='Brew package name')
    cmd.arg('version', nargs='?', help='''
        Optional if there is only a single version installed''')
    cmd.arg_bool('-f', '--force', help='Allow keg-only packages to be linked')
    cmd.arg_bool('-n', '--dry-run', dest='dry', help='''
        List files which would be linked without actually linking''')
    grp = cmd.xor_group()
    grp.arg_bool('--bin', help='Only link binaries, ignore opt-link')
    grp.arg_bool('--no-bin', help='Only link opt-link, ignore binaries')

    # unlink
    cmd = cli.subcommand('unlink', cli_unlink)
    cmd.arg('package', help='Brew package name')
    cmd.arg_bool('-n', '--dry-run', dest='dry', help='''
        List files which would be unlinked without actually unlinking''')
    cmd.arg_bool('--bin', help='Unlink binary but keep opt link active')

    # switch
    cmd = cli.subcommand('switch', cli_switch)
    cmd.arg('package', help='Brew package name')
    cmd.arg('version', nargs='?', help='Package version')  # convenience omit

    # toggle
    cmd = cli.subcommand('toggle', cli_toggle)
    cmd.arg('package', help='Brew package name')

    # pin
    cmd = cli.subcommand('pin', cli_pin)
    cmd.arg('packages', nargs='+', help='Brew package name')

    # unpin
    cmd = cli.subcommand('unpin', cli_unpin)
    cmd.arg('packages', nargs='+', help='Brew package name')

    # cleanup
    cmd = cli.subcommand('cleanup', cli_cleanup, aliases=['clean'])
    cmd.arg('packages', nargs='*', help='Brew package name')
    cmd.arg('--prune', type=int, help='''
        Remove all cache files and downloads older than specified days''')
    cmd.arg_bool('-n', '--dry-run', dest='dry', help='''
        Show what would be removed, but do not actually remove anything''')

    # export
    cmd = cli.subcommand('export', cli_export)
    cmd.arg('binaries', nargs='+', help='Binary files to be exported')
    cmd.arg('outdir', help='Export output directory')
    cmd.arg_bool('-f', '--force', help='Overwrite existing files in outdir')

    return cli.parse()


# -----------------------------------
#  Cli Helper
# -----------------------------------

class CliQuickArg(ArgsContainer):
    def arg(self, *args: Any, **kwargs: Any) -> Action:
        return self.add_argument(*args, **kwargs)

    def arg_bool(self, *args: Any, **kwargs: Any) -> Action:
        return self.add_argument(*args, **kwargs, action='store_true')

    def xor_group(self, **kwargs: Any) -> 'CliXorGroup':
        group = CliXorGroup(self, **kwargs)
        self._mutually_exclusive_groups.append(group)
        return group


class CliXorGroup(ArgsXorGroup, CliQuickArg):
    pass


class Cli(ArgumentParser, CliQuickArg):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.set_defaults(func=lambda _: self.print_help(sys.stdout))

    def subcommand(
        self, name: str, fn: 'Callable[[ArgParams], None]|None',
        *args: Any, meta: str = 'command', **kwargs: Any
    ) -> 'Cli':
        if not hasattr(self, 'sub_parser'):
            self.sub_parser = self.add_subparsers(metavar=meta, dest=meta)

        if fn:
            desc = fn.__doc__ or ''
            cmd = self.sub_parser.add_parser(
                name, *args, help=desc, description=desc.strip(), **kwargs)
            cmd.set_defaults(func=fn)
        else:
            cmd = self.sub_parser.add_parser(name, *args, **kwargs)
            # cmd.set_defaults(func=lambda _: cmd.print_help())
        return cmd

    def parse(self) -> ArgParams:
        return self.parse_args()


# -----------------------------------
#  System configuration
# -----------------------------------

class Arch:
    BREW = ''
    GHCR = ''

    IS_MAC = True  # no support for linux (yet?)
    IS_ARM = False
    OS_VER = '0'
    OS_NAME = 'xxx'
    ALL_OS = {
        'yosemite': '10.10',
        'el_capitan': '10.11',
        'sierra': '10.12',
        'high_sierra': '10.13',
        'mojave': '10.14',
        'catalina': '10.15',
        'big_sur': '11',
        'monterey': '12',
        'ventura': '13',
        'sonoma': '14',
        'sequoia': '15',
        'tahoe': '26',
    }

    @staticmethod
    def detect(args: ArgParams) -> None:
        Arch.IS_ARM = platform.machine() == 'arm64'
        Arch.OS_VER = Arch.macOSVersion()
        Arch.OS_NAME = {v: k for k, v in Arch.ALL_OS.items()}[Arch.OS_VER]
        if hasattr(args, 'arch') and args.arch:
            Arch.BREW = args.arch
            Arch.GHCR = args.arch
            return
        if not Arch.BREW:
            prefix = 'arm64_' if Arch.IS_ARM else ''  # arm64_tahoe OR tahoe
            Arch.BREW = prefix + Arch.OS_NAME
        if not Arch.GHCR:
            cpu = 'arm64' if Arch.IS_ARM else 'amd64'
            os_type = 'darwin' if Arch.IS_MAC else 'linux'
            Arch.GHCR = f'{cpu}|{os_type}|macOS {Arch.OS_VER}'

    @staticmethod
    def macOSVersion() -> str:
        major, minor, *_ = platform.mac_ver()[0].split('.')
        return ('10.' + minor) if major == '10' else major

    _SOFTWARE_VERSIONS = {}  # type: dict[str, list[int]]

    @staticmethod
    def getClangBuildVersion() -> list[int]:
        return Arch._SOFTWARE_VERSIONS.get('clang') or \
            Arch._SOFTWARE_VERSIONS.setdefault('clang', Bash.getVersion(
                ['clang', '--version'], r'clang-([\d.]+)'))

    @staticmethod
    def getGccVersion() -> list[int]:
        return Arch._SOFTWARE_VERSIONS.get('gcc') or \
            Arch._SOFTWARE_VERSIONS.setdefault('gcc', Bash.getVersion(
                ['gcc', '-v'], r'gcc version ([\d.]+)'))

    @staticmethod
    def hasXcodeVer(version: str) -> bool:
        currentVer = Arch._SOFTWARE_VERSIONS.get('xcode') or \
            Arch._SOFTWARE_VERSIONS.setdefault('xcode', Bash.getVersion(
                ['xcodebuild', '-version'], r'Xcode ([\d.]+)'))
        return currentVer >= [int(x) for x in version.split('.')]


# -----------------------------------
#  Config
# -----------------------------------

class Config:
    class Install(NamedTuple):
        LINK_BIN_PRIM: bool
        LINK_BIN_DEPS: bool

    class Cleanup(NamedTuple):
        DOWNLOAD: int
        CACHE: int
        AUTH: int

    INSTALL: Install
    CLEANUP: Cleanup

    @staticmethod
    def load(fname: str) -> None:
        if not os.path.exists(fname):
            with open(fname, 'w') as fp:
                fp.write('''
[install]
; whether install should link binaries of main package (user-installed)
link_bin_primary = yes  ; default: yes
; whether install should link binaries of dependencies
link_bin_dependency = no  ; default: no

[cleanup]
; unit: s|m|h|d (secs, mins, hours, days)
download = 21d  ; default: 21d
cache = 5d  ; default: 5d
auth = 365d  ; default: 365d
''')
        ini = IniFile(inline_comment_prefixes=(';', '#'))
        ini.read(fname)

        def timed(value: str) -> int:
            unit = value[-1].lower()
            mul = {'s': 1, 'm': 60, 'h': 60 * 60, 'd': 24 * 60 * 60}.get(unit)
            if not mul:
                raise AttributeError(f'Unkown time unit "{value}" in config')
            return int(value[:-1]) * mul

        sec = ini['install']
        Config.INSTALL = Config.Install(
            LINK_BIN_PRIM=sec.getboolean('link_bin_primary', fallback=True),
            LINK_BIN_DEPS=sec.getboolean('link_bin_dependency', fallback=False)
        )
        sec = ini['cleanup']
        Config.CLEANUP = Config.Cleanup(
            DOWNLOAD=timed(sec.get('download', '21d')),
            CACHE=timed(sec.get('cache', '5d')),
            AUTH=timed(sec.get('auth', 'never')),
        )


# -----------------------------------
#  TreeDict
# -----------------------------------

class TreeDict:
    Keys = TypeVar('Keys', set[str], list[str])

    def __init__(self) -> None:
        self.direct = {}  # type: dict[str, set[str]]
        self._leaves = {}  # type: dict[str, set[str]]
        self._all = {}  # type: dict[str, set[str]]

    def __iter__(self) -> Iterator[str]:
        return iter(self.direct)

    def inverse(self) -> 'TreeDict':
        ''' Copy values to a new tree where keys and values are flipped '''
        rv = TreeDict()
        for key, deps in self.direct.items():
            rv.direct.setdefault(key, set())
            for dep in deps:
                rv.direct.setdefault(dep, set()).add(key)
        return rv

    def getLeaves(self, key: str) -> set[str]:
        ''' Follow branches but return only dead-end values '''
        try:
            return self._leaves[key]
        except KeyError:
            rv = set(x for x in self.getAll(key) if not self.direct.get(x))
            self._leaves[key] = rv
            return self._leaves[key]

    def getAll(self, key: str) -> set[str]:
        ''' Follow branches and retrieve all values '''
        try:
            return self._all[key]
        except KeyError:
            deps = self.direct.get(key, set())
            rv = set()  # type: set[str]
            for x in deps:
                rv.update([x], self.getAll(x))
            self._all[key] = rv  # assign after recursive call finished
            return self._all[key]

    def unionAll(self, keys: Keys, *, inclInput: bool = True) -> set[str]:
        ''' Retrieve and join all values for all keys '''
        rv = set(x for key in keys for x in self.getAll(key))
        return rv.union(keys) if inclInput else rv

    def filterDifference(self, keys: Keys, other: set[str]) -> Keys:
        ''' Filter keys based on `if .direct.get(key).difference(other)` '''
        return type(keys)(key for key in keys
                          if self.direct.get(key, set()).difference(other))

    def filterIntersection(self, keys: Keys, other: set[str]) -> Keys:
        ''' Filter keys based on `if .direct.get(key).intersection(other)` '''
        return type(keys)(key for key in keys
                          if self.direct.get(key, set()).intersection(other))

    def missing(self, keys: Keys) -> Keys:
        ''' List of keys which are not present in `.direct` (keeps order) '''
        return type(keys)(key for key in keys if self.direct.get(key) is None)

    def directEnd(self) -> set[str]:
        ''' List of keys with with direct dead-ends '''
        return set(key for key, deps in self.direct.items() if not deps)

    def assertExist(self, keys: Keys, msg: str = 'unknown package:') -> None:
        ''' Print any `.missing(keys)` and exit with status code 1 '''
        if unknownKeys := self.missing(keys):
            Log.error(msg, ', '.join(unknownKeys))
            exit(1)

    def printFlat(
        self, keys: Keys, separator: str,
        *, leaves: bool = False, direct: bool = False,
    ) -> None:
        ''' format: "{pkg}{sep}{deps}". Priority: leaves, direct, all  '''
        for pkg in keys:
            if leaves:
                flat = self.getLeaves(pkg)
            elif direct:
                flat = self.direct[pkg]
            else:
                flat = self.getAll(pkg)
            print(pkg + separator + ', '.join(sorted(flat)))

    def printTree(
        self, keys: Keys, *, depth: int = 0, indent: int = 2, prefix: str = ''
    ) -> None:
        queue = [([], key) for key in keys]  # type:list[tuple[list[bool],str]]

        while queue:
            lvl, key = queue.pop(0)
            tx = (' ' * indent).join('│' if x else ' ' for x in lvl)
            if tx:
                conn = '├' if tx[-1] == '│' else '└'
                tx = tx[:-1] + conn + '─' * (indent - 1) + '╴'
            print(prefix + tx + key)

            if depth and depth > 0 and len(lvl) >= depth:
                continue

            subdeps = self.direct.get(key, set())
            if not subdeps:
                continue
            # prefer entries without dependencies -- then sort by name
            order = sorted((bool(self.direct.get(x)), x) for x in subdeps)
            new_items = [(lvl + [True], pkg) for (_, pkg) in order]
            # OR: sort by name only:
            # new_items = [(lvl + [True], x) for x in sorted(subdeps)]
            new_items[-1][0][-1] = False  # only last item has "no more"
            queue = new_items + queue

    def dotGraph(self, keys: Keys, *, reverse: bool = False) -> None:
        print('digraph G {')
        print('{rank=same;', ', '.join(f'"{x}"' for x in sorted(keys)),
              '[shape=box, style=dashed];}')
        for key in sorted(self.unionAll(keys)):
            for dep in sorted(self.direct.get(key, [])):
                if reverse:
                    print(f'"{dep}" -> "{key}";')
                else:
                    print(f'"{key}" -> "{dep}";')
        print('}')


# -----------------------------------
#  DependencyTree
# -----------------------------------

class DependencyTree:
    def __init__(self, forward: TreeDict) -> None:
        self.forward = forward
        self.reverse = forward.inverse()

    def obsolete(self, ignore: list[str]) -> set[str]:
        '''
        Packages that would become obsolete if `ignore` doesn't exist
        (incl. `ignore`)
        '''
        if not ignore:
            return set()
        # going DOWN the tree, get all dependencies of <ignore>
        allIgnored = self.forward.unionAll(ignore)
        children = allIgnored.difference(ignore)  # <ignore> can be nested!
        # going UP the tree and selecting branches not already ignored.
        # => look for children with other parents besides <ignore>
        multiParents = self.reverse.filterDifference(children, allIgnored)
        return allIgnored - multiParents

    def getMissing(self, constraint: TreeDict.Keys) -> set[str]:
        '''
        List of packages not currently installed
        (aka. appear in `.reverse` but not in `.forward`).
        Optionally: filter by `constraint` (any match within full tree).
        '''
        if constraint:
            return self.forward.unionAll(constraint).difference(self.forward)
        else:
            return set(self.reverse).difference(self.forward)


# -----------------------------------
#  LinkTarget
# -----------------------------------

class LinkTarget(NamedTuple):
    path: str
    target: str  # absolute path
    raw: str = ''  # relative target

    @staticmethod
    def read(filePath: str) -> 'LinkTarget|None':
        ''' Read a single symlink and populate with absolute paths '''
        if not os.path.islink(filePath):
            return None
        raw = os.readlink(filePath)
        real = os.path.realpath(os.path.join(os.path.dirname(filePath), raw))
        return LinkTarget(filePath, real, raw)

    @staticmethod
    def allInDir(path: str) -> 'list[LinkTarget]':
        return [x for f in os.scandir(path) if (x := LinkTarget.read(f.path))]


# -----------------------------------
#  LocalPackage
# -----------------------------------

class LocalPackage:
    '''
    Most properties are cached. Throw away your instance after (un-)install.
    '''

    def __init__(self, pkg: str) -> None:
        self.name = pkg
        self.path = Cellar.installPath(pkg)

    def __repr__(self) -> str:
        return f'<LocalPackage {self.name}>'

    def assertInstalled(self, msg: str = 'unknown package:') -> 'LocalPackage':
        '''If not installed: print error message and exit with status code 1'''
        if not self.installed:
            Log.error(msg, self.name)
            exit(1)
        return self

    def version(self, version: str) -> 'LocalPackageVersion':
        ''' Create new `LocalPackageVersion` instance '''
        return LocalPackageVersion(self, version)

    def anyVersion(self) -> 'LocalPackageVersion':
        ''' Return any of the installed versions (should be latest) '''
        assert self.installed, 'Only installed packages can call anyVersion()'
        return self.version(self.allVersions[-1])  # alphanumeric sort, latest

    def cleanup(self, *, dryRun: bool = False, quiet: bool = False) -> int:
        ''' Delete old, inactive versions and return size of savings '''
        if self.pinned:
            return 0
        savings = 0
        for ver in self.inactiveVersions:
            vpkg = self.version(ver)
            savings += File.remove(vpkg.path, dryRun=dryRun, quiet=quiet)
        return savings

    # Version properties on any version

    @cached_property
    def homepageUrl(self) -> 'str|None':
        ''' Extract homepage url from ruby file '''
        version = self.activeVersion or ([None] + self.allVersions)[-1]
        if version:
            return self.version(version).homepageUrl
        return None

    # Versions

    @cached_property
    def activeVersion(self) -> 'str|None':
        ''' Returns currently active version (if opt-link is set) '''
        return os.path.basename(self.optLink.target) if self.optLink else None

    @cached_property
    def allVersions(self) -> list[str]:
        ''' All installed versions '''
        rv = []
        if os.path.isdir(self.path):
            for ver in sorted(os.listdir(self.path)):
                if os.path.isdir(os.path.join(self.path, ver, '.brew')):
                    rv.append(ver)
        return rv

    @cached_property
    def installed(self) -> bool:
        ''' Returns `True` if at least one version is installed '''
        return len(self.allVersions) > 0

    @cached_property
    def inactiveVersions(self) -> list[str]:
        ''' Versions which are currently not active (not opt-linked) '''
        return [x for x in self.allVersions if x != self.activeVersion]

    # Custom config files

    @cached_property
    def pinned(self) -> bool:
        ''' Returns `True` if `.pinned` file exists '''
        return os.path.exists(os.path.join(self.path, '.pinned'))

    def pin(self, flag: bool) -> bool:
        ''' Create or delete `.pinned` file. Returns `False` if no change. '''
        assert os.path.isdir(self.path), 'Package must be installed to (un)pin'
        if changes := flag ^ self.pinned:
            del self.pinned  # clear cached_property

            if flag:
                File.touch(os.path.join(self.path, '.pinned'))
            else:
                os.remove(os.path.join(self.path, '.pinned'))
        return changes

    @cached_property
    def primary(self) -> bool:
        ''' Returns `False` if package was installed (only) as a dependency '''
        return os.path.exists(os.path.join(self.path, '.primary'))

    def setPrimary(self, flag: bool) -> None:
        ''' Create `.primary` (main pkg) or `.secondary` (dependency) file '''
        fname = os.path.join(self.path, '.primary' if flag else '.secondary')
        if flag:
            self.__dict__.pop('primary', None)  # clear cached_property
        File.touch(fname)

    # Symlink processing

    @cached_property
    def optLink(self) -> 'LinkTarget|None':
        ''' Read `@/opt/<pkg>` link. `None` if non-exist or not link to pkg '''
        # TODO: should opt-links have "@version" suffix or not?
        #       if no, fix-dylib needs adjustments
        lnk = LinkTarget.read(os.path.join(Cellar.OPT, self.name))
        if lnk and not lnk.target.startswith(self.path + '/'):
            return None
        return lnk

    @cached_property
    def binLinks(self) -> list[LinkTarget]:
        ''' List of `@/bin/...` links that match `<pkg>` destination '''
        return [lnk for lnk in Cellar.allBinLinks()
                if lnk.target.startswith(self.path + '/')]

    def unlink(
        self, *, unlinkOpt: bool, unlinkBin: bool,
        dryRun: bool = False, quiet: bool = False,
    ) -> list[LinkTarget]:
        ''' remove symlinks `@/opt/<pkg>` and `@/bin/...` matching target '''
        rv = []
        if unlinkBin:
            rv += self.binLinks

        if unlinkOpt:
            rv += filter(None, [self.optLink])

        for lnk in rv:
            if not quiet:
                Log.info(f'  unlink {Cellar.shortPath(lnk.path)} -> {lnk.raw}')
            if not dryRun:
                os.remove(lnk.path)

        if not dryRun:
            self._resetCachedProperty(optLink=unlinkOpt, binLink=unlinkBin)
        return rv

    def _resetCachedProperty(self, *, optLink: bool, binLink: bool) -> None:
        ''' clear cached_property '''
        if optLink:
            self.__dict__.pop('optLink', None)
            self.__dict__.pop('activeVersion', None)
            self.__dict__.pop('inactiveVersions', None)
        if binLink:
            self.__dict__.pop('binLinks', None)


# -----------------------------------
#  LocalPackageVersion
# -----------------------------------

class LocalPackageVersion:
    '''
    Most properties are cached. Throw away your instance after (un-)install.
    '''

    def __init__(self, pkg: LocalPackage, version: str) -> None:
        assert version, 'version is required'
        self.pkg = pkg
        self.version = version
        self.path = os.path.join(pkg.path, version)

    def __repr__(self) -> str:
        return f'<LocalPackageVersion {self.pkg.name} ({self.version})>'

    @cached_property
    def installed(self) -> bool:
        ''' Returns `True` if version is installed (`.brew` dir exists) '''
        return os.path.isdir(os.path.join(self.path, '.brew'))

    # Ruby file processing

    @cached_property
    def rubyPath(self) -> str:
        ''' Returns `@/Cellar/<pkg>/<version>/.brew/<pkg>.rb` '''
        return os.path.join(self.path, '.brew', self.pkg.name + '.rb')

    @cached_property
    def homepageUrl(self) -> 'str|None':
        ''' Extract homepage url from ruby file '''
        return RubyParser(self.rubyPath).parseHomepageUrl()

    @cached_property
    def dependencies(self) -> set[str]:
        ''' Extract dependencies from ruby file '''
        return RubyParser(self.rubyPath).parse().dependencies

    @cached_property
    def isKegOnly(self) -> bool:
        ''' Parse ruby file to check if package is keg-only '''
        return RubyParser(self.rubyPath).parseKegOnly()

    # Symlink processing

    @cached_property
    def _gatherBinaries(self) -> list[str]:
        ''' Binary paths in `@/Cellar/<pkg>/<version>/bin/...` '''
        path = os.path.join(self.path, 'bin')
        if os.path.isdir(path):
            return [x.path for x in os.scandir(path) if os.access(x, os.X_OK)]
        return []

    def link(
        self, *, linkOpt: bool, linkBin: bool,
        dryRun: bool = False, quiet: bool = False,
    ) -> None:
        ''' create symlinks `@/opt/<pkg>` and `@/bin/...` matching target '''
        if not self.installed:
            raise RuntimeError('Package not installed')

        queue = []
        optLinkPath = os.path.join(Cellar.OPT, self.pkg.name)

        if linkOpt:
            queue.append(LinkTarget(optLinkPath, self.path + '/'))

        for exePath in self._gatherBinaries if linkBin else []:
            # dynamic link on opt instead of direct
            dynLink = exePath.replace(self.path, optLinkPath, 1)
            queue.append(LinkTarget(
                os.path.join(Cellar.BIN, os.path.basename(exePath)), dynLink))

        for link in queue:
            relTgt = os.path.relpath(link.target, os.path.dirname(link.path))
            short = Cellar.shortPath(link.path)
            if os.path.islink(link.path) or os.path.exists(link.path):
                Log.warn(f'skip already existing link: {short}', summary=True)
            else:
                if not quiet:
                    Log.info(f'  link {short} -> {relTgt}')
                if not dryRun:
                    os.symlink(relTgt, link.path)

        if not dryRun:
            self.pkg._resetCachedProperty(optLink=linkOpt, binLink=linkBin)

    # Custom config files

    def setDigest(self, digest: str) -> None:
        ''' Copy digest of tar file into install dir '''
        with open(os.path.join(self.path, '.brew', 'digest'), 'w') as fp:
            fp.write(digest)

    # Post-install fix

    def fix(self) -> None:
        ''' Re-link dylibs and fix time of symlinks '''
        if not self.installed:
            Log.error('not a brew-package directory', self.path, summary=True)
            return

        Fixer.run(self.path)


# -----------------------------------
#  Remote logic
# -----------------------------------

class Brew:
    @staticmethod
    def _ghcrAuth(pkg: str, *, force: bool = False) -> str:
        return ApiGhcr.auth(pkg, force=force)['token']  # should never force

    class PackageManifest(NamedTuple):
        version: str
        digest: Optional[str]
        dependencies: Optional[list[str]]
        platforms: list[str]
        homepage: str

    @staticmethod
    def info(pkg: str, *, force: bool = False) -> PackageManifest:
        arch = Arch.BREW
        Log.debug('[DEBUG] query Brew.sh manifest for', pkg, '...')
        manifest = ApiBrew.manifest(pkg, force=force)
        targets = manifest['bottle']['stable']['files']
        if arch not in targets and 'all' in targets:
            arch = 'all'
        return Brew.PackageManifest(
            version=manifest['versions']['stable'],
            digest=targets[arch]['sha256'] if arch in targets else None,
            dependencies=manifest['dependencies'],
            platforms=list(targets.keys()),
            homepage=manifest['homepage'],
        )

    @staticmethod
    def ghcrInfo(pkg: str, version: str, *, force: bool = False) \
            -> PackageManifest:
        arch = Arch.GHCR
        Log.debug('[DEBUG] query ghcr manifest for', pkg, '...')
        auth = Brew._ghcrAuth(pkg)
        manifest = ApiGhcr.manifest(auth, pkg, version, force=force)

        digest = None
        dependencies = None
        platforms = []

        for target in manifest['manifests']:
            pl = target['platform']
            pl_str = '{}|{}|{}'.format(
                pl['architecture'], pl['os'], pl['os.version'])
            platforms.append(pl_str)
            if not digest and pl_str.startswith(arch):
                digest = target['annotations']['sh.brew.bottle.digest']
                data = target['annotations']['sh.brew.tab']
                dependencies = [
                    x['full_name'] + '|' + x['version']
                    for x in json.loads(data)['runtime_dependencies']]

        return Brew.PackageManifest(
            version=version,
            digest=digest,
            dependencies=dependencies,
            platforms=platforms,
            homepage='',
        )

    @staticmethod
    def ghcrTags(pkg: str, *, force: bool = False) -> list[str]:
        Log.debug('[DEBUG] query ghcr tags for', pkg, '...')
        auth = Brew._ghcrAuth(pkg)
        return ApiGhcr.tags(auth, pkg, force=force)['tags']

    @staticmethod
    def downloadBottle(
        pkg: str, version: str, digest: str,
        *, askOverwrite: bool = False, dryRun: bool = False
    ) -> str:
        assert digest, 'digest is required for download'
        fname = Cellar.downloadPath(pkg, version)
        # reuse already downloaded tar
        if os.path.isfile(fname):
            if File.sha256(fname) == digest:
                Log.main('skip already downloaded', pkg, version, count=True)
                return fname
            elif askOverwrite:
                Log.warn(f'file "{fname}" already exists')
                if not Utils.ask('Do you want to overwrite it?', 'n'):
                    Log.info('abort.')
                    return fname
            else:
                Log.warn('sha256 mismatch. Ignore local file and re-download.')

        if dryRun:
            Log.main('would download', pkg, version, count=True)
        else:
            Log.main('download', pkg, version, count=True)
            auth = Brew._ghcrAuth(pkg)
            os.rename(ApiGhcr.blob(auth, pkg, digest), fname)
        return fname


# -----------------------------------
#  Local logic
# -----------------------------------

class Cellar:
    ROOT = Env.CELLAR_PATH
    BIN = os.path.join(ROOT, 'bin')
    CACHE = os.path.join(ROOT, 'cache')
    CELLAR = os.path.join(ROOT, 'Cellar')
    DOWNLOAD = os.path.join(ROOT, 'download')
    OPT = os.path.join(ROOT, 'opt')

    @staticmethod
    def init() -> None:
        ''' Check if ENV variable is set and create directories '''
        if not Cellar.ROOT:
            Log.error('env BREW_PY_CELLAR not set')
            exit(42)

        for x in (Cellar.BIN, Cellar.CACHE, Cellar.CELLAR, Cellar.DOWNLOAD,
                  Cellar.OPT):
            os.makedirs(x, exist_ok=True)

        Config.load(os.path.join(Cellar.ROOT, 'config.ini'))  # after makedirs
        Cellar.cleanup(quiet=True)  # after Config.load()

    @staticmethod
    def cleanup(
        maxAgeDays: 'int|None' = None, *,
        dryRun: bool = False, quiet: bool = False,
    ) -> int:
        ''' Delete outdated files in cache and download. '''
        savings = 0

        if maxAgeDays is not None:
            maxAgeDays *= 24 * 60 * 60  # days
            if maxAgeDays == 0:
                maxAgeDays = 1

        for file in os.scandir(Cellar.CACHE):
            if file.name == '_auth-token.json':
                # TODO: test how long the token is valid
                maxage = Config.CLEANUP.AUTH
            else:
                maxage = maxAgeDays or Config.CLEANUP.CACHE

            if File.isOutdated(file.path, maxage):
                savings += File.remove(file.path, dryRun=dryRun, quiet=quiet)

        maxage = maxAgeDays or Config.CLEANUP.DOWNLOAD
        for file in os.scandir(Cellar.DOWNLOAD):
            if File.isOutdated(file.path, maxage):
                savings += File.remove(file.path, dryRun=dryRun, quiet=quiet)
        return savings

    # Paths

    @staticmethod
    def downloadPath(pkg: str, version: str) -> str:
        ''' Returns `@/download/<pkg>-<version>.tar.gz` '''
        return os.path.join(Cellar.DOWNLOAD, f'{pkg}-{version}.tar.gz')

    @staticmethod
    def installPath(pkg: str) -> str:
        ''' Returns `@/Cellar/<pkg>` '''
        return os.path.join(Cellar.CELLAR, pkg)

    # Version handling

    @staticmethod
    def infoAll(filterPkg: list[str] = [], *, assertInstalled: bool = False) \
            -> list[LocalPackage]:
        ''' List all installed packages (already checked for `.installed`) '''
        pkgs = filterPkg if filterPkg else sorted(os.listdir(Cellar.CELLAR))
        infos = [x for pkg in pkgs if (x := LocalPackage(pkg)).installed]
        # hard-fail if asserting for installed
        if assertInstalled and filterPkg and len(pkgs) != len(infos):
            unkownPkgs = set(pkgs) - set(x.name for x in infos)
            Log.error('unknown package:', ', '.join(sorted(unkownPkgs)))
            exit(1)
        return infos

    @staticmethod
    def getDependencyTree() -> DependencyTree:
        ''' Returns dict object for dependency traversal '''
        forward = TreeDict()
        for pkg in Cellar.infoAll():  # must always go over all, no filters
            forward.direct[pkg.name] = set(
                dep
                for ver in pkg.allVersions
                for dep in pkg.version(ver).dependencies
            )
        return DependencyTree(forward)

    @staticmethod
    def allBinLinks() -> list[LinkTarget]:
        ''' List of all `@/bin/...` links '''
        return LinkTarget.allInDir(Cellar.BIN)

    @staticmethod
    def allOptLinks() -> list[LinkTarget]:
        ''' List of all `@/opt/...` links '''
        return LinkTarget.allInDir(Cellar.OPT)

    @staticmethod
    def shortPath(path: str) -> str:
        ''' Return truncated path (relative to `Cellar.ROOT`) '''
        # if OPT and BIN will be stored separately, check each path separately
        return os.path.relpath(path, Cellar.ROOT)


# -----------------------------------
#  TarPackage
# -----------------------------------

class TarPackage:
    class PkgVer(NamedTuple):
        package: str
        version: str

    def __init__(self, fname: str) -> None:
        self.fname = fname

    def extract(self, *, dryRun: bool = False) -> 'PkgVer|None':
        ''' Extract tar file into `@/Cellar/...` '''
        shortPath = Cellar.shortPath(self.fname)
        if shortPath.startswith('..'):  # if path outside of cellar
            shortPath = os.path.basename(self.fname)

        if not os.path.isfile(self.fname):
            if dryRun:
                Log.main('would install', shortPath, count=True)
            return None

        pkg, version = None, None
        with openTarfile(self.fname, 'r') as tar:
            subset = []
            for x in tar:
                if self.filter(x, Cellar.CELLAR):
                    subset.append(x)
                    if not pkg and x.isdir() and x.path.endswith('/.brew'):
                        pkg, version, *_ = x.path.split('/')
                        if dryRun:
                            break
                else:
                    Log.error(f'prohibited tar entry "{x.path}" in', shortPath,
                              summary=True)

            if pkg is None or version is None:
                Log.error('".brew" dir missing. Failed to extract', shortPath,
                          summary=True, count=True)
                return None

            Log.main('would install' if dryRun else 'install', shortPath,
                     f'({pkg} {version})', count=True)
            if not dryRun:
                tar.extractall(Cellar.CELLAR, subset)
        return TarPackage.PkgVer(pkg, version)

    # Copied from Python 3.12 tarfile _get_filtered_attrs
    def filter(self, member: TarInfo, dest_path: str) -> bool:
        '''Remove dangerous tar elements (relative dir escape & permissions)'''
        dest_path = os.path.realpath(dest_path)
        # Strip leading / (tar's directory separator) from filenames.
        # Include os.sep (target OS directory separator) as well.
        if member.name.startswith(('/', os.sep)):
            Log.warn('reject absolute path', member.name, summary=True)
            return False
        # Ensure we stay in the destination
        target_path = os.path.realpath(os.path.join(dest_path, member.name))
        if os.path.commonpath([target_path, dest_path]) != dest_path:
            Log.warn('path breaks cellar bounds', member.name, summary=True)
            return False
        # Limit permissions (no high bits, and go-w)
        if member.mode is not None:
            # Strip high bits & group/other write bits
            member.mode &= 0o755
            # For data, handle permissions & file types
            if member.isreg() or member.islnk():
                if not member.mode & 0o100:
                    # Clear executable bits if not executable by user
                    member.mode &= ~0o111
                # Ensure owner can read & write
                member.mode |= 0o600
            elif member.isdir() or member.issym():
                # Ignore mode for directories & symlinks
                pass
            else:
                # Reject special files
                Log.warn('reject special files', summary=True)
                return False

        # Check link destination for 'data'
        if member.islnk() or member.issym():
            if os.path.isabs(member.linkname):
                Log.warn('reject symlink absolute path', member.linkname,
                         summary=True)
                return False
            normalized = os.path.normpath(member.linkname)
            if normalized != member.linkname:
                member.linkname = normalized
            if member.issym():
                target_path = os.path.join(
                    dest_path, os.path.dirname(member.name), member.linkname)
            else:
                target_path = os.path.join(dest_path, member.linkname)
            target_path = os.path.realpath(target_path)
            if os.path.commonpath([target_path, dest_path]) != dest_path:
                Log.warn('symlink breaks cellar bounds', member.linkname,
                         summary=True)
                return False
        return True


# -----------------------------------
#  InstallQueue
# -----------------------------------

class InstallQueue:
    class Item(NamedTuple):
        package: str
        version: str
        digest: str

    def __init__(self, *, dryRun: bool, force: bool) -> None:
        self.dryRun = dryRun
        self.force = force
        self._primary = set()  # type: set[str]  # pkg
        self._missingDigest = []  # type: list[str]  # pkg
        self.downloadQueue = []  # type: list[InstallQueue.Item]
        self.installQueue = []  # type: list[str]  # tar file path
        self.finished = []  # type: list[tuple[str, str]]  # [(pkg, version)]

    def init(self, pkgOrFile: str, *, recursive: bool, quiet: bool = False) \
            -> None:
        ''' Auto-detect input type and install from tar-file or brew online '''
        if os.path.isfile(pkgOrFile) and pkgOrFile.endswith('.tar.gz'):
            shortName = os.path.basename(pkgOrFile)
            Log.info(f'==> Install tar file ({shortName}) ...')
            self.installQueue.append(pkgOrFile)
            self._primary.add(pkgOrFile)
        elif '/' in pkgOrFile:
            Log.error('package may not contain path-separator')
        elif recursive:
            Log.info(f'==> Gather dependencies for {pkgOrFile} ...')
            self.addRecursive(pkgOrFile, quiet=quiet)
        else:
            Log.info(f'==> Install {pkgOrFile} (ignoring dependencies) ...')
            bundle = Brew.info(pkgOrFile)
            self.add(pkgOrFile, bundle.version, bundle.digest, quiet=quiet)
            self._primary.add(pkgOrFile)

    def addRecursive(self, pkg: str, *, quiet: bool = False) -> None:
        ''' Recursive online search for dependencies '''
        self._primary.add(pkg)
        queue = [pkg]
        done = set(self._missingDigest).union(
            x.package for x in self.downloadQueue)
        while queue:
            pkg = queue.pop(0)
            if pkg not in done:
                done.add(pkg)
                bundle = Brew.info(pkg)
                queue.extend(bundle.dependencies or [])
                self.add(pkg, bundle.version, bundle.digest)

    def add(
        self, pkg: str, version: str, digest: 'str|None', *,
        quiet: bool = False,
    ) -> None:
        ''' Check if specific version exists and add to download queue '''
        # skip if a specific version already exists
        if not self.force and version in LocalPackage(pkg).allVersions:
            # TODO: print already installed?
            return
        if not quiet:
            Log.info('  -', pkg)
        if not digest:
            self._missingDigest.append(pkg)
        else:
            self.downloadQueue.append(InstallQueue.Item(pkg, version, digest))

    def validateQueue(self) -> None:
        ''' Check if any digest is missing. If so, fail with exit code 1 '''
        # if any digest couldn't be determined, we must fail whole queue
        if self._missingDigest:
            Log.error('missing platform "{}" in: {}'.format(
                Arch.BREW, ', '.join(self._missingDigest)))
            exit(1)

    def download(self) -> None:
        ''' Download all dependencies in normal order (depth-first) '''
        if not self.downloadQueue:
            return
        Log.info()
        Log.info('==> Download ...')
        Log.beginCounter(len(self.downloadQueue))
        for x in self.downloadQueue:
            self.installQueue.append(Brew.downloadBottle(
                x.package, x.version, x.digest, dryRun=self.dryRun))
        Log.endCounter()

    def install(
        self, *, skipLink: bool = True, linkExe: 'bool|None' = None,
        isUpgrade: bool = False,
    ) -> None:
        ''' Install all dependencies in reverse order (main package last) '''
        Log.info()
        Log.info('==> Install ...')
        if not self.installQueue:
            Log.info('nothing to install')
            return
        total = len(self.installQueue)
        Log.beginCounter(total)
        Log.beginErrorSummary()

        # flags
        linkPrim = Config.INSTALL.LINK_BIN_PRIM if linkExe is None else linkExe
        linkDeps = Config.INSTALL.LINK_BIN_DEPS if linkExe is None else linkExe

        # reverse to install main package last (allow re-install until success)
        for tar in reversed(self.installQueue):
            bundle = TarPackage(tar).extract(dryRun=self.dryRun)
            if not bundle:
                continue  # install error

            isPrimary = bundle.package in self._primary or tar in self._primary
            linkBin = linkPrim if isPrimary else linkDeps

            if self.dryRun:
                if not linkBin:
                    Log.info('will NOT link binaries')
                continue

            # post-install stuff
            pkg = LocalPackage(bundle.package)
            if not isUpgrade:
                pkg.setPrimary(isPrimary)

            vpkg = pkg.version(bundle.version)
            vpkg.setDigest(File.sha256(tar))
            vpkg.fix()  # relink dylibs

            self.finished.append((pkg.name, vpkg.version))

            if skipLink:
                continue

            if isUpgrade:
                # only switch to new version if old is linked already
                if pkg.optLink:
                    pkg.unlink(unlinkOpt=True, unlinkBin=False, quiet=True)
                    vpkg.link(linkOpt=True, linkBin=False)
                continue

            if vpkg.isKegOnly:
                linkBin = False
                Log.warn('keg-only, must link manually ({}, {})'.format(
                    pkg.name, vpkg.version), summary=True)

            pkg.unlink(unlinkOpt=True, unlinkBin=True)  # cleanup prev install
            vpkg.link(linkOpt=True, linkBin=linkBin)

        Log.endCounter()
        Log.dumpErrorSummary()


# -----------------------------------
#  Fixer
# -----------------------------------

class Fixer:
    @staticmethod
    def run(path: str) -> None:
        for base, dirs, files in os.walk(path):
            for file in files:
                fname = os.path.join(base, file)
                if os.path.islink(fname):
                    Fixer.symlink(fname)
                    continue

                if File.isMachO(fname):
                    Dylib(fname).fix()
                elif File.isBinary(fname):
                    pass  # skip other binary (.a, .class, .png, ...)
                else:
                    # replace all @@homebrew@@ placeholders
                    Fixer.inreplace(fname)

    @staticmethod
    def symlink(fname: str) -> None:
        ''' Fix time on symlink, copy time from target link '''
        # TODO: we could check if link is absolute, but untar already did that
        # fix date modified
        atime = os.path.getatime(fname)
        mtime = os.path.getmtime(fname)
        os.utime(fname, (atime, mtime), follow_symlinks=False)

    @staticmethod
    def inreplace(fname: str) -> None:
        # check if file contains any homebrew prefix placeholders
        matches = Fixer._read_placeholders_location(fname)
        if not matches:
            return

        Log.debug('  replace placeholders in', fname)
        # check that we dont miss any placeholder
        for pos, match in matches:
            if match not in Fixer.INREPLACE_DICT:
                Log.error('missed placeholder', match, 'in', fname,
                          summary=True)

        # if yes, replace all placeholders
        tmp_tgt = fname + '.brew-repl'
        Fixer._write_placeholders_replace(matches, fname, tmp_tgt)

        # replace original file and restore file flags
        shutil.copystat(fname, tmp_tgt)
        st = os.stat(fname)
        os.chown(tmp_tgt, st.st_uid, st.st_gid)
        os.rename(tmp_tgt, fname)

    PlaceholderMatches = list[tuple[int, bytes]]

    @staticmethod
    def _read_placeholders_location(fname: str) -> PlaceholderMatches:
        ''' Returns list of `(pos, b'@@PLACEHOLDER@@')` '''
        CHUNK_SIZE = 4096
        # file_size = 0
        needle = b'@@HOMEBREW_'
        rv = []
        with open(fname, 'rb') as fp:
            fp.seek(0)
            while True:
                chunk = fp.read(CHUNK_SIZE)
                if len(chunk) == 0:
                    # file_size = fp.tell()
                    break

                if needle not in chunk:
                    continue

                idx = chunk.index(needle)
                if idx > CHUNK_SIZE - 30:
                    fp.seek(-30, 1)  # relative to current pos
                    continue

                suffix = chunk[idx + 2:idx + 30]
                if b'@@' in suffix:
                    end = idx + 2 + suffix.index(b'@@') + 2
                    fp_idx = fp.tell() - len(chunk) + idx
                    rv.append((fp_idx, chunk[idx:end]))
                    fp.seek(- len(chunk) + end, 1)  # relative to current pos
                    continue

                fp.seek(- len(chunk) + idx + len(needle), 1)
        return rv

    @staticmethod
    def _write_placeholders_replace(
        matches: PlaceholderMatches, src: str, dst: str
    ) -> None:
        ''' Apply changes to new file by replacing placeholders with value '''
        CHUNK_SIZE = 4096
        # this is easier than adding a special case to read until EOF
        matches.append((99 ** 9, b''))
        prev = 0
        with open(src, 'rb') as fpr:
            with open(dst, 'wb') as fpw:
                for pos, match in matches:
                    while prev + CHUNK_SIZE < pos:
                        change = fpw.write(fpr.read(CHUNK_SIZE))
                        if change == 0:
                            return
                        prev += change
                    fpw.write(fpr.read(pos - prev))
                    fpr.seek(pos + len(match))
                    prev = fpr.tell()
                    fpw.write(Fixer.INREPLACE_DICT[match])

    INREPLACE_DICT = {
        b'@@HOMEBREW_PREFIX@@': Cellar.ROOT.encode('utf8'),
        b'@@HOMEBREW_CELLAR@@': Cellar.CELLAR.encode('utf8'),
        b'@@HOMEBREW_LIBRARY@@': Cellar.ROOT.encode('utf8') + b'/Library',
    }


# -----------------------------------
#  Dylib
# -----------------------------------

class Dylib:
    def __init__(self, path: str) -> None:
        self.path = path
        self.atime = os.path.getatime(path)
        self.mtime = os.path.getmtime(path)
        # dylib specific
        self.id = ''
        self.signed = False
        self.rpaths = []  # type: list[str]
        self.dylibs = []  # type: list[str]
        self._load()
        # remove system dylibs with absolute URLs
        self.dylibs = [x for x in self.dylibs if x.startswith('@')]

    def _load(self) -> None:
        ''' Run `otool` on file, parse output, write instance fields '''
        cmd = ''
        value = ''
        for line in Bash.otool(self.path) + ['Load command END']:
            line = line.strip()
            if line.startswith('Load command '):
                if cmd == 'LC_ID_DYLIB':
                    self.id = value
                elif cmd == 'LC_LOAD_DYLIB':
                    self.dylibs.append(value)
                elif cmd == 'LC_RPATH':
                    self.rpaths.append(value)
                elif cmd == 'LC_CODE_SIGNATURE':
                    self.signed = True
                # reset temporary variables
                cmd = ''
                value = ''
            elif line.startswith('cmd '):
                cmd = line[4:]
            elif line.startswith('path ') or line.startswith('name '):
                value = line[5:].split(' (offset ')[0]

    @cached_property
    def rpaths_expanded(self) -> list[str]:
        ''' Apply expand_path() on all `.rpaths` '''
        return [self.expand_path(x) for x in self.rpaths]

    def expand_path(self, rpath: str) -> str:
        ''' Replace `@@HOMEBREW_` placeholders and resolve `@loader_path` '''
        if rpath.startswith('@loader_path'):
            rpath = os.path.dirname(self.path) + rpath[12:]
        elif rpath.startswith('@@HOMEBREW_PREFIX@@'):
            rpath = Cellar.ROOT + rpath[19:]
        elif rpath.startswith('@@HOMEBREW_CELLAR@@'):
            rpath = Cellar.CELLAR + rpath[19:]

        assert rpath.startswith('/'), f'Missing replace for {rpath}'
        return os.path.abspath(rpath)

    def fix(self) -> None:
        ''' Rewrite dylib to use relative links (@loader_path only) '''
        # TLDR:
        # 1) otool -l <file>  // list all linked shared libraries
        # 2) install_name_tool -id X -delete_rpath Y ... -change Z ... <file>
        # 3) codesign --verify --force --sign - <file>  // resign with no sign
        args = []
        if self.id:
            new_id = '@loader_path/' + os.path.basename(self.id)
            if self.id != new_id:
                args.extend(['-id', new_id])

        for rpath in self.rpaths:
            args.extend(['-delete_rpath', rpath])

        for old, new in self._dylib_renames():
            args.extend(['-change', old, new])

        if args:
            Log.info('  fix dylib', Cellar.shortPath(self.path))
            Log.debug('    cmd:', args)
            Bash.install_name_tool(self.path, args)

            if self.signed:
                Log.debug('  codesign')
                Bash.codesign(self.path)
            # restore previous date-time
            os.utime(self.path, (self.atime, self.mtime))

    def _dylib_renames(self) -> list[tuple[str, str]]:
        ''' Iterate over all `.dylibs` and return rename changes to apply '''
        if not self.dylibs:
            return []

        parentDir = os.path.dirname(self.path)
        repl1 = parentDir.replace(Cellar.CELLAR, '@@HOMEBREW_CELLAR@@', 1)
        repl2 = parentDir.replace(Cellar.ROOT, '@@HOMEBREW_PREFIX@@', 1)
        assert repl1.startswith('@@HOMEBREW_CELLAR@@'), 'must be inside CELLAR'

        # check if opt-link points to the same package
        _, pkgName, pkgVer, *subpath = repl1.split('/')
        opt_prefix = f'@@HOMEBREW_PREFIX@@/opt/{pkgName}/'
        repl_same = opt_prefix + '/'.join(subpath)

        rv = []
        for oldRef in self.dylibs:
            newRef = ''

            if oldRef.startswith('@@HOMEBREW_CELLAR@@'):
                newRef = os.path.relpath(oldRef, repl1)

            elif oldRef.startswith('@@HOMEBREW_PREFIX@@'):
                if oldRef.startswith(opt_prefix):
                    newRef = os.path.relpath(oldRef, repl_same)
                else:
                    newRef = os.path.relpath(oldRef, repl2)

            elif oldRef.startswith('@rpath/'):
                assert self.rpaths, '@rpath is defined elsewhere?!'

                for rpath in self.rpaths_expanded:
                    try_rpath = oldRef.replace('@rpath', rpath)
                    if os.path.exists(try_rpath):
                        newRef = os.path.relpath(try_rpath, parentDir)
                        break

            elif oldRef.startswith('@loader_path/'):
                try_path = self.expand_path(oldRef)
                if os.path.exists(try_path):
                    newRef = os.path.relpath(try_path, parentDir)

            if not newRef or newRef.startswith('/'):
                Log.warn('could not resolve dylib link', oldRef, summary=True)
                continue

            newRef = '@loader_path/' + newRef
            if oldRef != newRef:
                rv.append((oldRef, newRef))
        return rv


# -----------------------------------
#  UninstallQueue
# -----------------------------------

class UninstallQueue:
    def __init__(self) -> None:
        # uses after uninstall (primary dependencies with multiple parents)
        self.warnings = {}  # type: dict[str, set[str]]  # {pkg: {deps}}
        # used by other packages (secondary dependencies with multiple parents)
        self.skips = {}  # type: dict[str, set[str]]  # {pkg: {deps}}
        # list of packages that will be removed
        self.uninstallQueue = []  # type: list[LocalPackage]

    def collect(
        self, deletePkgs: list[str], hiddenPkgs: list[str], *,
        leaves: bool, ignoreDependencies: bool,
    ) -> None:
        '''
        Try to uninstall all `deletePkgs`. Act as if `hiddenPkgs` don't exist.
        Any package that depends on another package (not in those two sets)
        will be skipped and remains on the system.
        '''
        depTree = Cellar.getDependencyTree()
        depTree.forward.assertExist(hiddenPkgs)

        for unknown in depTree.forward.missing(deletePkgs):
            Log.error('unknown package:', unknown)
            deletePkgs.remove(unknown)

        def getDeps(pkg: str) -> set[str]:
            if leaves:
                return depTree.reverse.getLeaves(pkg)
            else:
                return depTree.reverse.direct[pkg]

        def setWarnings(hidden: set[str]) -> None:
            self.warnings = {pkg: deps for pkg in deletePkgs
                             if (deps := getDeps(pkg) - hidden)}

        def setUninstallQueue(pkgs: list[str]) -> None:
            self.uninstallQueue = [LocalPackage(x) for x in pkgs]

        # user said "these aren't the packages you're looking for"
        activelyIgnored = depTree.obsolete(hiddenPkgs)

        if ignoreDependencies:
            setWarnings(activelyIgnored.union(deletePkgs))
            setUninstallQueue(deletePkgs)
            self.skips = {}
            return

        # ideally, we uninstall <deletePkgs> and all its dependencies
        rawUninstall = depTree.forward.unionAll(deletePkgs)

        # dont consider these, they will be gone (or are actively ignored)
        hidden = activelyIgnored.union(rawUninstall)

        # only secondary items can be skipped, primary are always removed
        secondary = rawUninstall.difference(deletePkgs)
        # skip a package if it has other, non-ignored, parents
        skipped = depTree.reverse.filterDifference(secondary, hidden)
        removed = rawUninstall.difference(skipped)

        # skip dependencies which were installed by user on request
        primary = set(x for x in removed if LocalPackage(x).primary)
        primary = primary.difference(deletePkgs)
        removed -= primary
        skipped |= primary

        # recursively ignore dependencies that rely on already ignored
        while deps := depTree.reverse.filterIntersection(removed, skipped):
            skipped.update(deps)
            removed.difference_update(deps)

        # remove any not-installed packages
        removed -= depTree.forward.missing(removed)

        setWarnings(hidden)
        setUninstallQueue(sorted(removed))
        irrelevant = removed.union(hiddenPkgs)
        self.skips = {pkg: getDeps(pkg) - irrelevant for pkg in skipped}

    def validateQueue(self) -> None:
        ''' Check for direct dependencies. If found, fail with exit code 1 '''
        if self.warnings:
            for pkg, deps in sorted(self.warnings.items()):
                Log.error(pkg, 'is a dependency of', ', '.join(sorted(deps)))
            exit(1)

    def printUninstallQueue(self) -> None:
        ''' Print list of `==> will remove X.` '''
        for pkg in self.uninstallQueue:
            Log.main(f'==> will remove {pkg.name}.')

    def printSkipped(self) -> None:
        ''' Print list of `skip X. used by: {deps}` '''
        for pkg, deps in sorted(self.skips.items()):
            if LocalPackage(pkg).primary:
                Log.warn(f'skip {pkg}. (primary install)')
            else:
                Log.warn(f'skip {pkg}. used by:', ', '.join(sorted(deps)))

    def uninstall(self, *, dryRun: bool) -> None:
        ''' Remove symlinks and package directories (or pretend to do) '''
        countPkgs = len(self.uninstallQueue)

        # delete links
        Log.info('==> Remove symlinks for', countPkgs, 'packages')
        countSym = 0
        for pkg in self.uninstallQueue:
            links = pkg.unlink(unlinkOpt=True, unlinkBin=True,
                               dryRun=dryRun, quiet=dryRun and Log.LEVEL <= 2)
            countSym += len(links)
        Log.main('Would remove' if dryRun else 'Removed', countSym, 'symlinks')

        # delete packages and links
        Log.info('==> Uninstall', countPkgs, 'packages')
        total_savings = 0
        for pkg in self.uninstallQueue:
            total_savings += File.remove(pkg.path, dryRun=dryRun)

        Log.info(Txt.freedDiskSpace(total_savings, dryRun=dryRun))

        if dryRun:
            print()
            print('The following packages will be removed:')
            Utils.printInColumns([x.name for x in self.uninstallQueue])
            if self.skips:
                print()
                print('The following packages will NOT be removed:')
                Utils.printInColumns(sorted(self.skips))


# -----------------------------------
#  RubyParser
# -----------------------------------

class RubyParser:
    PRINT_PARSE_ERRORS = True
    ASSERT_KNOWN_SYMBOLS = False
    IGNORE_RULES = False
    FAKE_INSTALLED = set()  # type: set[str] # simulate LocalPackage.installed

    IGNORED_TARGETS = set([':optional', ':build', ':test'])
    TARGET_SYMBOLS = IGNORED_TARGETS.union([':recommended'])
    # https://rubydoc.brew.sh/MacOSVersion.html#SYMBOLS-constant
    # MACOS_SYMBOLS = set([':' + x for x in Arch.ALL_OS])
    # https://rubydoc.brew.sh/RuboCop/Cask/Constants#ON_SYSTEM_METHODS-constant
    # https://rubydoc.brew.sh/Homebrew/SimulateSystem.html#arch_symbols-class_method
    # SYSTEM_SYMBOLS = set([':arm,', ':intel', ':arm64', ':x86_64'])
    # KNOWN_SYMBOLS = MACOS_SYMBOLS | SYSTEM_SYMBOLS | TARGET_SYMBOLS

    def __init__(self, path: str) -> None:
        self.invalidArch = []  # type: list[str]  # reasons why not supported
        self.path = path
        if not os.path.isfile(self.path):
            raise FileNotFoundError(path)

    def readlines(self) -> Iterator[str]:
        with open(self.path, 'r') as fp:
            for line in fp.readlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    yield line

    def parseHomepageUrl(self) -> 'str|None':
        ''' Extract homepage url '''
        for line in self.readlines():
            if line.startswith('homepage '):
                return line.split('"')[1]
        return None

    def parseKegOnly(self) -> bool:
        ''' Check if package is keg-only '''
        for line in self.readlines():
            if line == 'keg_only' or line.startswith('keg_only '):
                return True
        return False

    def parse(self) -> 'RubyParser':
        ''' Extract depends_on rules (updates `.invalidArch`) '''
        END = r'\s*(?:#|$)'  # \n or comment
        STR = r'"([^"]*)"'  # "foo"
        ACT = r'([^\s:]+:)'  # foo:
        SYM = r'(:[^\s:]+)'  # :foo
        ARR = r'\[([^\]]*)\]'  # [foo]
        TOK = fr'(?:{STR}|{SYM}|{ARR})'  # "str" | :sym | [arr]
        TGT = fr'(?:\s*=>\s*{TOK})?'  # OPTIONAL: => {TOK}
        # depends_on
        DEP = fr'(?:{STR}|{SYM}|{ACT}\s+{TOK})'  # "str" | :sym | act: {TOK}
        IF = r'(?:\s+if\s+(.*))?'  # OPTIONAL: if MacOS.version >= :catalina
        # uses_from_macos
        REQ = fr'(?:,\s+{ACT}\s+{SYM})?'  # OPTIONAL: , act: :sym  (with comma)

        rx_grp = re.compile(fr'^on_([^\s]*)\s*(.*)\s+do{END}')
        rx_dep = re.compile(fr'^depends_on\s+{DEP}{TGT}{IF}{END}')
        rx_use = re.compile(fr'^uses_from_macos\s+{STR}{TGT}{REQ}{END}')

        self.dependencies = set()  # type: set[str]
        context = [True]
        prev_classes = set()  # type: set[str]
        for line in self.readlines():
            if line.startswith('class '):
                prev_classes.add(line.split()[1])

            if line.startswith('on_'):
                if match := rx_grp.match(line):
                    flag = self._parse_block(*match.groups())
                    context.append(flag)
                else:
                    # ignore single outlier cvs.rb
                    if not line.startswith('on_macos { patches'):
                        self._err(line)

            elif line == 'end' or line.startswith('end '):
                if len(context) > 1:
                    context.pop()

            elif not self.IGNORE_RULES and not all(context):
                continue

            elif line.startswith('depends_on '):
                if match := rx_dep.match(line):
                    if self._parse_depends(*match.groups()):
                        self.dependencies.add(match.group(1))
                else:
                    # glibc seems to be the only formula with weird defs
                    # https://github.com/Homebrew/homebrew-core/blob/main/Formula/g/glibc%402.17.rb
                    if line.split()[1] not in prev_classes:
                        self._err(line)

            elif line.startswith('uses_from_macos '):
                if match := rx_use.match(line):
                    if not self._parse_uses(*match.groups()):
                        self.dependencies.add(match.group(1))
                else:
                    self._err(line)

        return self

    ##################################################
    # Helper methods
    ##################################################

    def _err(self, *msg: Any) -> None:
        if self.PRINT_PARSE_ERRORS:
            Log.warn('ruby parse err //', *msg, '--', self.path)

    def _unify_tok(self, string: str, sym: str, arr: str) -> list[str]:
        if string:
            return [string]
        if sym:
            return [sym]
        if arr:
            return [x.strip().strip('"') for x in arr.split(',')]
        return []

    def _is_ignored_target(self, args: list[str]) -> bool:
        ''' Returns `True` if target is :build or :test (unless debugging) '''
        if self.ASSERT_KNOWN_SYMBOLS:
            if unkown := set(args) - RubyParser.TARGET_SYMBOLS:
                self._err('unkown symbol', unkown)
        if self.IGNORE_RULES:
            return False
        for value in args:
            if value in self.IGNORED_TARGETS:
                return True
        return False  # fallback to required

    ##################################################
    # on_xxx block
    ##################################################

    def _parse_block(self, block: str, param: str) -> bool:
        ''' Returns `True` if on_BLOCK matches requirements '''
        # https://github.com/Homebrew/brew/blob/main/Library/Homebrew/ast_constants.rb#L32
        # on_macos, on_system, on_linux, on_arm, on_intel, "on_#{os_name}"
        if block == 'macos':
            if not param:
                return Arch.IS_MAC
        elif block == 'linux':
            if not param:
                return not Arch.IS_MAC
        elif block == 'arm':
            if not param:
                return Arch.IS_ARM
        elif block == 'intel':
            if not param:
                return not Arch.IS_ARM
        elif block == 'arch':
            return self._eval_on_arch(param)
        elif block == 'system':
            if param:
                return any(self._eval_on_system(x) for x in param.split(','))
        elif block in Arch.ALL_OS:
            if not Arch.IS_MAC:
                return False
            return self._eval_on_mac_version(block, param)
        self._err(f'unknown on_{block} with param "{param}"')
        return True  # fallback to is-a-matching-block

    def _eval_on_arch(self, param: str) -> bool:
        if param == ':arm':
            return Arch.IS_ARM
        if param in ':intel':
            return not Arch.IS_ARM
        self._err(f'unknown on_arch param "{param}"')
        return True  # fallback to is-matching

    def _eval_on_system(self, param: str) -> bool:
        ''' Returns `True` if current machine matches requirements '''
        param = param.strip()
        if param == ':linux':
            return not Arch.IS_MAC

        if param == ':macos':
            return Arch.IS_MAC

        if param.startswith('macos: :'):
            if not Arch.IS_MAC:
                return False
            os_name = param.removeprefix('macos: :')
            if os_name.endswith('_or_older'):
                if ver := Arch.ALL_OS.get(os_name.removesuffix('_or_older')):
                    return Arch.OS_VER <= ver
            elif os_name.endswith('_or_newer'):
                if ver := Arch.ALL_OS.get(os_name.removesuffix('_or_newer')):
                    return Arch.OS_VER >= ver
            elif ver := Arch.ALL_OS.get(os_name):
                return Arch.OS_VER == ver

        self._err(f'unknown on_system param "{param}"')
        return True  # fallback to is-matching

    def _eval_on_mac_version(self, macver: str, param: str) -> bool:
        ''' Returns `True` if current machine matches requirements '''
        if not param:
            return Arch.OS_VER == Arch.ALL_OS[macver]
        if param == ':or_older':
            return Arch.OS_VER <= Arch.ALL_OS[macver]
        if param == ':or_newer':
            return Arch.OS_VER >= Arch.ALL_OS[macver]
        self._err(f'unknown on_{macver} param "{param}"')
        return True  # fallback to is-matching

    ##################################################
    # uses_from_macos
    ##################################################

    def _parse_uses(
        self, dep: str, uStr: str, uSym: str, uArr: str, rAct: str, rSym: str,
    ) -> bool:
        ''' Returns `True` if requirement is fulfilled. '''
        # dep [=> :uSym|uArr]? [, rAct: :rSym]?
        if self._is_ignored_target(self._unify_tok(uStr, uSym, uArr)):
            return True  # only a :build target

        if not Arch.IS_MAC:
            return False  # on linux, install

        if not rAct:
            assert not rSym
            return True  # no need to install, because it is a Mac

        assert rSym
        if rAct == 'since:':
            if os_ver := Arch.ALL_OS.get(rSym.lstrip(':')):
                return Arch.OS_VER >= os_ver
        self._err('unknown uses_from_macos', rAct, rSym)
        return True  # dont install, assuming it should be fine on any Mac

    ##################################################
    # depends_on
    ##################################################

    def _parse_depends(
        self, dep: str, sym: str, act: str,
        dStr: str, dSym: str, dArr: str,
        tStr: str, tSym: str, tArr: str, tIf: str,
    ) -> bool:
        ''' Returns `True` if dependency is required (needs install). '''
        # (dep|:sym|act: (dStr|:dSym|dArr))! [=> (tStr|:tSym|tArr)]? [if tIf]?
        if sym:
            self._validity_symbol(sym)
            return False  # no dependency, only a system requirement

        if act:
            dTok = self._unify_tok(dStr, dSym, dArr)
            param = dTok.pop(0)
            if not self._is_ignored_target(dTok):
                self._validity_action(act, param, dTok)
            return False  # no dependency, only a system requirement

        if self._is_ignored_target(self._unify_tok(tStr, tSym, tArr)):
            return False  # only a :build target

        if tIf and not self._eval_depends_if(tIf):
            return False  # if-clause says "no need to install"
        return True  # needs install

    def _eval_depends_if(self, clause: str) -> bool:
        ''' Returns `True` if if-clause evaluates to True '''
        if clause.startswith('MacOS.version '):
            if not Arch.IS_MAC:
                return False
            what, op, os_name = clause.split()
            if os_ver := Arch.ALL_OS.get(os_name.lstrip(':')):
                return Utils.cmpVersion(Arch.OS_VER, op, os_ver)

        elif clause.startswith('Formula["') and \
                clause.endswith('"].any_version_installed?'):
            pkg = clause.split('"')[1]
            return LocalPackage(pkg).installed or pkg in self.FAKE_INSTALLED

        elif clause.startswith('build.with? "'):
            pkg = clause.split('"')[1]
            # technically not correct, dependency could appear after this rule
            return pkg in self.dependencies

        elif clause.startswith('build.without? "'):
            pkg = clause.split('"')[1]
            # technically not correct, dependency could appear after this rule
            return pkg not in self.dependencies

        elif match := re.match(r'^(.+)\s+([<=>]+)\s+([0-9.]+)$', clause):
            what, op, ver = match.groups()
            ver = [int(x) for x in ver.split('.')]
            if what == 'DevelopmentTools.clang_build_version':
                return Utils.cmpVersion(Arch.getClangBuildVersion(), op, ver)
            if what.startswith('DevelopmentTools.gcc_version'):
                return Utils.cmpVersion(Arch.getGccVersion(), op, ver)

        self._err('unhandled depends_on if-clause', clause)
        return True  # in case of doubt, install

    ##################################################
    # Check system architecture
    ##################################################

    def _validArch(self, check: bool, desc: str) -> None:
        if not check:
            self.invalidArch.append(desc)

    def _validity_symbol(self, sym: str) -> None:
        ''' Check if symbol corresponds to current system architecture '''
        if sym == ':linux':
            self._validArch(not Arch.IS_MAC, 'Linux only')
        elif sym == ':macos':
            self._validArch(Arch.IS_MAC, 'MacOS only')
        elif sym == ':xcode':
            self._validArch(Arch.hasXcodeVer('1'), 'needs Xcode')
        else:
            self._err('unknown depends_on symbol', sym)

    def _validity_action(self, act: str, param: str, flags: list[str]) -> None:
        ''' Check if action is valid on current system architecture '''
        # https://github.com/Homebrew/brew/blob/main/Library/Homebrew/dependency_collector.rb#L161
        # arch:, macos:, maximum_macos:, xcode:
        # not supported (yet): linux:, codesign:
        if act == 'arch:':
            assert not flags
            if param == ':x86_64':
                self._validArch(not Arch.IS_ARM, 'no ARM support')
            elif param == ':arm64':
                self._validArch(Arch.IS_ARM, 'ARM only')
            else:
                self._err('unknown depends_on arch:', param)

        elif act in ['macos:', 'maximum_macos:']:
            if os_ver := Arch.ALL_OS.get(param.lstrip(':')):
                op = '<=' if act == 'maximum_macos:' else '>='
                if Arch.IS_MAC:
                    self._validArch(Utils.cmpVersion(Arch.OS_VER, op, os_ver),
                                    f'needs macOS {op} {os_ver}')
                else:
                    self._validArch(False, f'needs macOS {op} {os_ver}')
            else:
                self._err('unknown depends_on', act, param)

        elif act == 'xcode:':
            ver = param
            if ver.startswith(':'):  # probably some ":build"
                self._validArch(Arch.hasXcodeVer('1'), 'needs Xcode')
            else:
                self._validArch(Arch.hasXcodeVer(ver), f'needs Xcode >= {ver}')

        else:
            self._err('unknown depends_on action', act, param, flags)


# -----------------------------------
#  Utils
# -----------------------------------

class File:
    @staticmethod
    def isMachO(fname: str) -> bool:
        # magic number check for Mach-O
        with open(fname, 'rb') as fp:
            return fp.read(4) == b'\xcf\xfa\xed\xfe'

    @staticmethod
    def isBinary(fname: str) -> bool:
        with open(fname, 'rb') as fp:
            return b'\0' in fp.read(4096)

    @staticmethod
    def isOutdated(fname: str, maxage: int) -> bool:
        ''' Check if `fname` is older than `maxage` '''
        return datetime.now().timestamp() - os.path.getmtime(fname) > maxage

    @staticmethod
    def sha256(fname: str) -> str:
        ''' Calculate sha256 sum of file content '''
        rv = hashlib.sha256()
        with open(fname, 'rb') as f:
            while data := f.read(65536):
                rv.update(data)
        return rv.hexdigest()

    @staticmethod
    def touch(fname: str) -> None:
        ''' Update access time of file (or create new file) '''
        with open(fname, 'a'):
            os.utime(fname, None)

    @staticmethod
    def folderSize(path: str) -> tuple[int, int]:
        '''Calculate total size of folder and all it's content (recursively)'''
        files = 0
        size = 0
        for entry in os.scandir(path):
            if not entry.is_symlink():
                if entry.is_file():
                    files += 1
                    size += os.path.getsize(entry)
                elif entry.is_dir():
                    df, ds = File.folderSize(entry.path)
                    files += df
                    size += ds
        return files, size

    @staticmethod
    def remove(path: str, *, dryRun: bool = False, quiet: bool = False) -> int:
        '''Delete file or folder. Calculate and print size. Optional dry-run'''
        isdir = os.path.isdir(path)
        if isdir:
            files, size = File.folderSize(path)
        else:
            size = 0 if os.path.islink(path) else os.path.getsize(path)

        if not quiet:
            Log.main('{}: {} ({}{})'.format(
                'Would remove' if dryRun else 'Removing',
                Cellar.shortPath(path),
                f'{files} files, ' if isdir else '',
                Txt.humanSize(size)))
        if not dryRun:
            shutil.rmtree(path) if isdir else os.remove(path)
        return size


class Txt:
    ''' They all return strings '''
    @staticmethod
    def humanSize(size: float) -> str:
        ''' Convert bytes to human readable format, e.g., 4096 -> "4K" '''
        for unit in 'BKMGTP':
            if size < 1024.0:
                break
            size /= 1024.0
        return f'{size:.1f}{unit}'

    @staticmethod
    def freedDiskSpace(savings: int, *, dryRun: bool) -> str:
        ''' "==> This operation has freed approximately X of disk space" '''
        return '==> This operation {} approximately {} of disk space'.format(
            'would free' if dryRun else 'has freed', Txt.humanSize(savings))

    @staticmethod
    def prettyList(arr: list[str], prefix: str = '  - ') -> str:
        ''' Join list of items with newline and prepend `prefix` '''
        return '\n'.join(prefix + x for x in arr)


class Utils:
    @staticmethod
    def ask(msg: str, default: str = 'y') -> bool:
        ''' Show user-input dialog. Returns `True` if user answered "yes" '''
        ans = input(msg + (' [Y/n] ' if default == 'y' else ' [y/N] '))
        return (ans or default).lower().startswith('y')

    Version = TypeVar('Version', int, str, list[int])

    @staticmethod
    def cmpVersion(left: Version, op: str, right: Version) -> bool:
        '''Convert `op` string to mathematical operation (<=, >=, <, >, ==)'''
        if op == '<=':
            return left <= right
        if op == '>=':
            return left >= right
        if op == '<':
            return left < right
        if op == '>':
            return left > right
        if op == '==':
            return left == right
        raise ArithmeticError(f'unknown op "{op}"')

    @staticmethod
    def printInColumns(
        strings: list[str], *,
        min_lines: int = 1, prefix: str = '', sep: str = '    ',
        plainList: bool = False,
    ) -> None:
        '''Detect best possible column-width and print `strings` in columns'''
        if not strings:
            return
        if plainList:
            for line in strings:
                print(line)
            return
        max_width = shutil.get_terminal_size().columns
        rows, cols, total = 0, 0, len(strings)
        lens = [len(x) for x in strings]
        # estimate minimum lines
        min_needed = len(prefix) + sum(lens) + len(sep) * (total - 1)
        min_rows = max(min_lines, math.ceil(min_needed / max_width))
        # detect best fit for given window width
        for rows in range(min_rows, 999):
            cols = math.ceil(total / rows)
            widths = [max(lens[rows * i:rows * i + rows])
                      for i in range(cols)]
            needed = len(prefix) + sum(widths) + (cols - 1) * len(sep)
            if needed < max_width:  # < instead of <= because +1 for \n
                break
        # group strings by column
        allOfThem = [strings[rows * i:rows * i + rows] for i in range(cols)]
        # fillup last column
        allOfThem[-1] += [''] * (rows * cols - total)
        # concatenate result
        for parts in zip(*allOfThem):
            line = sep.join(f'{x:{w}}' for x, w in zip(parts, widths))
            print(prefix + line.rstrip())


# -----------------------------------
#  Shell interface
# -----------------------------------

class Bash:
    @staticmethod
    def getVersion(cmd: list[str], pattern: str) -> list[int]:
        ''' Run `cmd` and match `pattern` (should include 1 matching group) '''
        try:
            rv = shell.run(cmd, capture_output=True)
            if match := re.search(pattern.encode('utf8'), rv.stdout):
                return [int(x) for x in match.group(1).split(b'.')]
        except OSError:
            pass
        return [0]

    @staticmethod
    def otool(fname: str) -> list[str]:
        ''' Read shared library references '''
        rv = shell.run(['otool', '-l', fname], capture_output=True)
        return rv.stdout.decode('utf8').split('\n')

    @staticmethod
    def install_name_tool(fname: str, args: list[str]) -> None:
        ''' Modify dylib structure '''
        shell.run(['install_name_tool'] + args + [fname], stderr=shell.DEVNULL)

    @staticmethod
    def codesign(fname: str) -> None:
        ''' Code sign with no real signature '''
        shell.run(['codesign', '--verify', '--force', '--sign', '-', fname],
                  stderr=shell.DEVNULL)


# -----------------------------------
#  (web) API
# -----------------------------------
# see How to download a file from GitHub Container Registry
#     https://stackoverflow.com/questions/78164818

class ApiBrew:
    class ManifestTarget(TypedDict):
        cellar: str
        url: str
        sha256: str

    class ManifestJson(TypedDict):
        homepage: str
        dependencies: list[str]
        versions: dict[str, str]
        # bottle: {stable: {files: {ARCH: ...}}}}
        bottle: dict[str, dict[str, dict[str, 'ApiBrew.ManifestTarget']]]

    @staticmethod
    def manifest(pkg: str, *, force: bool = False) -> ManifestJson:
        assert pkg, 'missing <package>'
        cache_name = f'{pkg}.brew.manifest.json'
        url = f'https://formulae.brew.sh/api/formula/{pkg}.json'
        return Curl.json(cache_name, url, force=force)  # type: ignore


class ApiGhcr:
    ENDOINT = 'https://ghcr.io/v2/homebrew/core/'

    class AuthJson(TypedDict):
        token: str

    @staticmethod
    def auth(pkg: str, *, force: bool = False) -> AuthJson:
        assert pkg, 'missing <package>'
        cache_name = '_auth-token.json'
        pkg = pkg.replace('@', '/')
        url = ('https://ghcr.io/token?service=ghcr.io&scope=repository:'
               f'homebrew/core/{pkg}:pull')
        return Curl.json(cache_name, url, force=force)  # type: ignore

    class TagsJson(TypedDict):
        tags: list[str]

    @staticmethod
    def tags(auth: str, pkg: str, *, force: bool = False) -> TagsJson:
        assert auth, 'missing <auth>'
        assert pkg, 'missing <package>'
        cache_name = f'{pkg}.ghcr.tags.json'
        pkg = pkg.replace('@', '/')
        url = ApiGhcr.ENDOINT + f'{pkg}/tags/list'
        return Curl.json(cache_name, url, {  # type: ignore[no-any-return]
            'Authorization': 'Bearer ' + auth
        }, force=force)

    class ManifestTarget(TypedDict):
        platform: dict[str, str]  # 'architecture', 'os', 'os.version'
        annotations: dict[str, str]  # sh.brew.bottle.digest, etc.

    class ManifestJson(TypedDict):
        manifests: list['ApiGhcr.ManifestTarget']

    @staticmethod
    def manifest(auth: str, pkg: str, tag: str, *, force: bool = False) \
            -> ManifestJson:
        assert auth, 'missing <auth>'
        assert pkg, 'missing <package>'
        assert tag, 'missing <tag>'
        cache_name = f'{pkg}-{tag}.ghcr.manifest.json'
        pkg = pkg.replace('@', '/')
        url = ApiGhcr.ENDOINT + f'{pkg}/manifests/{tag}'
        return Curl.json(cache_name, url, {  # type: ignore[no-any-return]
            'Authorization': 'Bearer ' + auth,
            'Accept': 'application/vnd.oci.image.index.v1+json',
        }, force=force)

    @staticmethod
    def blob(
        auth: str, pkg: str, digest: str, *, progress: bool = True
    ) -> str:
        ''' Download binary blob '''
        assert auth, 'missing <auth>'
        assert pkg, 'missing <package>'
        assert digest, 'missing <digest>'
        cache_name = f'{pkg}.{digest}.bottle.tar.gz'
        pkg = pkg.replace('@', '/')
        url = ApiGhcr.ENDOINT + f'{pkg}/blobs/sha256:{digest}'
        fname = Curl.file(cache_name, url, {
            'Authorization': 'Bearer ' + auth,
            'Accept': 'application/vnd.oci.image.layer.v1.tar+gzip',
        }, progress=progress)
        if File.sha256(fname) != digest:
            Log.error('sha256 mismatch', fname)
            exit(1)
        return fname


# -----------------------------------
#  Curl
# -----------------------------------

class Curl:
    @staticmethod
    def json(
        cache_name: str, url: str, header: 'dict[str,str]|None' = None,
        *, force: bool = False
    ) -> Any:
        ''' Download file + parse json result. '''
        fname = Curl.file(cache_name, url, header, force=force, progress=False)
        with open(fname) as fp:
            return json.load(fp)

    @staticmethod
    def file(
        cache_name: str, url: str, headers: 'dict[str,str]|None' = None,
        *, force: bool = True, progress: bool = True
    ) -> str:
        '''
        Download raw data to file. Creates an intermediate ".inprogress" file.
        '''
        fname = os.path.join(Cellar.CACHE, cache_name)
        if force or not os.path.isfile(fname):
            os.makedirs(Cellar.CACHE, exist_ok=True)
            tmp_file = fname + '.inprogress'

            opener = Req.build_opener()
            opener.addheaders = list((headers or {}).items())
            Req.install_opener(opener)
            try:
                if progress:
                    Req.urlretrieve(url, tmp_file, Curl.printProgress)
                    Log.info('' if Env.IS_TTY else ' done')
                else:
                    Req.urlretrieve(url, tmp_file)
            except HTTPError:
                Log.error('could not download', url)
                exit(1)

            os.rename(tmp_file, fname)  # atomic download, no broken files
        return fname

    @staticmethod
    def printProgress(
        blocknum: int, bs: int, size: int, progress: list[int] = [0]
    ) -> None:
        percent = min((blocknum * bs) / size, 1.0)
        done = int(40 * percent)
        if Env.IS_TTY:
            Log.info(f'\r[{"#" * done:<40}] {percent:.1%}', end='')
        else:
            if progress[0] != done:
                progress[0] = done
                Log.info('.', end='')


# -----------------------------------
#  Logger
# -----------------------------------

class Log:
    LEVEL = 2  # 0: error, 1: warn, 2: info, 3: debug
    _SUMMARY = None  # type: StringIO|None
    _COUNT = 0
    _COUNT_TOTAL = 0

    @staticmethod
    def _log(
        lvl: int, *msg: Any, summary: bool = False, count: bool = False,
        **kwargs: Any
    ) -> None:
        if Log.LEVEL >= lvl:
            if count and Log._COUNT_TOTAL:
                Log._COUNT += 1
                print(f'[{Log._COUNT}/{Log._COUNT_TOTAL}]', *msg, **kwargs)
            else:
                print(*msg, **kwargs)
            if summary and Log._SUMMARY:
                kwargs['file'] = Log._SUMMARY
                print(*msg, **kwargs)

    @staticmethod
    def error(*msg: Any, **kwargs: Any) -> None:
        start = '\033[31m' if Env.IS_TTY else ''
        end = '\033[0m' if Env.IS_TTY else ''
        kwargs['file'] = sys.stderr
        Log._log(0, f'{start}ERROR:', *msg, end, **kwargs)

    @staticmethod
    def main(*msg: Any, **kwargs: Any) -> None:
        Log._log(0, *msg, **kwargs)

    @staticmethod
    def warn(*msg: Any, **kwargs: Any) -> None:
        Log._log(1, '[WARN]', *msg, **kwargs)

    @staticmethod
    def info(*msg: Any, **kwargs: Any) -> None:
        Log._log(2, *msg, **kwargs)

    @staticmethod
    def debug(*msg: Any, **kwargs: Any) -> None:
        Log._log(3, *msg, **kwargs)

    # counter

    @staticmethod
    def beginCounter(total: int) -> None:
        Log._COUNT = 0
        Log._COUNT_TOTAL = total

    @staticmethod
    def endCounter() -> None:
        Log._COUNT = 0
        Log._COUNT_TOTAL = 0

    # log summary

    @staticmethod
    def beginErrorSummary() -> None:
        assert not Log._SUMMARY, 'summary already running'
        Log._SUMMARY = StringIO()

    @staticmethod
    def dumpErrorSummary() -> None:
        if Log._SUMMARY:
            if Log._SUMMARY.tell():
                print()
                print('Error summary:')
                print(Log._SUMMARY.getvalue(), end='')  # no double-\n
            Log._SUMMARY.close()
            Log._SUMMARY = None


if __name__ == '__main__':
    main()
