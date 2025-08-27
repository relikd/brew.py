class Test < Formula
  homepage "https://example.org"
  keg_only :macos

  depends_on xcode: "8.3"

  depends_on :macos
  depends_on :linux

  depends_on arch: :x86_64
  depends_on arch: :arm64

  # test build target
  depends_on "__:build__:test__" => [:build, :test]
  depends_on "__:build__" => :build
  depends_on "__:test__" => :test
  depends_on "__:recommended__" => :recommended
  depends_on "__:optional__" => :optional

  # test uses_from_macos
  uses_from_macos "__uses_from_macos__"
  uses_from_macos "__uses_from_macos__:build__" => :build
  uses_from_macos "__uses_from_macos__:build__since__" => :build, since: :catalina
  uses_from_macos "__uses_from_macos__since_catalina__", since: :catalina
  uses_from_macos "__uses_from_macos__since_sierra__", since: :sierra

  # test if-clause
  depends_on "__if_clang_<=_1400__" if DevelopmentTools.clang_build_version <= 1400
  depends_on "__if_gcc_<_9__" if DevelopmentTools.gcc_version("/usr/bin/gcc") < 9
  depends_on "__if_macos_>=_catalina__" if MacOS.version >= :catalina
  depends_on "__if_any_zlib_installed__" if Formula["zlib"].any_version_installed?
  depends_on "__if_build.with_catalina__" if build.with? "__if_macos_>=_catalina__"
  depends_on "__if_build.without_catalina__" if build.without? "__if_macos_>=_catalina__"


  on_macos do
    depends_on "__on_macos__"
  end

  on_linux do
    depends_on "__on_linux__"
  end

  on_macos do
    on_linux do
      depends_on "__nested__on_macos__on_linux__"
    end
  end

  on_linux do
    on_macos do
      depends_on "__nested__on_linux__on_macos__"
    end
  end

  # https://rubydoc.brew.sh/OnSystem/MacOSAndLinux.html
  # https://rubydoc.brew.sh/Formula.html
  # https://rubydoc.brew.sh/Formula#uses_from_macos-class_method
  # https://rubydoc.brew.sh/Cask/DSL/DependsOn.html

  #############################################################################
  # from https://rubydoc.brew.sh/Formula.html#on_system_blocks_exist%3F-class_method
  #
  on_monterey :or_older do
    depends_on "__on_monterey :or_older__"
  end
  on_system :linux, macos: :big_sur_or_newer do
    depends_on "__on_system :linux, macos: :big_sur_or_newer__"
  end
  #
  #############################################################################


  #############################################################################
  # from https://rubydoc.brew.sh/OnSystem.html#ALL_OS_OPTIONS-constant
  #
  on_arch :arm do # comment
    depends_on "__on_arch :arm__"
  end
  on_arch :intel do
    depends_on "__on_arch :intel__"
  end
  on_system macos: :sierra_or_older do
    depends_on "__on_system macos: :sierra_or_older__"
  end
  #
  #############################################################################


  #############################################################################
  # https://rubydoc.brew.sh/RuboCop/Cask/AST/Stanza.html#on_arch_conditional%3F-instance_method
  #
  on_arm do
    depends_on "__on_arm__"
  end
  on_intel do
    depends_on "__on_intel__"
  end
  #
  #
  on_yosemite do
    depends_on "__on_yosemite__"
  end
  on_el_capitan do
    depends_on "__on_el_capitan__"
  end
  on_sierra do
    depends_on "__on_sierra__"
  end
  on_high_sierra do
    depends_on "__on_high_sierra__"
  end
  on_mojave do
    depends_on "__on_mojave__"
  end
  on_catalina do
    depends_on "__on_catalina__"
  end
  on_big_sur do
    depends_on "__on_big_sur__"
  end
  on_monterey do
    depends_on "__on_monterey__"
  end
  on_ventura do
    depends_on "__on_ventura__"
  end
  on_sonoma do
    depends_on "__on_sonoma__"
  end
  on_sequoia do
    depends_on "__on_sequoia__"
  end
  on_tahoe do
    depends_on "__on_tahoe__"
  end
  #
  #############################################################################


  #############################################################################
  # from glib formula
  #
  depends_on "python-setuptools" => :build # for gobject-introspection
  depends_on "python@3.13" => :build
  depends_on "pcre2"
  #
  uses_from_macos "flex" => :build # for gobject-introspection
  uses_from_macos "libffi", since: :catalina
  uses_from_macos "python"
  uses_from_macos "zlib"
  #
  #############################################################################


  #############################################################################
  # from https://docs.brew.sh/Formula-Cookbook#specifying-macos-components-as-dependencies
  #
  # For example, to require the bzip2 formula on Linux while relying on built-in bzip2 on macOS:
  uses_from_macos "bzip2"
  # To require the perl formula only when building or testing on Linux:
  uses_from_macos "perl" => [:build, :test]
  # To require the curl formula on Linux and pre-macOS 12:
  uses_from_macos "curl", since: :monterey
  #
  #############################################################################


  #############################################################################
  # from https://github.com/Homebrew/homebrew-core/blob/main/Formula/c/c-blosc2.rb
  #
  on_macos do
    depends_on "llvm" => :build if DevelopmentTools.clang_build_version <= 1400
  end
  #
  #############################################################################


  #############################################################################
  # from https://docs.brew.sh/Formula-Cookbook#specifying-other-formulae-as-dependencies
  #
  depends_on "httpd" => [:build, :test]
  depends_on xcode: ["9.3", :build]
  depends_on arch: :x86_64
  depends_on "jpeg"
  depends_on macos: :high_sierra
  depends_on "pkg-config"
  depends_on "readline" => :recommended
  depends_on "gtk+" => :optional
  #
  option "with-foo", "Compile with foo bindings" # This overrides the generated description if you want to
  depends_on "foo" => :optional # Generated description would otherwise be "Build with foo support"
  #
  #############################################################################


  #############################################################################
  # from https://docs.brew.sh/Formula-Cookbook#handling-different-system-configurations
  #
  on_linux do
    depends_on "gcc"
  end
  #
  on_mojave :or_newer do # comment
    depends_on "gettext" => :build
  end
  #
  on_system :linux, macos: :sierra_or_older do # comment
    depends_on "gettext" => :build # comment
  end
  #
  on_macos do # comment
    on_arm do
      depends_on "gettext" => :build
    end
  end
  #
  #############################################################################


  #############################################################################
  # from https://rubydoc.brew.sh/Formula#depends_on-class_method
  #
  # :build means this dependency is only needed during build.
  depends_on "cmake" => :build
  # :test means this dependency is only needed during testing.
  depends_on "node" => :test
  # :recommended dependencies are built by default. But a --without-... option is generated to opt-out.
  depends_on "readline" => :recommended
  # :optional dependencies are NOT built by default unless the auto-generated --with-... option is passed.
  depends_on "glib" => :optional
  # If you need to specify that another formula has to be built with/out certain options (note, no -- needed before the option):
  depends_on "zeromq" => "with-pgm"
  depends_on "qt" => ["with-qtdbus", "developer"] # Multiple options.
  # Optional and enforce that "boost" is built using --with-c++11.
  depends_on "boost" => [:optional, "with-c++11"]
  # If a dependency is only needed in certain cases:
  depends_on "sqlite" if MacOS.version >= :catalina
  depends_on xcode: :build # If the formula really needs full Xcode to compile.
  depends_on macos: :mojave # Needs at least macOS Mojave (10.14) to run.
  # It is possible to only depend on something if build.with? or build.without? "another_formula":
  depends_on "postgresql" if build.without? "sqlite"
  #
  #############################################################################
end
