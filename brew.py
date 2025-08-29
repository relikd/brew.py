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
from webbrowser import open as launchBrowser
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
    MAX_AGE_CACHE = 5 * 24 * 60 * 60  # 5 days
    MAX_AGE_DOWNLOAD = int(os.environ.get('BREW_PY_CLEANUP_MAX_AGE_DAYS', 21))
    CELLAR_PATH = os.environ.get('BREW_PY_CELLAR', '').rstrip('/')
    LINK_BINARIES = os.environ.get('BREW_PY_LINK_BINARIES', '1').lower() in (
        'true', '1', 'yes', 'y', 'on')


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
    if args.version is True:
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
    info = Cellar.info(args.package)
    Log.info('Installed:', 'yes' if info.installed else 'no')

    # local information
    if info.installed:
        Log.info(' Active version:', info.verActive or '–')
        Log.info(' Inactive versions:', ', '.join(info.verInactive) or '–')

        ver = args.version or info.verActive
        if ver:
            Log.info(f' Dependencies[{ver}]:')
            if ver not in info.verAll:
                Log.info('  <not installed>')
            else:
                localDeps = Cellar.getDependencies(args.package, ver)
                Log.info(' ', ', '.join(sorted(localDeps)) or '<none>')

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
    Log.info(Utils.prettyList([manifest.digest or '<architecture not found>']))
    Log.info(' Dependencies:')
    deps = manifest.dependencies
    if deps is None:
        deps = ['<architecture not found>']
    Log.info(Utils.prettyList(sorted(deps)) or '  <none>')
    Log.info(' Platforms:')
    Log.info(Utils.prettyList(sorted(manifest.platforms)) or '  <none>')

    if mode == 'Brew':
        Log.info('GHCR:')
        Log.info(' Tags:')
        tags = Brew.ghcrTags(args.package, force=True)
        Utils.printInColumns(sorted(tags), prefix='  ', sep='  |  ')


# https://docs.brew.sh/Manpage#home-homepage---formula---cask-formulacask-
def cli_home(args: ArgParams) -> None:
    ''' Open a project's homepage in a browser. '''
    url = Cellar.getHomepageUrl(args.package)
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
            Log.info(Utils.prettyList(manifest.platforms))
            exit(1)

    Log.info(' tag:', tag)
    Log.info(' digest:', digest)

    path = Brew.download(Brew.Dependency(args.package, tag or digest, digest),
                         askOverwrite=True)
    Log.info('==> ', end='')
    Log.main(path)


# https://docs.brew.sh/Manpage#list-ls-options-installed_formulainstalled_cask-
def cli_list(args: ArgParams) -> None:
    ''' List installed packages. '''
    infos = Cellar.infoAll(args.packages)
    if args.multiple:
        infos = [x for x in infos if len(x.verAll) > 1]
    if not infos:
        Log.main('no package found.')
        return

    if args.versions:
        for info in infos:
            txt = '{}: {}'.format(info.package, info.verActive or 'not linked')
            if info.verInactive:
                txt += ' ({})'.format(', '.join(info.verInactive))
            Log.main(txt)
    else:
        Utils.printInColumns([x.package for x in infos],
                             plainList=not Env.IS_TTY or args.__dict__['1'])


# https://docs.brew.sh/Manpage#deps-options-formulacask-
def cli_deps(args: ArgParams) -> None:
    ''' Show dependencies for package. '''
    depTree = Cellar.getDependencyTree()
    depTree.forward.assertInstalled(args.packages)

    choice = args.packages or sorted(depTree.forward)

    if args.dot:
        depTree.forward.dotGraph(args.packages or depTree.reverse.directEnd())
    elif args.tree:
        depTree.forward.printTree(choice, depth=args.depth)
    else:
        depTree.forward.printFlat(
            choice, ' => ', leaves=args.leaves, direct=args.depth == 1)


# https://docs.brew.sh/Manpage#upgrade-options-installed_formulainstalled_cask-
def cli_uses(args: ArgParams) -> None:
    ''' Show dependents of package (reverse dependencies). '''
    depTree = Cellar.getDependencyTree()
    depTree.reverse.assertInstalled(args.packages)

    if args.missing:
        choice = sorted(set(depTree.reverse).difference(depTree.forward))
        if args.packages:
            choice = sorted(
                x for x in choice
                if depTree.reverse.getAll(x).intersection(args.packages))
    else:
        choice = args.packages

    if args.dot:
        depTree.reverse.dotGraph(
            choice or depTree.forward.directEnd(), reverse=True)
    elif args.tree:
        depTree.reverse.printTree(choice, depth=args.depth)
    else:
        depTree.reverse.printFlat(
            choice, ' := ', leaves=args.leaves, direct=args.depth == 1)


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
    depTree.reverse.assertInstalled(args.packages)

    if args.packages:
        installed = depTree.forward.unionAll(args.packages, inclInput=False)
    else:
        installed = set(depTree.reverse)

    missing = sorted(installed.difference(depTree.forward))
    if args.no_dependencies:
        Utils.printInColumns(
            missing, plainList=not Env.IS_TTY or args.__dict__['1'])
    else:
        for pkg in missing:
            direct = depTree.reverse.direct[pkg]
            leaves = depTree.reverse.getLeaves(pkg)
            Log.main('{} (dependency of: {} ... {})'.format(
                pkg, ', '.join(direct - leaves), ', '.join(leaves)))

    if missing:
        if Log.LEVEL >= 2:
            Log.error(f'missing {len(missing)} dependencies')
        exit(1)
    else:
        Log.info(f'all {len(installed)} dependencies installed')


