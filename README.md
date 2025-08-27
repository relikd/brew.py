# brew.py

A lightweight replacement for Homebrew

see [usage](#usage) below.


## Install

Copy `brew.py` to anywhere, where it can be found by your shell.
Or add a new path to your `$PATH`.

In your shell config (e.g., `.zprofile`) add

```sh
export BREW_PY_CELLAR=$HOME/any/path/you/like
```


## FAQ

### Why this project?

Well, I hate dependencies.
For years, I have been avoiding Homebrew because of the large codebase and because Homebrew installs a lot of stuff in a lot of different places.
And I did not want to audit every single installation.

Most of the time, I just need a single binary and thus fallback to downloading that binary manually.
That's how this script started – as a way to download a single binary.
And then it escalated quickly.
Now I am trying to copy some of the functionality of brew itself and the, once simple script, is growing into a full-fledged Homebrew-alternative suite.

I don't know if anybody can make use of this, but here you go.


### What is the scope?

I don't know yet.
Maybe I will add more features, and copy more of the original brew CLI.
But most importantly, it should be simple and dependency free.

brew.py focuses on:
- downloading pre-built binaries (bottles) from Brew.sh or GitHub registry
- re-link dynamic libraries (.dylib) to use relative paths
- provide a structure for other brew packages to link to shared libs

What brew.py does **NOT** do:
- build from source code
- search or browse packages (use Brew.sh for that)
- formula analysis & dependency checks (use Brew.sh to check if a package is suitable for your machine)
- cask management (beyond mere download)


## Usage

```
usage: brew.py [-h] [-q] [--version] command ...

A lightweight replacement for Homebrew

positional arguments:
  command
    info                List versions, dependencies, platforms, etc.
    home (homepage)     Open a project's homepage in a browser.
    fetch               Download bottle (binary tar) for package.
    list (ls)           List installed packages.
    deps                Show dependencies for package.
    uses                Show dependents of package (reverse dependencies).
    leaves              List installed packages that are not dependencies of
                        another package.
    missing             Check the given packages for missing dependencies. If
                        no packages are provided, check all kegs. Will exit
                        with a non-zero status if any are found to be missing.
    install             Install a package with all dependencies.
    uninstall (remove, rm)
                        Remove / uninstall a package.
    link (ln)           Link a specific package version (activate).
    unlink              Remove symlinks for package to (temporarily) disable
                        it.
    switch              Change package version.
    cleanup             Remove old versions of installed packages. If
                        arguments are specified, only do this for the given
                        packages. Removes all downloads more than 21 days old.
                        This can be adjusted with
                        $BREW_PY_CLEANUP_MAX_AGE_DAYS.

optional arguments:
  -h, --help            show this help message and exit
  -q, --quiet           reduce verbosity (-q or -qq)
  --version             show program's version number and exit
```
