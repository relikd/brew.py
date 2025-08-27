#!/usr/bin/env python3
import os
from brew import Arch, RubyParser

RubyParser.PRINT_PARSE_ERRORS = True
RubyParser.ASSERT_KNOWN_SYMBOLS = True
RubyParser.IGNORE_RULES = True

Arch.OS_VER = '0'
Arch.IS_MAC = True
Arch.IS_ARM = True
Arch._SOFTWARE_VERSIONS = {
    'xcode': [0],
    'gcc': [0],
    'clang': [0],
}


def main() -> None:
    # testCoreFormulae()
    testRubyTestFile()
    # testConfigVariations()


def testRubyTestFile() -> None:
    ruby = RubyParser('test-formula.rb').parse()
    print()
    print('deps:')
    for dep in sorted(ruby.dependencies):
        if dep.startswith('__'):
            print('  ', dep)
    print('invalid arch:')
    print('  ', ruby.invalidArch)


def testCoreFormulae() -> None:
    if not os.path.isdir('git-clone'):
        print('run `make git-clone` first')
        return

    RubyParser.PRINT_PARSE_ERRORS = True
    RubyParser.ASSERT_KNOWN_SYMBOLS = True
    RubyParser.IGNORE_RULES = True

    for x in os.scandir('git-clone/Formula'):
        if x.is_dir():
            for file in os.scandir(x.path):
                RubyParser(file.path).parse()


def testConfigVariations() -> None:
    RubyParser.PRINT_PARSE_ERRORS = False
    RubyParser.ASSERT_KNOWN_SYMBOLS = False
    RubyParser.IGNORE_RULES = False

    for ver in Arch.ALL_OS.values():
        Arch.OS_VER = ver
        for ismac in [True, False]:
            Arch.IS_MAC = ismac
            for isarm in [True, False]:
                Arch.IS_ARM = isarm
                for xcode in [0, 9, 15]:
                    Arch._SOFTWARE_VERSIONS['xcode'] = [xcode]
                    for clang in [0, 1300, 1700]:
                        Arch._SOFTWARE_VERSIONS['clang'] = [clang]
                        for gcc in [0, 8, 14]:
                            Arch._SOFTWARE_VERSIONS['gcc'] = [gcc]
                            runSingleParseTest()

    RubyParser.FAKE_INSTALLED.add('zlib')
    runSingleParseTest()
    RubyParser.FAKE_INSTALLED.clear()
    runSingleParseTest()
    print('ok')


def runSingleParseTest() -> None:
    ruby = RubyParser('test-formula.rb').parse()
    assertInvalidArch(ruby)
    assertDependencies(ruby.dependencies)


def assertInvalidArch(ruby: RubyParser) -> None:
    if Arch.IS_ARM:
        assert 'no ARM support' in ruby.invalidArch
        assert 'ARM only' not in ruby.invalidArch
    else:
        assert 'no ARM support' not in ruby.invalidArch
        assert 'ARM only' in ruby.invalidArch

    if Arch._SOFTWARE_VERSIONS['xcode'] < [1]:
        assert 'needs Xcode >= 8.3' in ruby.invalidArch
        assert 'needs Xcode' in ruby.invalidArch
    elif Arch._SOFTWARE_VERSIONS['xcode'] < [8, 3]:
        assert 'needs Xcode >= 8.3' in ruby.invalidArch
        assert 'needs Xcode' not in ruby.invalidArch
    else:
        assert 'needs Xcode >= 8.3' not in ruby.invalidArch
        assert 'needs Xcode' not in ruby.invalidArch

    if not Arch.IS_MAC:
        assert 'Linux only' not in ruby.invalidArch
        assert 'needs macOS >= 10.13' in ruby.invalidArch
        assert 'needs macOS >= 10.14' in ruby.invalidArch
        assert 'MacOS only' in ruby.invalidArch
    elif Arch.OS_VER < '10.13':
        assert 'Linux only' in ruby.invalidArch
        assert 'needs macOS >= 10.13' in ruby.invalidArch
        assert 'needs macOS >= 10.14' in ruby.invalidArch
    elif Arch.OS_VER < '10.14':
        assert 'Linux only' in ruby.invalidArch
        assert 'needs macOS >= 10.13' not in ruby.invalidArch
        assert 'needs macOS >= 10.14' in ruby.invalidArch
    else:
        assert 'Linux only' in ruby.invalidArch
        assert 'needs macOS >= 10.13' not in ruby.invalidArch
        assert 'needs macOS >= 10.14' not in ruby.invalidArch