# https://docs.brew.sh/Manpage#install-options-formulacask-
def cli_install(args: ArgParams) -> None:
    ''' Install a package with all dependencies. '''
    if os.path.isfile(args.package) and args.package.endswith('.tar.gz'):
        if args.dry_run:
            Log.info('==> Would install from tar file ...')
        else:
            Log.info('==> Installing from tar file ...')
            Cellar.install(args.package,
                           skipLink=args.skip_link, linkExe=args.binaries)
        return

    elif '/' in args.package:
        Log.error('package may not contain path-separator')
        return

    if args.ignore_dependencies:
        Log.info('==> Ignoring dependencies ...')
        deps = Brew.gatherDependencies(args.package, recursive=False)
    else:
        Log.info('==> Gather dependencies ...')
        deps = Brew.gatherDependencies(args.package, recursive=True)

    Log.info(Utils.prettyList([x.package for x in deps]))

    infos = [Cellar.info(x.package) for x in deps]
    # if all are installed, we dont care about which version exactly.
    # users should run upgrade in that case
    if not args.force and all(x.installed for x in infos):
        Log.error(args.package, 'is already installed.')
        Brew.checkUpdates(deps)
        return

    # if at least one digest couldn't be determined, we must fail whole queue
    failed_arch = [x.package for x in deps if not x.digest]
    if failed_arch:
        Log.error('missing platform "{}" in: {}'.format(
            Arch.BREW, ', '.join(failed_arch)))
        return

    # skip if a specific version already exists
    needs_download = [dep for dep, info in zip(deps, infos)
                      if args.force or dep.version not in info.verAll]

    Log.info()
    Log.info('==> Download ...')
    Log.beginCounter(len(needs_download))
    needs_install = [Brew.download(dep, dryRun=args.dry_run)
                     for dep in needs_download]

    Log.info()
    Log.info('==> Install ...')
    Log.beginCounter(len(needs_install))
    Log.beginErrorSummary()
    for tar in reversed(needs_install):
        if args.dry_run:
            Log.main('would install', os.path.relpath(tar, Cellar.ROOT),
                     count=True)
        else:
            Cellar.install(tar, skipLink=args.skip_link, linkExe=args.binaries)

    Log.endCounter()
    Log.dumpErrorSummary()


# https://docs.brew.sh/Manpage#uninstall-remove-rm-options-installed_formulainstalled_cask-
def cli_uninstall(args: ArgParams) -> None:
    ''' Remove / uninstall a package. '''
    depTree = Cellar.getDependencyTree()
    depTree.forward.assertInstalled(args.packages + args.ignore)

    recipe = depTree.collectUninstall(
        args.packages, args.ignore, ignoreDependencies=args.no_dependencies)

    # hard-fail check. no direct dependencies
    if not args.force and recipe.warnings:
        for pkg, deps in recipe.warnings:
            if args.leaves:
                deps = depTree.reverse.getLeaves(pkg).difference(
                    args.packages, args.ignore)
            Log.error('{} is a {}dependency of {}'.format(
                pkg, '' if args.leaves else 'direct ', ', '.join(deps)))
        exit(1)

    needsUninstall = sorted(recipe.remove)

    # if not dry-run, show potential changes
    for pkg in [] if args.dry_run else needsUninstall:
        Log.main(f'==> will remove {pkg}.')

    # soft-fail check. warning for any doubly used dependencies
    for pkg in sorted(recipe.skip):
        if args.leaves:
            deps = depTree.reverse.getLeaves(pkg)
        else:
            deps = depTree.reverse.direct[pkg]
        Log.warn(f'skip {pkg}. used by:',
                 ', '.join(deps.difference(recipe.remove, args.ignore)))

    # if interactive, show potential changes and ask user to continue
    if args.dry_run or args.yes:
        pass
    elif not Utils.ask('Do you want to continue?', 'n'):
        Log.info('abort.')
        return

    # delete links
    Log.info('==> Remove symlinks for', len(needsUninstall), 'packages')
    count = 0
    for pkg in needsUninstall:
        count += len(Cellar.unlinkPackage(
            pkg, dryRun=args.dry_run, quiet=args.dry_run and Log.LEVEL <= 2))
    Log.main('Would remove' if args.dry_run else 'Removed', count, 'symlinks')

    # delete packages and links
    Log.info('==> Uninstall', len(needsUninstall), 'packages')
    total_savings = 0
    for pkg in needsUninstall:
        path = Cellar.installPath(pkg)
        total_savings += File.remove(path, args.dry_run)

    Log.info('==> This operation {} approximately {} of disk space.'.format(
        'would free' if args.dry_run else 'has freed',
        Utils.humanSize(total_savings)))

    if args.dry_run:
        print()
        print('The following packages will be removed:')
        Utils.printInColumns(needsUninstall)
        if recipe.skip:
            print()
            print('The following packages will NOT be removed:')
            Utils.printInColumns(sorted(recipe.skip))


