# Troubleshooting

This guide covers common issues you might encounter when using LeanInteract.

## Common Issues

### Out of Memory Errors

**Symptoms**:

- The application crashes with memory-related errors
- Python process is killed by the operating system
- Error messages mentioning "MemoryError" or "Killed"

**Solutions**:

- Reduce parallel processing or increase system memory
- Limit the maximum amount of memory usage allocated to the REPL with `LeanREPLConfig`:

  ```python
  from lean_interact import AutoLeanServer, LeanREPLConfig
  server = AutoLeanServer(LeanREPLConfig(memory_hard_limit_mb=8192)) # Limit to 8GB
  ```

- If you are working with large files or complex proofs in a single session, consider breaking them into smaller, more manageable pieces.

### Timeout Errors

**Symptoms**:

- Commands take too long to execute
- Error messages mentioning "TimeoutError"

**Solutions**:

- Pass a higher timeout to `run()`/`async_run()`:

  ```python
  server = AutoLeanServer(LeanREPLConfig())
  result = server.run(Command(cmd="..."), timeout=60)
  ```

- Use `AutoLeanServer` for automatic recovery from timeouts:

  ```python
  server = AutoLeanServer(config)
  ```

- Break complex commands into smaller, more manageable pieces

### Long Waiting Times During First Run

**Symptoms**:

- Initial setup takes a long time
- Process seems stuck at "Downloading" or "Building"

**Solution**:
This is expected behavior as LeanInteract:

1. Downloads and sets up the specified Lean version
2. Downloads and builds Lean REPL
3. If using Mathlib, downloads it and instantiates a project using it (which is resource-intensive)

Subsequent runs will be much faster due to caching.

### Lake Update Errors

**Symptoms**:

- Error: `Failed during Lean project setup: Command '['lake', 'update']' returned non-zero exit status 1.`

**Solutions**:

- Update your `elan` version (should be at least 4.0.0):

  ```bash
  elan self update
  ```

- Check your project's lake file for errors
- Ensure Git is properly installed and can access required repositories

### Path Too Long Error (Windows)

**Symptoms**:

- On Windows, errors related to path length limitations
- Git errors about paths exceeding 260 characters

**Solutions**:
Enable long paths in Windows 10/11:

```powershell
# Run in administrator PowerShell
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -Value 1 -PropertyType DWord -Force
git config --system core.longpaths true
```

### Cache Issues

**Symptoms**:

- Unexpected behavior after upgrading LeanInteract
- Errors about incompatible versions

**Solution**:
Clear the LeanInteract cache:

```bash
clear-lean-cache
```

### Unexpected Lean error messages

**Symptom**:
LeanInteract returns error messages while the Lean code runs fine in VSCode.

**Solutions**:

- Check you are using the same Lean version in both environments
- If you are creating a temporary project using LeanInteract, make sure your dependencies are correctly set and compatible with the Lean version you are using
  - A frequent issue is forgetting to include `mathlib` in the dependencies:

    ```python
    config = LeanREPLConfig(
        project=TempRequireProject(lean_version="v4.19.0", require="mathlib")
    )
    ```

- Check if a similar [issue](https://github.com/leanprover-community/repl/issues) for the Lean REPL has been reported

### "'elan' is not recognized as an internal or external command"

**Symptom**:
Error when running LeanInteract on a new system

**Solution**:
Install Lean's version manager:

```bash
install-lean
```

## Getting Additional Help

If you encounter issues not covered in this guide:

1. Check the [GitHub repository](https://github.com/augustepoiroux/LeanInteract) for open issues
2. Open a new issue with:
    - A minimal reproducible example
    - Your operating system and Python version
    - LeanInteract version (`pip show lean-interact`)
    - Complete error message/stack trace