def assertDependencies(deps: set[str]) -> None:
    # test build target

    assert '__:recommended__' in deps
    assert '__:build__:test__' not in deps
    assert '__:build__' not in deps
    assert '__:test__' not in deps
    assert '__:optional__' not in deps

    # test nested ignore

    assert '__nested__on_macos__on_linux__' not in deps
    assert '__nested__on_linux__on_macos__' not in deps

    # test macos versions
    for os_name, os_ver in Arch.ALL_OS.items():
        if Arch.IS_MAC and Arch.OS_VER == os_ver:
            assert f'__on_{os_name}__' in deps, f'{os_name} in deps'
        else:
            assert f'__on_{os_name}__' not in deps, f'{os_name} not in deps'

    if Arch.IS_MAC:
        assert '__on_macos__' in deps
        assert '__on_linux__' not in deps
        assert '__uses_from_macos__' not in deps
    else:
        assert '__on_linux__' in deps
        assert '__on_macos__' not in deps
        assert '__uses_from_macos__' in deps

    if Arch.IS_ARM:
        assert '__on_arm__' in deps
        assert '__on_intel__' not in deps
        assert '__on_arch :arm__' in deps
        assert '__on_arch :intel__' not in deps
    else:
        assert '__on_arm__' not in deps
        assert '__on_intel__' in deps
        assert '__on_arch :arm__' not in deps
        assert '__on_arch :intel__' in deps

    if Arch.IS_MAC and Arch.OS_VER <= '12':
        assert '__on_monterey :or_older__' in deps
    else:
        assert '__on_monterey :or_older__' not in deps

    if Arch.OS_VER <= '10.12' and Arch.IS_MAC:
        assert '__on_system macos: :sierra_or_older__' in deps
    else:
        assert '__on_system macos: :sierra_or_older__' not in deps

    if Arch.IS_MAC and Arch.OS_VER < '11':
        assert '__on_system :linux, macos: :big_sur_or_newer__' not in deps
    else:
        assert '__on_system :linux, macos: :big_sur_or_newer__' in deps

    # test uses_from_macos

    assert '__uses_from_macos__:build__' not in deps
    assert '__uses_from_macos__:build__since__' not in deps

    if Arch.OS_VER >= '10.15' and Arch.IS_MAC:
        assert '__uses_from_macos__since_catalina__' not in deps
        assert '__uses_from_macos__since_sierra__' not in deps
    elif Arch.OS_VER >= '10.12' and Arch.IS_MAC:
        assert '__uses_from_macos__since_catalina__' in deps
        assert '__uses_from_macos__since_sierra__' not in deps
    else:
        assert '__uses_from_macos__since_catalina__' in deps
        assert '__uses_from_macos__since_sierra__' in deps

    # test if-clause

    if Arch.OS_VER >= '10.15' and Arch.IS_MAC:
        assert '__if_macos_>=_catalina__' in deps
        assert '__if_build.with_catalina__' in deps
        assert '__if_build.without_catalina__' not in deps
    else:
        assert '__if_build.with_catalina__' not in deps
        assert '__if_build.without_catalina__' in deps
        assert '__if_macos_>=_catalina__' not in deps

    if Arch._SOFTWARE_VERSIONS['clang'] <= [1400]:
        assert '__if_clang_<=_1400__' in deps
    else:
        assert '__if_clang_<=_1400__' not in deps

    if Arch._SOFTWARE_VERSIONS['gcc'] < [9]:
        assert '__if_gcc_<_9__' in deps
    else:
        assert '__if_gcc_<_9__' not in deps

    if 'zlib' in RubyParser.FAKE_INSTALLED:
        assert '__if_any_zlib_installed__' in deps
    else:
        assert '__if_any_zlib_installed__' not in deps


if __name__ == '__main__':
    main()