# https://docs.brew.sh/Manpage#link-ln-options-installed_formula-
def cli_link(args: ArgParams) -> None:
    ''' Link a specific package version (activate). '''
    info = Cellar.info(args.package)
    if not info.installed:
        Log.error('unknown package:', args.package)
        return

    if info.verActive:
        # must unlink before relinking (except --bin)
        if args.bin:
            args.version = info.verActive
        else:
            Log.error(f'already linked to {info.verActive}. Unlink first.')
            return

    # auto-fill version if there is only one version
    if not args.version:
        if len(info.verAll) == 1:
            args.version = info.verAll[0]
        else:
            Log.info('Multiple versions found:')
            Log.info(Utils.prettyList(info.verAll))
            Log.error('no package version provided.')
            return

    # check if package is really installed
    if args.version not in info.verAll:
        Log.error('package version', args.version, 'not found')
        return

    if not args.force and Cellar.isKegOnly(args.package, args.version):
        Log.error(args.package, 'is keg-only. Use -f to force linking.')
        return

    # perform link
    Cellar.linkPackage(args.package, args.version,
                       noExe=args.no_bin, dryRun=args.dry_run)
    Log.main('==> Linked to', args.version)


# https://docs.brew.sh/Manpage#unlink---dry-run-installed_formula-
def cli_unlink(args: ArgParams) -> None:
    ''' Remove symlinks for package to (temporarily) disable it. '''
    info = Cellar.info(args.package)
    if not info.installed:
        Log.error('unknown package:', args.package)
        return
    if not info.verActive:
        Log.error(args.package, 'is not active')
        return

    # perform unlink
    Cellar.unlinkPackage(args.package, onlyExe=args.bin, dryRun=args.dry_run)
    Log.main('==> Unlinked', info.verActive)


def cli_switch(args: ArgParams) -> None:
    ''' Change package version. '''
    info = Cellar.info(args.package)
    if not info.installed:
        Log.error('unknown package:', args.package)
        return
    if not info.verActive:
        Log.error('cannot switch, package is not active')
        return
    if info.verActive == args.version:
        Log.main('already on', info.verActive)
        return

    # convenience toggle
    if not args.version and len(info.verInactive) == 1:
        args.version = info.verInactive[0]

    # convenience list print
    if not args.version:
        Log.info('Available versions:')
        Utils.printInColumns(info.verAll, prefix='  ')
        Log.error('no version provided')
        return

    noBinsLinks = not Cellar.getBinLinks(args.package)
    Cellar.unlinkPackage(args.package, onlyExe=False)
    Cellar.linkPackage(args.package, args.version, noExe=noBinsLinks)
    Log.main('==> switched to version', args.version)
    if noBinsLinks:
        Log.warn('no binary links found. Skipped for new version as well.')


