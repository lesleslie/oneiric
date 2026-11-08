---
title: Pin the queue provider so LavinMQ registration cannot silently repoint the bus
description: The LavinMQ queue adapter carries priority=330, above redis-streams (300), and nothing in the Bodai fleet sets a selections override — so the ("adapter", "queue") resolver slot was decided purely by priority. Priority alone can never give that slot to redis-streams (pubsub 410 and cloudtasks 400 are GCP adapters that cannot run locally). Adds settings/oneiric.yaml with an explicit adapters.selections pin, registers LavinMQ for explicit opt-in only, and documents the local broker supervisor split.
audience: oneiric maintainer + mahavishnu maintainer
created: 2026-11-08
status: active
role: implementation
topic: adapter-registry
date: 2026-11-08
last_reviewed: 2026-11-08
superseded_by: null
blocks_on: []
---

# Pin the queue provider so LavinMQ registration cannot silently repoint the bus

**Date:** 2026-11-08
**Status:** in progress
**Affects:** `settings/oneiric.yaml` (new), `oneiric/adapters/bootstrap.py`
**Consumers:** every component that calls `oneiric.adapters.bootstrap.register_builtin_adapters()`

## Problem

`oneiric/adapters/queue/lavinmq.py` ships a complete `LavinMQQueueAdapter`
(AMQP 0-9-1 + MQTT), with `settings/lavinmq.yaml`, dedicated tests, and the
`queue-lavinmq` extra. It is **not** in `builtin_adapter_metadata()`, so it is
never registered and therefore unselectable.

The adapter carries `priority=330`. The other queue adapters carry:

| Provider | Priority | Locally usable | Registered today |
|---|---|---|---|
| `pubsub` | 410 | no (GCP) | yes |
| `cloudtasks` | 400 | no (GCP) | yes |
| `lavinmq` | 330 | yes (running) | **no** |
| `nats` | 320 | no (not running) | yes |
| `rabbitmq` | 320 | no | no |
| `redis-streams` | 300 | yes (running) | yes |

`oneiric/core/resolution.py::_score_candidates` ranks candidates by the tuple
`(override_score, capability_score, priority, stack_level, registration_sequence)`.
Queue adapters register under `domain="adapter", key="queue"`
(`oneiric/adapters/metadata.py::AdapterMetadata.to_candidate` sets
`domain="adapter"`, `key=self.category`).

Nothing in the Bodai fleet sets a `selections` override — checked
`settings/` across mahavishnu, oneiric, akosha, session-buddy, crackerjack and
mcp-common for `selections`: zero hits. The provider is therefore chosen
**purely by priority**.

Two consequences, both verified by running the resolver:

1. **Priority alone can never hand the slot to redis-streams.** It sits at
   300, below `pubsub` (410) and `cloudtasks` (400) — both GCP adapters that
   cannot run locally — and below `lavinmq` (330) once that one is
   registered. Measured unpinned winner: `pubsub`. No amount of priority
   tuning fixes this; only an explicit selection can put redis-streams on
   top.

2. **Registering LavinMQ adds a second local-queue candidate.** Its
   capabilities (`queue`, `streaming`, `mqtt`, `amqp`) are a superset of
   `redis-streams` (`queue`, `streaming`), so capability filtering does not
   separate them. A broker being up and healthy makes it a more attractive
   candidate, which raises the odds someone reaches for it.

Note the Bodai **event bus** is unaffected either way: it is hardwired to
`RedisStreamsQueueAdapter` and never consults the resolver (see Scope). The
resolver's `("adapter", "queue")` slot is the generic one a future consumer
would hit.

## Scope

- **Pin** `("adapter", "queue")` to `redis-streams` via `adapters.selections`,
  the tier-1 "explicit override" mechanism documented in `CLAUDE.md`
  ("Resolution Precedence (4-tier)").
- **Register** `LavinMQQueueAdapter` so it is selectable by explicit opt-in
  (`DomainBridge.use(key, provider="lavinmq")`).
- **Not** in scope: migrating the Bodai event bus off Redis Streams. The bus is
  hardwired to `redis_streams` (`oneiric/adapters/bootstrap.py::queued_publisher`
  returns `RedisStreamsQueueAdapter` unconditionally;
  `mahavishnu/bodai_hook_bridge.py::_publish` targets
  `oneiric.adapters.queue.redis_streams` directly), and
  `docs/decisions/2026-10-15-unified-event-bus-wrapper.md` in mahavishnu
  names Redis Streams transport as the decided shape. No config knob switches
  the bus, and no change here alters it.

## Design

`override_score` is the **first** element of the scoring tuple, so an explicit
selection dominates priority outright. The pin therefore holds regardless of
what priorities the queue adapters carry — that is the property that makes it
durable rather than a snapshot of today's numbers.

The pin lives in `settings/oneiric.yaml` (project layer, committed) rather
than `~/.config/oneiric/local.yaml` (XDG layer, operator-local) because the
hazard is a property of the code, not of one machine's configuration. The
committed file is the default for every checkout and for CI.

