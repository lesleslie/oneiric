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

## Supervisor Split — findings and remaining steps

The broker is **already running**, but not under `brew services`. `brew
services list` reports `lavinmq none` because a second, hand-rolled
LaunchAgent owns it:

- `~/Library/LaunchAgents/com.bodai.lavinmq.plist` — label `com.bodai.lavinmq`,
  `RunAtLoad` + `KeepAlive`, running `lavinmq --data-dir
  /Users/les/Library/lavinmq --default-user-only-loopback false` (no `-c`, so
  the Homebrew ini is **not** read).
- Verified listening: `127.0.0.1:5672` (AMQP), `127.0.0.1:1883` (MQTT),
  `127.0.0.1:15672` (mgmt), `127.0.0.1:15692` (metrics). Loopback only.
- Verified idle: `connections_opened_total 0`, `queues 0`,
  `queues_declared_total 0`, `messages_delivered_total 0`. No client has ever
  connected.

So the hazard is not "the broker is down" — it is that `brew services start
lavinmq` would spawn a **second** instance against the same ports.

### The Homebrew ini binds to every interface

Verified empirically by running a throwaway instance from a copy of
`/usr/local/etc/lavinmq/lavinmq.ini` on alternate ports:

```
lmq.server      Bound AMQP to [::]:25672
lmq.server      Bound MQTT to [::]:21883
lmq.http.server Bound to [::]:25671
```

`[::]` is all interfaces. The shipped ini has `bind = ::` in `[mgmt]`,
`[amqp]`, `[mqtt]` and `[clustering]`, and `default_user_only_loopback` is
commented out. The hand-rolled LaunchAgent is loopback-only only because it
runs **without** `-c`, so it never reads that ini.

**Consequence:** switching the supervisor to `brew services` without first
hardening the ini would expose AMQP, MQTT and the management API on every
network interface, with the default `guest`/`guest` credentials. The ini must
be hardened *before* the switch, not after.

### Remaining steps (require operator action)

Two operations are outside the agent's permitted scope — `launchctl` is not
in the permission allowlist, and `/usr/local/etc/**` is not writable by the
Edit tool. Run these in order:

```bash
# 1. Harden the Homebrew ini: bind every listener to loopback.
#    (edit /usr/local/etc/lavinmq/lavinmq.ini)
#      [main]    default_user_only_loopback = true
#      [mgmt]    bind = 127.0.0.1
#      [amqp]    bind = 127.0.0.1
#      [mqtt]    bind = 127.0.0.1
#      [clustering] bind = 127.0.0.1

# 2. Stop the hand-rolled instance and unload it.
launchctl bootout gui/$(id -u)/com.bodai.lavinmq

# 3. Remove its autostart plist.
rm ~/Library/LaunchAgents/com.bodai.lavinmq.plist

# 4. Hand the supervisor to Homebrew.
brew services start lavinmq

# 5. Verify: loopback-only binds, no second instance, metrics live.
brew services list | grep lavinmq
lsof -nP -iTCP -sTCP:LISTEN | grep lavinmq
curl -s http://localhost:15692/metrics | grep lavinmq_version
```

### Rollback references

No backup files were created (the agent's file-creation step was denied), so
the pre-change contents are recorded here verbatim.

`/usr/local/etc/lavinmq/lavinmq.ini` — **before**:

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

`~/Library/LaunchAgents/com.bodai.lavinmq.plist` — **before** (restore with
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