# https://docs.brew.sh/Manpage#cleanup-options-formulacask-
def cli_cleanup(args: ArgParams) -> None:
    '''
    Remove old versions of installed packages.
    If arguments are specified, only do this for the given packages.
    Removes all downloads more than 21 days old.
    This can be adjusted with $BREW_PY_CLEANUP_MAX_AGE_DAYS.
    '''
    total_savings = 0
    infos = Cellar.infoAll(args.packages)
    if not infos:
        Log.error('no package found')
        return

    if not args.packages:
        Log.info('==> Removing cached downloads')
        maxage = Env.MAX_AGE_DOWNLOAD if args.prune is None else args.prune
        for file in os.scandir(Cellar.DOWNLOAD):
            if File.isOutdated(file.path, maxage * 24 * 60 * 60):
                total_savings += File.remove(file.path, args.dry_run)

    # remove all non-active versions
    Log.info('==> Removing old versions')
    for info in infos:
        for ver in info.verInactive:
            if Cellar.isKegOnly(info.package, ver):
                continue
            path = Cellar.installPath(info.package, ver)
            total_savings += File.remove(path, args.dry_run)

    # should never happen but just in case, remove symlinks which point nowhere
    Log.info('==> Removing dead links')
    binLinks = Cellar.getBinLinks()
    if args.packages:
        deadPaths = set(Cellar.installPath(x) + '/' for x in args.packages)
        binLinks = [x for x in binLinks
                    if any(x.target.startswith(y) for y in deadPaths)]

    for link in binLinks:
        if not os.path.exists(link.target):
            total_savings += File.remove(link.path, args.dry_run)

    Log.main('==> This operation {} approximately {} of disk space.'.format(
        'would free' if args.dry_run else 'has freed',
        Utils.humanSize(total_savings)))


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
    cmd = cli.subcommand('fetch', cli_fetch)
    cmd.arg('package', help='Brew package name')
    cmd.arg('-arch', help='''Download for the given platform architecture.
        (e.g. 'arm64_sequoia' (brew), 'arm64|darwin|macOS 15' (ghcr))''')
    cmd.arg('-o', dest='outfile', help='''
        Output file. (default: download/<pkg>-<version|digest>.tar.gz)''')
    grp = cmd.xor_group()
    grp.arg_bool('-ghcr', help='''
        Download from ghcr registry instead of Brew.sh''')
    grp.arg('-tag', help='Manually provide tag / version (uses ghcr)')
    grp.arg('-digest', help='''
        Manually provide digest hash (direct download, skips tag query)''')
    cmd.epilog = '''
    If no -ghcr/-tag/-digest is provided, use DIGEST hash of Brew.sh.
    Otherwise, DIGEST hash will be queried from Github registry.'''

    # list
    cmd = cli.subcommand('list', cli_list, aliases=['ls'])
    cmd.arg('packages', nargs='*', help='Brew package name')
    cmd.arg_bool('--versions', help='Include version numbers in list')
    cmd.arg_bool('-1', help='''
        Force output to be one entry per line.
        This is the default when output is not to a terminal.''')
    cmd.arg_bool('--multiple', help='''
        Only show packages with multiple versions installed''')

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
    cmd = cli.subcommand('install', cli_install)
    cmd.arg('package', help='Brew package name')
    cmd.arg_bool('-f', '--force', help='Install even if already installed')
    cmd.arg_bool('-n', '--dry-run', help='''
        Show what would be installed, but do not actually install anything''')
    cmd.arg('-arch', help='''Manually set platform architecture
        (e.g. 'arm64_sequoia' (brew), 'arm64|darwin|macOS 15' (ghcr))''')
    cmd.arg_bool('--ignore-dependencies', help='Do not install dependencies')
    cmd.arg_bool('--skip-link', help='Install but skip linking to opt')
    cmd.arg('--binaries', action=BooleanOptionalAction, help='''
        Enable/disable linking of helper executables (default: enabled).
        Can be set with $BREW_PY_LINK_BINARIES.''')

    # uninstall
    cmd = cli.subcommand('uninstall', cli_uninstall, aliases=['remove', 'rm'])
    cmd.arg('packages', nargs='+', help='Brew package name')
    cmd.arg_bool('-y', '--yes', help='Do not ask for confirmation')
    cmd.arg_bool('-f', '--force', help='''
        Remove package even if it is a direct dependency of another package''')
    cmd.arg('--ignore', nargs='*', default=[], help='''
        Treat IGNORE packages as if they are not installed.
        Allow uninstall of packages which are dependency of IGNORE package.''')
    cmd.arg_bool('--no-dependencies', help='''
        Do not uninstall any of the dependencies of package''')
    cmd.arg_bool('--leaves', help='Show top-most dependencies, not direct')
    cmd.arg_bool('-n', '--dry-run', help='''
        List packages which would be uninstalled, without actually removing''')

    # link
    cmd = cli.subcommand('link', cli_link, aliases=['ln'])
    cmd.arg('package', help='Brew package name')
    cmd.arg('version', nargs='?', help='''
        Optional if there is only a single version installed''')
    cmd.arg_bool('-f', '--force', help='Allow keg-only packages to be linked')
    cmd.arg_bool('-n', '--dry-run', help='''
        List files which would be linked without actually linking''')
    grp = cmd.xor_group()
    grp.arg_bool('--bin', help='Only link binaries, ignore opt-link')
    grp.arg_bool('--no-bin', help='Only link opt-link, ignore binaries')

    # unlink
    cmd = cli.subcommand('unlink', cli_unlink)
    cmd.arg('package', help='Brew package name')
    cmd.arg_bool('-n', '--dry-run', help='''
        List files which would be unlinked without actually unlinking''')
    cmd.arg_bool('--bin', help='Unlink binary but keep opt link active')

    # switch
    cmd = cli.subcommand('switch', cli_switch)
    cmd.arg('package', help='Brew package name')
    cmd.arg('version', nargs='?', help='Package version')  # convenience omit

    # cleanup
    cmd = cli.subcommand('cleanup', cli_cleanup)
    cmd.arg('packages', nargs='*', help='Brew package name')
    cmd.arg('--prune', type=int, help='''
        Remove all cache files older than specified days''')
    cmd.arg_bool('-n', '--dry-run', help='''
        Show what would be removed, but do not actually remove anything''')

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

    def unionAll(self, keys: Keys, *, inclInput: bool) -> set[str]:
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

    def directEnd(self) -> list[str]:
        ''' List of keys with with direct dead-ends '''
        return [key for key, deps in self.direct.items() if not deps]

    def assertInstalled(self, keys: Keys) -> None:
        ''' Print any `.missing(keys)` and exit with status code 1 '''
        if unknownKeys := self.missing(keys):
            Log.error('unknown package:', ', '.join(unknownKeys))
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
        for key in sorted(self.unionAll(keys, inclInput=True)):
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
        allIgnored = self.forward.unionAll(ignore, inclInput=True)
        # yes, add ignore then difference because <ignore> can be nested
        children = allIgnored.difference(ignore)
        # going UP the tree and selecting branches not already ignored.
        # => look for children with other parents besides <ignore>
        multiParents = self.reverse.filterDifference(children, allIgnored)
        return allIgnored - multiParents

    class UninstallRecipe(NamedTuple):
        remove: set[str]
        skip: set[str]
        warnings: list[tuple[str, set[str]]]  # [(pkg, {deps})]

    def collectUninstall(
        self, deletePkgs: list[str], hiddenPkgs: list[str],
        *, ignoreDependencies: bool
    ) -> UninstallRecipe:
        '''
        Try to uninstall all `deletePkgs`. Act as if `hiddenPkgs` don't exist.
        Any package that depends on another package (not in those two sets)
        will be skipped and remains on the system.
        '''
        def warnings(hidden: set[str]) -> list[tuple]:
            # uses after uninstall (dependencies with multiple parents)
            return [(pkg, deps) for pkg in deletePkgs
                    if (deps := self.reverse.direct[pkg] - hidden)]

        # user said "these aren't the packages you're looking for"
        activelyIgnored = self.obsolete(hiddenPkgs)

        if ignoreDependencies:
            hidden = activelyIgnored.union(deletePkgs)
            return self.UninstallRecipe(
                set(deletePkgs), set(), warnings(hidden))

        # ideally, we uninstall <deletePkgs> and all its dependencies
        rawUninstall = self.forward.unionAll(deletePkgs, inclInput=True)

        # dont consider these, they will be gone (or are actively ignored)
        hidden = activelyIgnored.union(rawUninstall)

        # only secondary items can be skipped, primary are always removed
        secondary = rawUninstall.difference(deletePkgs)
        # skip a package if it has other, non-ignored, parents
        skipped = self.reverse.filterDifference(secondary, hidden)
        removed = rawUninstall.difference(skipped)

        # recursively ignore dependencies that rely on already ignored
        while deps := self.reverse.filterIntersection(removed, skipped):
            skipped.update(deps)
            removed.difference_update(deps)

        # remove any not-installed packages
        removed -= self.forward.missing(removed)

        return self.UninstallRecipe(removed, skipped, warnings(hidden))


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

    class Dependency(NamedTuple):
        package: str
        version: str
        digest: Optional[str]

    @staticmethod
    def gatherDependencies(pkg: str, *, recursive: bool) -> list[Dependency]:
        rv = []
        queue = [pkg]
        done = set(pkg)
        while queue:
            pkg = queue.pop(0)
            bundle = Brew.info(pkg)
            rv.append(Brew.Dependency(pkg, bundle.version, bundle.digest))
            if recursive:
                subdeps = bundle.dependencies or []
                queue.extend(x for x in subdeps if x not in done)
                done.update(subdeps)
        return rv

    @staticmethod
    def checkUpdates(deps: list[Dependency]) -> None:
        shownAny = False
        for dep in deps:
            info = Cellar.info(dep.package)
            if dep.version not in info.verAll:
                shownAny = True
                Log.info(' * upgrade available {} {} (installed: {})'.format(
                    dep.package, dep.version, ', '.join(info.verAll)))
        if not shownAny:
            Log.info('all packages are up to date.')

    @staticmethod
    def download(
        dep: Dependency, *, askOverwrite: bool = False, dryRun: bool = False
    ) -> str:
        assert dep.digest, 'digest is required for download'
        fname = Cellar.downloadPath(dep.package, dep.version)
        # reuse already downloaded tar
        if os.path.isfile(fname):
            if File.sha256(fname) == dep.digest:
                Log.main('skip already downloaded', dep.package, dep.version,
                         count=True)
                return fname
            elif askOverwrite:
                Log.warn(f'file "{fname}" already exists')
                if not Utils.ask('Do you want to overwrite it?', 'n'):
                    Log.info('abort.')
                    return fname
            else:
                Log.warn('sha256 mismatch. Ignore local file and re-download.')

        if dryRun:
            Log.main('would download', dep.package, dep.version, count=True)
        else:
            Log.main('download', dep.package, dep.version, count=True)
            auth = Brew._ghcrAuth(dep.package)
            os.rename(ApiGhcr.blob(auth, dep.package, dep.digest), fname)
        return fname


