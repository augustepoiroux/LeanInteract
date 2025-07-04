# Changelog

This page documents the notable changes to LeanInteract.

## v0.7.0 (July 04, 2025)

## What's Changed

* Check Lean version formatting by @sorgfresser in <https://github.com/augustepoiroux/LeanInteract/pull/27>
* Improve git-related operations by @augustepoiroux in <https://github.com/augustepoiroux/LeanInteract/pull/28>
    * `GitProject` has a `force_pull` argument to enforce pulling / reset if the project is already in the cache
    * Similarly, `LeanREPLConfig` has a `force_pull_repl` argument. Useful when working on a custom REPL living on an evolving git branch.
* Bump REPL to v1.0.12 by @augustepoiroux in <https://github.com/augustepoiroux/LeanInteract/pull/29>
    * `FileCommand` has now an `env` field <https://github.com/leanprover-community/repl/pull/99>
    * Various REPL fixes: <https://github.com/leanprover-community/repl/pull/106>, <https://github.com/leanprover-community/repl/pull/98>, <https://github.com/leanprover-community/repl/pull/72>
    * Syntax nodes now export a few more attributes <https://github.com/leanprover-community/repl/pull/89>
* New `LeanServer.get_memory_usage` method to monitor REPL memory usage.
* Add InfoTree pydantic models by @sorgfresser in <https://github.com/augustepoiroux/LeanInteract/pull/3>
    * Leverage the new exported attributes for syntax nodes <https://github.com/leanprover-community/repl/pull/89>

**Full Changelog**: <https://github.com/augustepoiroux/LeanInteract/compare/v0.6.3...v0.7.0>

## v0.6.3 (July 01, 2025)

## What's Changed

* Add support for Lean v4.22.0-rc1 and v4.22.0-rc2

**Full Changelog**: <https://github.com/augustepoiroux/LeanInteract/compare/v0.6.2...v0.6.3>

## v0.6.2 (June 30, 2025)

## What's Changed

* Add support for Lean v4.21.0

**Full Changelog**: <https://github.com/augustepoiroux/LeanInteract/compare/v0.6.1...v0.6.2>

## v0.6.1 (June 24, 2025)

## What's Changed

* Fix Lean version inference for `LocalProject` and `GitProject` by @augustepoiroux in <https://github.com/augustepoiroux/LeanInteract/pull/26>
* Fix `ResourceWarning` issues when killing the REPL
* Improve memory monitoring in `AutoLeanServer`

**Full Changelog**: <https://github.com/augustepoiroux/LeanInteract/compare/v0.6.0...v0.6.1>

## v0.6.0 (June 05, 2025)

## What's Changed

* Support for local / custom REPL + Lean versions up to v4.21.0-rc3 by @augustepoiroux in <https://github.com/augustepoiroux/LeanInteract/pull/21>
* Separate the session cache logic from `AutoLeanServer` by @sorgfresser in <https://github.com/augustepoiroux/LeanInteract/pull/18>
* Add documentation by @augustepoiroux in <https://github.com/augustepoiroux/LeanInteract/pull/19>
* Add support for modern Python Path by @augustepoiroux in <https://github.com/augustepoiroux/LeanInteract/pull/20>

**Full Changelog**: <https://github.com/augustepoiroux/LeanInteract/compare/v0.5.3...v0.6.0>

## v0.5.3 (May 18, 2025)

## What's Changed

* Add optional build boolean for LocalProject by @sorgfresser in <https://github.com/augustepoiroux/LeanInteract/pull/16>
* Slightly improve sorry detection in `lean_code_is_valid` by checking `message` instead of just `sorries` in REPL output.

**Full Changelog**: <https://github.com/augustepoiroux/LeanInteract/compare/v0.5.2...v0.5.3>

## v0.5.2 (May 01, 2025)

Introduce compatibility with Lean v4.19.0

**Full Changelog**: <https://github.com/augustepoiroux/LeanInteract/compare/v0.5.1...v0.5.2>

## v0.5.1 (April 30, 2025)

## What's Changed

* Add fix for non-respected timeout by @augustepoiroux in <https://github.com/augustepoiroux/LeanInteract/pull/13>
* Query Lake cache for all Project types by @habemus-papadum in <https://github.com/augustepoiroux/LeanInteract/pull/10>
* Bump REPL version to v1.0.7 fixing `"auxiliary declaration cannot be created when declaration name is not available"` in tactic mode for Lean <= v4.18.0 <https://github.com/leanprover-community/repl/issues/44#issuecomment-2814069261>

**Full Changelog**: <https://github.com/augustepoiroux/LeanInteract/compare/v0.5.0...v0.5.1>

## v0.5.0 (April 21, 2025)

## What's Changed

* Make LeanInteract cross-platform by @augustepoiroux in <https://github.com/augustepoiroux/LeanInteract/pull/4>
* Fix infotree parsing issue by @sorgfresser in <https://github.com/augustepoiroux/LeanInteract/pull/1>
* Implement `async_run` + make calls to the REPL thread-safe by @augustepoiroux in <https://github.com/augustepoiroux/LeanInteract/pull/2>

## v0.4.1 (April 18, 2025)

**Full Changelog**: <https://github.com/augustepoiroux/LeanInteract/compare/v0.4.0...v0.4.1>

## v0.4.0 (April 11, 2025)

**Full Changelog**: <https://github.com/augustepoiroux/LeanInteract/compare/v0.3.3...v0.4.0>

## v0.3.3 (April 04, 2025)

**Full Changelog**: <https://github.com/augustepoiroux/LeanInteract/compare/v0.3.2...v0.3.3>

## v0.3.2 (April 03, 2025)

**Full Changelog**: <https://github.com/augustepoiroux/LeanInteract/compare/v0.3.1...v0.3.2>

## v0.3.1 (April 02, 2025)

**Full Changelog**: <https://github.com/augustepoiroux/LeanInteract/compare/v0.3.0...v0.3.1>

## v0.3.0 (April 02, 2025)

**Full Changelog**: <https://github.com/augustepoiroux/LeanInteract/compare/v0.2.0...v0.3.0>

## v0.2.0 (March 18, 2025)

**Full Changelog**: <https://github.com/augustepoiroux/LeanInteract/commits/v0.2.0>

## Pre-release Development

For development history prior to the first release, please see the [GitHub commit history](https://github.com/augustepoiroux/LeanInteract/commits/main).