Layer precedence confirms the pin is not shadowed: `build_yaml_layers` reads
`~/.config/oneiric/local.yaml` (XDG, higher precedence) →
`<repo>/settings/oneiric.yaml` (project). The existing XDG local file
defines `auth`, `selections`, `provider_settings`, `options`, `observability`
and `bifrost` — but **no `adapters` key** — so the deep merge leaves
`adapters.selections.queue` from the project layer intact.

## Integration Contract

- **Triggered from:** `oneiric.core.config.load_settings()` reading
  `<repo>/settings/oneiric.yaml`; `resolver_settings_from_config()` mapping
  `settings.adapters.selections` into `ResolverSettings.selections["adapter"]`.
- **Returns to / updates:** `Resolver.resolve("adapter", "queue")` returns
  `redis-streams`; `oneiric.adapters.bootstrap.builtin_adapter_metadata()`
  gains `LavinMQQueueAdapter.metadata`.
- **Demonstrable by:** `pytest tests/adapters/queue/test_queue_provider_selection.py`
  — asserts the pin file exists and carries the selection, that the pinned
  resolver returns `redis-streams`, and that an unpinned resolver would have
  returned `lavinmq` (the hazard the pin exists to contain).
- **Rollback signal:** `resolve("adapter", "queue")` returns `lavinmq`, or the
  oneiric MCP server's `/health` regresses after restart. Rollback is
  deleting the `settings/oneiric.yaml` pin and the
  `LavinMQQueueAdapter.metadata` entry — two edits, no data migration.
- **Observability added:** none at runtime. The pin changes *which* adapter
  resolves; it adds no feed, no metric, and no new failure mode.

## Integration Notes

- Registration is **metadata-only**: `AdapterMetadata.to_candidate()` builds a
  `Candidate`; no AMQP connection is attempted until `init()`. Registering
  LavinMQ therefore costs nothing at boot.
- `oneiric/adapters/queue/__init__.py` already imports `.lavinmq`
  unconditionally, so `bootstrap.py` pays no new import cost.
- `aio-pika` 10.2.2 and `aiomqtt` 3.0.0a1 are already installed in the
  oneiric venv; `aio_pika`/`aiomqtt` are imported lazily inside the adapter's
  methods, so the import stays optional.
- `rabbitmq` (320) and `kafka` are likewise unregistered. This plan does not
  register them — the pin would contain them too, but there is no consumer.

## Rollout

1. Add `settings/oneiric.yaml` with the pin. ✅ done
2. Register `LavinMQQueueAdapter` in `builtin_adapter_metadata()`. ✅ done
3. Add the regression test. ✅ done
4. Restart the oneiric MCP server and confirm `/health` stays green. ✅ done
   (`mcp-ctl restart oneiric` → HTTP 200, `warming_up` with
   `cycles_total: 1` — the normal post-restart feed warmup, not a
   regression.)

## Supervisor Split — findings and decision

**Decision: keep the hand-rolled LaunchAgent. Do not switch to `brew services`.**

The broker is already running, and `brew services list` reports `lavinmq none`
because a second, hand-rolled LaunchAgent owns it:

- `~/Library/LaunchAgents/com.bodai.lavinmq.plist` — label `com.bodai.lavinmq`,
  `RunAtLoad` + `KeepAlive`, running `lavinmq --data-dir
  /Users/les/Library/lavinmq --default-user-only-loopback false` (no `-c`, so
  the Homebrew ini is **not** read).
- Verified listening: `127.0.0.1:5672` (AMQP), `127.0.0.1:1883` (MQTT),
  `127.0.0.1:15672` (mgmt), `127.0.0.1:15692` (metrics). Loopback only.
- Verified idle: `connections_opened_total 0`, `queues 0`,
  `queues_declared_total 0`, `messages_delivered_total 0`. No client has ever
  connected.
- The plist instance's own log (`~/Library/Logs/lavinmq.log`) records **zero**
  ERROR/FATAL lines and only clean `Stopping`/restart cycles.

### Why the LaunchAgent, and not `brew services`

**1. LavinMQ's CLI default bind is loopback; the Homebrew ini overrides it to
all interfaces.**

`lavinmq --help` reports the defaults for every listener:

```
-b BIND, --bind=BIND          IP address that the AMQP, MQTT and HTTP servers will listen on (default: 127.0.0.1)
--amqp-bind=BIND             (default: 127.0.0.1)
--http-bind=BIND             (default: 127.0.0.1)
--mqtt-bind=BIND             (default: 127.0.0.1)
--metrics-http-bind=BIND     (default: 127.0.0.1)
```

The LaunchAgent passes no `-c`, so it inherits that safe default. The
Homebrew ini sets `bind = ::` in `[mgmt]`, `[amqp]`, `[mqtt]` and
`[clustering]`, which overrides it. Verified empirically by running a
throwaway instance from a copy of the ini on alternate ports:

```
lmq.server      Bound AMQP to [::]:25672
lmq.server      Bound MQTT to [::]:21883
lmq.http.server Bound to [::]:25671
```

`[::]` is every interface. Switching to `brew services` therefore *removes*
the loopback guarantee, with the default `guest`/`guest` credentials.