# -----------------------------------
#  Local logic
# -----------------------------------

class Cellar:
    ROOT = Env.CELLAR_PATH
    BIN = os.path.join(ROOT, 'bin')
    CACHE = os.path.join(ROOT, 'cache')
    CELLAR = os.path.join(ROOT, 'cellar')
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
        Cellar.cleanup(Env.MAX_AGE_CACHE)

    @staticmethod
    def cleanup(maxage: int) -> None:
        ''' Check all files in cache and delete outdated. '''
        for file in os.scandir(Cellar.CACHE):
            # TODO: different maxage for auth-token?
            if file.name == '_auth-token.json':
                continue  # TODO: test how long the token is valid
            if File.isOutdated(file.path, maxage):
                os.remove(file.path)

    @staticmethod
    def downloadPath(pkg: str, version: str) -> str:
        ''' Returns `@/download/<pkg>-<version>.tar.gz` '''
        return os.path.join(Cellar.DOWNLOAD, f'{pkg}-{version}.tar.gz')

    @staticmethod
    def installPath(pkg: str, version: str = 'ø') -> str:
        ''' Returns `@/cellar/<pkg>` or `@/cellar/<pkg>/<version>` '''
        assert version is not None, 'version cannot be None if passed'
        if version == 'ø':
            return os.path.join(Cellar.CELLAR, pkg)
        return os.path.join(Cellar.CELLAR, pkg, version)

    @staticmethod
    def rubyPath(pkg: str, version: str, otherName: str = '') -> str:
        ''' Returns `@/cellar/<pkg>/<version>/.brew/{<pkg>.rb|<otherName>}` '''
        pkgRoot = Cellar.installPath(pkg, version)
        return os.path.join(pkgRoot, '.brew', otherName or (pkg + '.rb'))

    # Version handling

    class PackageInfo(NamedTuple):
        package: str
        installed: bool
        verActive: Optional[str]
        verInactive: list[str]
        verAll: list[str]

    @staticmethod
    def info(pkg: str) -> PackageInfo:
        ''' Info about active and available package versions '''
        optLink = Cellar.getOptLink(pkg, ensurePkg=True)
        active = os.path.basename(optLink.target) if optLink else None
        inactive = []
        available = []
        pkgPath = Cellar.installPath(pkg)
        if os.path.isdir(pkgPath):
            for ver in sorted(os.listdir(pkgPath)):
                if os.path.isdir(os.path.join(pkgPath, ver, '.brew')):
                    available.append(ver)
                    if ver != active:
                        inactive.append(ver)
        return Cellar.PackageInfo(
            pkg, len(available) > 0, active, inactive, available)

    @staticmethod
    def infoAll(filterPkg: list[str] = []) -> list[PackageInfo]:
        ''' List all installed packages (already checked for `.installed`) '''
        pkgs = filterPkg if filterPkg else sorted(os.listdir(Cellar.CELLAR))
        return [info for pkg in pkgs if (info := Cellar.info(pkg)).installed]

    # Install management

    @staticmethod
    def install(
        tarPath: str, *, skipLink: bool = False, linkExe: bool = False
    ) -> bool:
        ''' Extract tar file into `@/cellar/...` '''
        pkg, version = None, None
        with openTarfile(tarPath, 'r') as tar:
            subset = []
            for x in tar:
                if tarFilter(x, Cellar.CELLAR):
                    subset.append(x)
                    if x.isdir() and x.path.endswith('/.brew'):
                        pkg, version, *_ = x.path.split('/')
                else:
                    Log.error('prohibited tar entry "{}" in ({})'.format(
                        x.path, os.path.basename(tarPath)), summary=True)

            if pkg is None or version is None:
                Log.error('".brew" dir missing. Failed to extract {}'.format(
                    os.path.basename(tarPath)), summary=True, count=True)
                return False
            else:
                Log.main(f'install {pkg} {version}', count=True)
                tar.extractall(Cellar.CELLAR, subset)

                with open(Cellar.rubyPath(pkg, version, 'digest'), 'w') as fp:
                    fp.write(File.sha256(tarPath))

        # relink dylibs
        Fixer.run(pkg, version)

        if skipLink:
            return True

        if Cellar.isKegOnly(pkg, version):
            Log.warn(f'keg-only, must link manually ({pkg}, {version})',
                     summary=True)
        else:
            withBin = Env.LINK_BINARIES if linkExe is None else linkExe
            Cellar.unlinkPackage(pkg)
            Cellar.linkPackage(pkg, version, noExe=not withBin)
        return True

    @staticmethod
    def getDependencyTree() -> DependencyTree:
        ''' Returns dict object for dependency traversal '''
        forward = TreeDict()
        for info in Cellar.infoAll():  # must always go over all, no filters
            forward.direct[info.package] = set(
                dep
                for ver in info.verAll
                for dep in Cellar.getDependencies(info.package, ver) or []
            )
        return DependencyTree(forward)

    # Symlink processing

    class LinkTarget(NamedTuple):
        path: str
        target: str  # absolute path
        raw: str  # relative target

    @staticmethod
    def _readLink(filePath: str, startswith: str = '') -> 'LinkTarget|None':
        ''' Read a single symlink and populate with absolute paths '''
        if not os.path.islink(filePath):
            return None
        raw = os.readlink(filePath)
        real = os.path.realpath(os.path.join(os.path.dirname(filePath), raw))
        if real.startswith(startswith or ''):
            return Cellar.LinkTarget(filePath, real, raw)
        return None

    @staticmethod
    def getOptLink(pkg: str, *, ensurePkg: bool) -> 'LinkTarget|None':
        ''' Read `@/opt/<pkg>` link. Returns `None` if non-exist '''
        pkgPath = (Cellar.installPath(pkg) + '/') if ensurePkg else ''
        return Cellar._readLink(os.path.join(Cellar.OPT, pkg), pkgPath)

    @staticmethod
    def getBinLinks(pkg: 'str|None' = None) -> list[LinkTarget]:
        ''' List of `@/bin/...` links that match `<pkg>` destination '''
        pkgPath = (Cellar.installPath(pkg) + '/') if pkg else ''
        rv = []
        for file in os.listdir(Cellar.BIN):
            lnk = Cellar._readLink(os.path.join(Cellar.BIN, file), pkgPath)
            if lnk:
                rv.append(lnk)
        return rv

    @staticmethod
    def unlinkPackage(
        pkg: str, *,
        onlyExe: bool = False, dryRun: bool = False, quiet: bool = False,
    ) -> list[LinkTarget]:
        ''' remove symlinks `@/opt/<pkg>` and `@/bin/...` matching target '''
        rv = Cellar.getBinLinks(pkg)
        if not onlyExe:
            rv += filter(None, [Cellar.getOptLink(pkg, ensurePkg=False)])
        for lnk in rv:
            shortPath = os.path.relpath(lnk.path, Cellar.ROOT)
            if not quiet:
                Log.info(f'  unlink {shortPath} -> {lnk.raw}')
            if not dryRun:
                os.remove(lnk.path)
        return rv

    @staticmethod
    def _gatherBinaries(pkg: str, version: str) -> list[str]:
        ''' Binary names (not paths) in `cellar/<pkg>/<version>/bin/...` '''
        path = os.path.join(Cellar.installPath(pkg, version), 'bin')
        if os.path.isdir(path):
            return [x.name for x in os.scandir(path) if os.access(x, os.X_OK)]
        return []

    @staticmethod
    def linkPackage(
        pkg: str, version: str, *, noExe: bool = False, dryRun: bool = False
    ) -> None:
        ''' create symlinks `@/opt/<pkg>` and `@/bin/...` matching target '''
        assert version, 'version is required'
        pkgRoot = Cellar.installPath(pkg, version)
        if not os.path.isdir(pkgRoot):
            raise RuntimeError('Package not installed')

        def ln(path: str, linkTarget: str) -> None:
            short = os.path.relpath(path, Cellar.ROOT)
            if os.path.islink(path) or os.path.exists(path):
                Log.warn(f'skip already existing link: {short}', summary=True)
            else:
                Log.info(f'  link {short} -> {linkTarget}')
                if not dryRun:
                    os.symlink(linkTarget, path)

        ln(os.path.join(Cellar.OPT, pkg), f'../cellar/{pkg}/{version}/')

        if not noExe:
            for exe in Cellar._gatherBinaries(pkg, version):
                ln(os.path.join(Cellar.BIN, exe), f'../opt/{pkg}/bin/{exe}')

    # Ruby file processing

    @staticmethod
    def getDependencies(pkg: str, version: str) -> set[str]:
        ''' Extract dependencies from ruby file '''
        assert version, 'version is required'
        return RubyParser(Cellar.rubyPath(pkg, version)).parse().dependencies

    @staticmethod
    def getHomepageUrl(pkg: str) -> 'str|None':
        ''' Extract homepage url from ruby file '''
        info = Cellar.info(pkg)
        ver = info.verActive or ([None] + info.verAll)[-1]
        if ver:
            return RubyParser(Cellar.rubyPath(pkg, ver)).parseHomepageUrl()
        return None

    @staticmethod
    def isKegOnly(pkg: str, version: str) -> bool:
        ''' Check if package is keg-only '''
        return RubyParser(Cellar.rubyPath(pkg, version)).parseKegOnly()


