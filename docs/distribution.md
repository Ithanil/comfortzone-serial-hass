# Distribution and release readiness

This is the root of
[Ithanil/comfortzone-serial-hass](https://github.com/Ithanil/comfortzone-serial-hass).
The initial snapshot contains the implementation, tests, tools, documentation and
distribution metadata, with display name **ComfortZone Serial** and domain
`comfortzone_serial`. The investigation repository's earlier history remains in
that repository. No HACS listing or release has been created.

## Installation boundary

For evaluation now, follow [manual installation](home-assistant.md). Copy the
entire `custom_components/comfortzone_serial/` directory, including `brand/`,
`translations/`, `telemetry/` and `LICENSE`. Nothing outside that directory is
needed by Home Assistant at runtime. Its manifest has no pip requirements.
Capture/replay commands, fixtures and development dependencies are not installed
into Home Assistant.

The metadata targets **Home Assistant 2026.10.2 or newer**; runtime tests currently
cover 2026.10.2 on Python 3.14. Older versions are unsupported. The protocol and
diagnostic tools separately support Python 3.13+. HACS metadata specifies the HA
minimum; a manual copy bypasses that HACS check, so check the HA version first.

The [HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/)
expect one integration under repository-root `custom_components/`. This standalone
repository has that layout; the investigation repository is not the HACS source.
The root-level `hacs.json` uses HACS's normal directory download, without a release
ZIP or generated runtime files.

## First release

Before the first release:

1. Publish the prepared initial snapshot on `main`, including dotfiles. Exclude
   virtual environments, caches, coverage output and private captures. The manifest
   links to this repository's documentation and issues.
2. HACS requires a public GitHub repository. Set a description, enable issues and
   add relevant topics such as `home-assistant`, `hacs`, `comfortzone` and `moxa`.
   See the [general HACS requirements](https://www.hacs.xyz/docs/publish/start/).
3. Enable Actions and run both included workflows. Require the tests, Ruff,
   hassfest and HACS validation to pass. Resolve validation failures before release.
4. Perform a manual install/configure/reload/remove test on an actual HA instance.
   Then verify installation and updating through HACS using the actual public
   standalone repository. This is distinct from the automated HA runtime tests.
5. Update [CHANGELOG.md](../CHANGELOG.md) and keep the release tag/version consistent
   with `manifest.json`. Version `0.1.0` is prepared but unreleased. A GitHub release
   is optional for HACS; if used, publish a release, not just a Git tag.
   Describe hardware validation accurately in its release notes.

After the public standalone repository exists, a user can add its URL in HACS's
**Custom repositories**, select **Integration**, download **ComfortZone Serial**,
restart HA and follow the setup guide. Do not use this investigation repository's
URL for that step. See [HACS custom repositories](https://www.hacs.xyz/docs/faq/custom_repositories/).

## Validation workflows

The files under `.github/` run in the standalone repository. GitHub does not run
them through the investigation repository's `integration/` checkout.

- `tests.yml` runs protocol/capture/replay tests on Python 3.13 and 3.14, the pinned
  Home Assistant harness on 3.14, Ruff and Python compilation. The protocol job
  disables automatic pytest plugin loading to isolate it from HA's fixtures.
- `validate.yml` runs the official hassfest action and the HACS action, with no
  ignored HACS checks. Repository metadata checks need the public repository.
- `dependabot.yml` proposes monthly action/development-dependency updates. Review
  HA harness upgrades together with their pinned HA version,
  the minimum version metadata and runtime tests.

Local test commands are in [home-assistant.md](home-assistant.md#development-verification).
Lint uses `python -m pip install -r requirements-lint.txt`, then `ruff check .`.
Official validator configuration follows [HACS's action guide](https://www.hacs.xyz/docs/publish/action/)
and the [Home Assistant hassfest action](https://github.com/home-assistant/actions/tree/master/hassfest).
Local JSON/layout/asset checks are not a substitute for these official validators.

## Brand asset and license

The house/temperature icon is original project artwork under the same MIT license
as the code. It is not a ComfortZone, Moxa or Home Assistant logo. The editable
source is [assets/icon.svg](../assets/icon.svg); the runtime ships the resulting
256×256 RGBA PNG at `custom_components/comfortzone_serial/brand/icon.png`.
This location follows [Home Assistant's custom integration brand documentation](https://contributors.home-assistant.io/core/integrations/brands/).

To regenerate it from this directory with librsvg installed:

```sh
rsvg-convert --width 256 --height 256 \
  --output custom_components/comfortzone_serial/brand/icon.png assets/icon.svg
```

The runtime includes an identical copy of the root MIT `LICENSE`, so the notice
travels with HACS and manual installations. No upstream artwork or code is bundled;
see the [reference audit](references.md).