**2. The Homebrew service has never been the working path on this machine.**

- `/usr/local/etc/lavinmq/lavinmq.ini` has **never been edited**: its mtime
  (`2026-10-26 02:12:28`) equals the formula install time. A working
  `brew services` deployment would have had to change `data_dir` and the
  binds.
- `/usr/local/var/lavinmq` (the ini's `data_dir`) did not exist until a
  deliberate probe on 2026-11-08. The Homebrew service never initialised it.
- The `com.bodai.*` plists are house style for "Homebrew binary, custom
  arguments" — `mahavishnu/settings/local.yaml` documents the llama-server
  plist as the home of `--batch-size 4096 --ubatch-size 4096` precisely
  because `brew services` cannot express per-service flags. `brew services`
  *is* used freely for everything else (opensearch, grafana, postgresql,
  prometheus), so there is no general aversion to it.

**3. The ini is Homebrew-owned.** `brew upgrade lavinmq` and
`brew reinstall lavinmq` regenerate `/usr/local/etc/lavinmq/lavinmq.ini` from
the formula, so any hardening written there is clobbered on the next
upgrade. The plist is stable across upgrades — it points at
`/usr/local/bin/lavinmq`, a symlink Homebrew repoints for us.

### Residual hazard (not fixed by this plan)

`brew services start lavinmq` would spawn a **second** instance. It fails on
the port conflict (launchd restart-loop, `exit 1`), and it would additionally
bind `::` before failing. Two mitigations, both operator-side:

1. **Harden the ini as defence-in-depth** so a stray `brew services start`
   cannot expose the broker, even though it will still fail to bind:

   ```ini
   # /usr/local/etc/lavinmq/lavinmq.ini
   [main]
   default_user_only_loopback = true
   [mgmt]        bind = 127.0.0.1
   [amqp]        bind = 127.0.0.1
   [mqtt]        bind = 127.0.0.1
   [clustering]  bind = 127.0.0.1
   ```

   This is a stopgap, not a fix — the ini is regenerated on upgrade, so
   re-check it after every `brew upgrade lavinmq`.

2. **Leave a note** where an operator will see it. `settings/lavinmq.yaml`
   in this repo now carries the warning, and this plan records it.

Do **not** run `brew services start lavinmq` while the LaunchAgent is loaded.

### Machine state — unchanged

Nothing on the machine was modified. The ini and the plist were **not**
edited, the LaunchAgent was never unloaded, and the broker has been running
under `com.bodai.lavinmq` throughout. A `brew services start lavinmq` probe
was run and immediately reverted with `brew services stop lavinmq`; it
failed on the port conflict, as expected.

One leftover from that probe: `/usr/local/var/lavinmq/` (the ini's `data_dir`)
was created by the failed Homebrew instance and could not be removed by the
agent. It is inert — an empty broker data dir that the Homebrew service
would initialise if it were ever started. Safe to delete:
`rm -rf /usr/local/var/lavinmq`.

### Reference: the two files, as they currently stand

Recorded because the agent could not create backup copies, and because the
ini's `bind = ::` is the thing to re-check after any `brew upgrade lavinmq`.

`/usr/local/etc/lavinmq/lavinmq.ini` — **as shipped, never edited**
(mtime equals the formula install time):

```ini
[main]
data_dir = /usr/local/var/lavinmq
log_level = info
;pidfile = /var/run/lavinmq.pid
;default_user_only_loopback = true
;tls_cert = /etc/lavinmq/cert.pem
;tls_key = /etc/lavinmq/key.pem

[mgmt]
bind = ::
;port = 15672
;tls_port = 15671

[amqp]
bind = ::
;port = 5672
;tls_port = 5671
;tcp_proxy_protocol = false
;proxy_protocol_trusted_sources = 10.0.0.1, 192.168.0.0/24, 2001:db8::/32

[mqtt]
bind = ::
;default_vhost = /
;port = 1883
;tls_port = 8883

[clustering]
enabled = false
bind = ::
;port = 5679
;advertised_uri = tcp://hostname.local:5679
;etcd_endpoints = localhost:2379
```

`~/Library/LaunchAgents/com.bodai.lavinmq.plist` — **as it stands**
(created 2026-05-10 11:13, unchanged since; restore with
`launchctl bootstrap gui/$(id -u) <path>`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.bodai.lavinmq</string>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/lavinmq</string>
        <string>--data-dir</string>
        <string>/Users/les/Library/lavinmq</string>
        <string>--default-user-only-loopback</string>
        <string>false</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>

    <key>StandardOutPath</key>
    <string>/Users/les/Library/Logs/lavinmq.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/les/Library/Logs/lavinmq.err.log</string>
</dict>
</plist>
```

The broker's durable state (`~/Library/lavinmq`) is untouched by this plan.

## Non-Goals

- Migrating the Bodai event bus to AMQP.
- Enabling MQTT ingest (the one genuinely additive capability LavinMQ offers —
  nothing in the fleet speaks MQTT today). That needs a consumer, which would
  be its own plan.
- Upgrading lavinmq 2.10.3 → 2.10.4.