# -----------------------------------
#  Fixer
# -----------------------------------

class Fixer:
    @staticmethod
    def run(pkg: str, version: str) -> None:
        path = Cellar.installPath(pkg, version)

        if not os.path.isfile(Cellar.rubyPath(pkg, version)):
            Log.error('not a brew-package directory', path, summary=True)
            return

        for base, dirs, files in os.walk(path):
            for file in files:
                fname = os.path.join(base, file)
                if os.path.islink(fname):
                    Fixer.symlink(fname)
                    continue
                # magic number check for Mach-O
                with open(fname, 'rb') as fp:
                    if fp.read(4) != b'\xcf\xfa\xed\xfe':
                        continue
                Fixer.dylib(fname, pkg, version)

    @staticmethod
    def symlink(fname: str) -> None:
        ''' Fix time on symlink, copy time from target link '''
        # TODO: we could check if link is absolute, but untar already did that
        # fix date modified
        atime = os.path.getatime(fname)
        mtime = os.path.getmtime(fname)
        os.utime(fname, (atime, mtime), follow_symlinks=False)

    @staticmethod
    def dylib(fname: str, pkg: str, version: str) -> None:
        ''' Rewrite dylib to use relative links '''
        # TLDR:
        # 1) otool -L <file>  // list all linked shared libraries (exe + dylib)
        # 2) install_name_tool -id "newRef" <file>  // only for *.dylib files
        # 3) install_name_tool -change "oldRef" "newRef" <file>  // both types
        # 4) codesign --verify --force --sign - <file>  // resign with no sign
        repl1 = f'@@HOMEBREW_CELLAR@@/{pkg}/{version}/bin'
        repl2 = f'@@HOMEBREW_PREFIX@@/cellar/{pkg}/{version}/bin'
        atime = os.path.getatime(fname)
        mtime = os.path.getmtime(fname)

        did_change = False
        for oldRef in Bash.otool(fname):
            if oldRef.startswith('@@HOMEBREW_CELLAR@@'):
                newRef = os.path.relpath(oldRef, repl1)
            elif oldRef.startswith('@@HOMEBREW_PREFIX@@'):
                newRef = os.path.relpath(oldRef, repl2)
            elif oldRef.startswith('@'):
                Log.debug('unhandled dylib link', oldRef)
                continue
            else:
                continue  # probably fine

            newRef = '@executable_path/' + newRef
            if not did_change:
                Log.info('  fix dylib', os.path.relpath(fname, Cellar.ROOT))
            Log.debug('    OLD:', oldRef)
            Log.debug('    NEW:', newRef)

            if fname.endswith('.dylib'):
                Bash.install_name_tool_id(newRef, fname)
            Bash.install_name_tool_change(oldRef, newRef, fname)
            did_change = True

        if did_change:
            Log.debug('  codesign')
            Bash.codesign(fname)
            os.utime(fname, (atime, mtime))


