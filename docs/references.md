# Reference and licensing audit

> The pinned upstream/license audit below records the original implementation. For current installation evidence and working RS-422/polling setup see [research](research.md) and the installation-evidence section at the end.

Inspected 2026-10-18, before writing implementation code. New runtime and tests
are independently written for this project and licensed under [MIT](../LICENSE).
No upstream implementation, fixtures, images or dependency has been vendored or
ported. This audit records engineering provenance, not a formal clean-room process.

## Upstream references

| Project and pinned revision | License evidence | Use in this project |
| --- | --- | --- |
| [qix67/comfortzone_heatpump](https://github.com/qix67/comfortzone_heatpump/tree/c0a896db8163d721e373c983bc651e7863e8c28b) — `c0a896db8163d721e373c983bc651e7863e8c28b` | [LICENSE](https://github.com/qix67/comfortzone_heatpump/blob/c0a896db8163d721e373c983bc651e7863e8c28b/LICENSE) contains GPL version 3. | Protocol facts and controller-version distinctions only. No C++ code, structures, decoder routines or tables copied/translated into the MIT implementation. |
| [Staffolainen/czbridge](https://github.com/Staffolainen/czbridge/tree/f690212a21153cf25b6c7663210ce477f840cabd) — `f690212a21153cf25b6c7663210ce477f840cabd` | Complete repository tree has no license file; inspected README and `app.py` provide no license grant. | Reference envelope, CRC parameters, exact temperature register/length/offsets and evidence that Moxa UDP can be observed. New framing, decoder and diagnostics implementation; no source or tests copied. |
| [Ithanil/loggamera-heatpump-hass](https://github.com/Ithanil/loggamera-heatpump-hass/tree/faab4b82d81acbba2f5420752c5f1c5d900dc1f6) — `faab4b82d81acbba2f5420752c5f1c5d900dc1f6` | [MIT license](https://github.com/Ithanil/loggamera-heatpump-hass/blob/faab4b82d81acbba2f5420752c5f1c5d900dc1f6/LICENSE), copyright 2025 Svante Jacobsen and 2026 Jan Kessler. | Entity behavior/design reference: units, temperature/measurement metadata, device grouping and stable identifiers. No source copied; cloud fields are not bus mappings. |

The qix67 [frame descriptions](https://github.com/qix67/comfortzone_heatpump/blob/c0a896db8163d721e373c983bc651e7863e8c28b/comfortzone_frame.h)
and [configuration](https://github.com/qix67/comfortzone_heatpump/blob/c0a896db8163d721e373c983bc651e7863e8c28b/comfortzone_config.h)
distinguish software 1.60, 1.80 and 2.21. This first decoder does not implement that
complete register catalog. The separately proposed 2.50 changes are not included.

The czbridge [application](https://github.com/Staffolainen/czbridge/blob/f690212a21153cf25b6c7663210ce477f840cabd/app.py)
is the reference for the 21-byte header, total-length byte at offset 10,
CRC-8/MAXIM, `r` response/register guard, 114-byte payload and eight signed
little-endian temperature fields starting at payload offset 52. It does not
establish these facts for the owner's EX35.

The previous integration's [sensor implementation](https://github.com/Ithanil/loggamera-heatpump-hass/blob/faab4b82d81acbba2f5420752c5f1c5d900dc1f6/custom_components/loggamera_heatpump/sensor.py)
uses cloud capability/value keys. Similar names do not establish equivalence to
the local bus. Local entities will have their own IDs, preserving the existing
cloud entities and history until a separately assessed migration.

If future work copies MIT source, retain its notices with the copied material.
GPL or unlicensed upstream source must not be imported under this project's MIT
license; any proposed incorporation needs a separate licensing decision.

## Current official integration documentation

Consulted directly on 2026-10-18:

- [Home Assistant manifest](https://contributors.home-assistant.io/core/integrations/manifest/): custom integration version, config flow and `local_push` classification.
- [Home Assistant config flow](https://contributors.home-assistant.io/core/integrations/config-flow/): configuration, duplicate detection and stable IDs; an IP address is not a suitable device unique ID.
- [Home Assistant data updates](https://contributors.home-assistant.io/core/integrations/fetching-data/): a coordinator can accept push updates without polling.
- [Home Assistant sensor entities](https://contributors.home-assistant.io/core/entities/sensor/): native units, device/state classes and read-only measurement entities.
- [HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/): one integration in root `custom_components/`, all runtime files inside it, manifest and brand assets.
- [HACS general requirements](https://www.hacs.xyz/docs/publish/start/): repository-root `hacs.json`, README, version/release conventions and minimum Home Assistant version metadata.

Package 3 rechecked the official
[config entry lifecycle](https://contributors.home-assistant.io/core/integrations/config-entries/),
[options flow](https://contributors.home-assistant.io/core/integrations/options-flow/),
[reconfiguration](https://contributors.home-assistant.io/core/integrations/reauth-reconfigure/),
push-coordinator and sensor documentation. It uses `entry.runtime_data`,
`OptionsFlowWithReload`, separate network reconfiguration and a coordinator with
no polling interval. The current form API uses `probatio`.

The HA tests use [pytest-homeassistant-custom-component 0.13.373](https://pypi.org/project/pytest-homeassistant-custom-component/0.13.373/),
which pins **Home Assistant 2026.10.2**, with Python 3.14.7. The installed HA source
was also inspected for coordinator cleanup, config-entry error/reload handling and
current registry APIs. Reading documentation alone was not treated as validation;
tests exercise the actual HA flow manager, sensor platform, registries and state
machine. No upstream source was copied, and no deployed HA frontend or hardware
installation has been tested.

CRC cross-check: [CRC RevEng catalogue, CRC-8/MAXIM-DOW](https://reveng.sourceforge.io/crc-catalogue/all.htm#crc.cat.crc-8-maxim-dow).
The algorithm parameters and standard check vector are used, not its source code.

Package 2 also consulted Python's official [transport/protocol lifecycle](https://docs.python.org/3/library/asyncio-protocol.html)
and [event-loop API](https://docs.python.org/3/library/asyncio-eventloop.html).
The receiver binds only a local endpoint, handles `connection_lost` and
`error_received`, and closes its datagram transport explicitly. UDP loss may be
silent; error callbacks are not treated as a complete loss detector.

Package 4 rechecked the manifest, HACS integration/general requirements and
[HACS validation action](https://www.hacs.xyz/docs/publish/action/) on 2026-10-19.
The [current HA brand documentation](https://contributors.home-assistant.io/core/integrations/brands/)
places custom integration images in the component's own `brand/` directory.
The bundled icon is original MIT project artwork, with its SVG source retained;
no vendor, HA or upstream-project logo was copied. Official
[hassfest action configuration](https://github.com/home-assistant/actions/tree/master/hassfest)
and the `actions/checkout` and `actions/setup-python` v6 definitions were also
checked. The prepared workflows have not run; see the package 4 validation record.

## Installation evidence, 2026-10-25

Owner captures now establish the `0b15`/117-byte EX35 layout, sensor offset 55,
TE24 hot water, and standalone read requests. See [research](research.md) and
[fixture provenance](../tests/data/README.md). Earlier electrical assumptions and
synthetic-only statements above describe the prior reference audit. No additional
upstream source code was copied for the captured layout or polling implementation.
The correct vendor reference is the [NPort 5100A series QIG v3.5](https://moxa.com/getmedia/b43d0252-add7-4bf4-987b-0f6ad8811de2/moxa-nport-5100a-series-qig-v3.5.pdf),
not the P5150A guide. Moxa pinout/settings are documented facts; the unusual
adapter wiring is installation evidence, not a vendor recommendation.

## Monitor query research, 2026-10-26

The [query mapping](query-mapping.md) records the additional capture-derived
registers, field facts and unresolved operation fields. It also references the
unmerged 2.50 proposal at `d401d5fd141cc05f576462aa2cd9b33359f030ea`, inspected
for contiguous settings, calibration and UI layouts. Its `0b10` layout is not
identified with this EX35's `0b15` layout. The earlier statement that 2.50 changes
were not included describes the original implementation checkpoint. No upstream
source or tables were copied; new code is independently written using protocol
facts and the owner's fixtures, under the existing MIT license.
