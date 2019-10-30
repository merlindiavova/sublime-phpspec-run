# Sublime phpspec-run

A small package around the phpspec run command. This PACKAGE helps you speedup your phpspec testing workflow.

> Please note: This package does not come with default keybindings

## Commands

### Run a spec (file)
 - Open the command pallet (Windows, Linux: `Ctrl+Shift+P`, MacOS: `⇧⌘P`)
 - Select `PHPSpec Run: Spec`

Equal to running ```$ bin/phpspec run spec/ClassNameSpec.php```

### Run spec nearest to the cursor
 - Place cursor inside or on a specification
 - Open the command pallet (Windows, Linux: `Ctrl+Shift+P`, MacOS: `⇧⌘P`)
 - Select `PHPSecp Run: here`

Equal to running ```$ bin/phpspec run spec/ClassNameSpec.php:56{specification line number}```

### Run Directory
 - Open the command pallet (Windows, Linux: `Ctrl+Shift+P`, MacOS: `⇧⌘P`)
 - Select `PHPSpec Run: Directory`

Equal to running ```$ bin/phpspec run spec/{folder}```

### Run all specs
 - Open the command pallet (Windows, Linux: `Ctrl+Shift+P`, MacOS: `⇧⌘P`)
 - Select `PHPSpec Run: Suite`

Equal to running ```$ bin/phpspec run```

### Rerun last spec
 - Open the command pallet (Windows, Linux: `Ctrl+Shift+P`, MacOS: `⇧⌘P`)
 - Select `PHPSpec Run: Rerun`

> Package inspired by [PHPUnit Kit](https://github.com/gerardroche/sublime-phpunit)

> The package provides the same functionality as my [phpspec-run](https://github.com/merlindiavova/phpspec-run) for VSCode