# -----------------------------------
#  RubyParser
# -----------------------------------

class RubyParser:
    PRINT_PARSE_ERRORS = True
    ASSERT_KNOWN_SYMBOLS = False
    IGNORE_RULES = False
    FAKE_INSTALLED = set()  # type: set[str] # simulate Cellar.info().installed

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
            return Cellar.info(pkg).installed or pkg in self.FAKE_INSTALLED

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
    def isOutdated(fname: str, maxage: int) -> bool:
        return datetime.now().timestamp() - os.path.getmtime(fname) > maxage

    @staticmethod
    def sha256(fname: str) -> str:
        rv = hashlib.sha256()
        with open(fname, 'rb') as f:
            while data := f.read(65536):
                rv.update(data)
        return rv.hexdigest()

    @staticmethod
    def folderSize(path: str) -> tuple[int, int]:
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
    def remove(path: str, dryRun: bool) -> int:
        isdir = os.path.isdir(path)
        if isdir:
            files, size = File.folderSize(path)
        else:
            size = 0 if os.path.islink(path) else os.path.getsize(path)

        Log.main('{}: {} ({}{})'.format(
            'Would remove' if dryRun else 'Removing',
            os.path.relpath(path, Cellar.ROOT),
            f'{files} files, ' if isdir else '',
            Utils.humanSize(size)))
        if not dryRun:
            shutil.rmtree(path) if isdir else os.remove(path)
        return size


