help:
	@echo 'available commands: test, test-git, test-parser'

git-clone:
	git clone --depth 1 https://github.com/Homebrew/homebrew-core/ git-clone

test-git: git-clone
	python3 -c 'import test; test.testCoreFormulae()'

test-parser:
	python3 -c 'import test; test.testConfigVariations()'

test: test-git test-parser