class Utils:
    @staticmethod
    def ask(msg: str, default: str = 'y') -> bool:
        ans = input(msg + (' [Y/n] ' if default == 'y' else ' [y/N] '))
        return (ans or default).lower().startswith('y')

    @staticmethod
    def humanSize(size: float) -> str:
        for unit in 'BKMGTP':
            if size < 1024.0:
                break
            size /= 1024.0
        return f'{size:.1f}{unit}'

    Version = TypeVar('Version', int, str, list[int])

    @staticmethod
    def cmpVersion(left: Version, op: str, right: Version) -> bool:
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
    def prettyList(arr: list[str], prefix: str = '  - ') -> str:
        return '\n'.join(prefix + x for x in arr)

    @staticmethod
    def printInColumns(
        strings: list[str], *,
        min_lines: int = 1, prefix: str = '', sep: str = '    ',
        plainList: bool = False,
    ) -> None:
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
        rv = shell.run(['otool', '-L', fname], capture_output=True)
        # TODO: can lib paths contain space?
        return [line.split()[0].decode('utf8')
                for line in rv.stdout.split(b'\n')
                if line.startswith(b'\t')]

    @staticmethod
    def install_name_tool_id(newRef: str, fname: str) -> None:
        ''' Set definitions (needed for dylib) '''
        shell.run(['install_name_tool', '-id', newRef, fname],
                  stderr=shell.DEVNULL)

    @staticmethod
    def install_name_tool_change(oldRef: str, newRef: str, fname: str) -> None:
        ''' Change library reference '''
        shell.run(['install_name_tool', '-change', oldRef, newRef, fname],
                  stderr=shell.DEVNULL)

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


# -----------------------------------
#  Misc
# -----------------------------------

# Copied from Python 3.12 tarfile _get_filtered_attrs
def tarFilter(member: TarInfo, dest_path: str) -> bool:
    dest_path = os.path.realpath(dest_path)
    # Strip leading / (tar's directory separator) from filenames.
    # Include os.sep (target OS directory separator) as well.
    if member.name.startswith(('/', os.sep)):
        return False
    # Ensure we stay in the destination
    target_path = os.path.realpath(os.path.join(dest_path, member.name))
    if os.path.commonpath([target_path, dest_path]) != dest_path:
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
            return False

    # Check link destination for 'data'
    if member.islnk() or member.issym():
        if os.path.isabs(member.linkname):
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
            return False
    return True


if __name__ == '__main__':
    main()

# TODO:

#  Show formulae with an updated version available
# https://docs.brew.sh/Manpage#outdated-options-formulacask-

#  Prevent the specified formulae from being upgraded
# https://docs.brew.sh/Manpage#pin-installed_formula-  ????

#  Allow the specified formulae to be upgraded.
# https://docs.brew.sh/Manpage#unpin-installed_formula-  ????

# https://docs.brew.sh/Manpage#reinstall-options-formulacask-

#  List all the current tapped repositories (taps)
#  Tap a formula repository from the specified URL
#  (default: https://github.com/user/homebrew-repo)
# https://docs.brew.sh/Manpage#tap-options-userrepo-url  ????

#  Remove the given tap from the repository
# https://docs.brew.sh/Manpage#untap---force-tap-  ????

#  Fetch latest version of homebrew and formula
# https://docs.brew.sh/Manpage#update-up-options

#  Upgrade all outdated and unpinned brews
#  Upgrade only the specified brew
# https://docs.brew.sh/Manpage#upgrade-options-installed_formulainstalled_cask-
