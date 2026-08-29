# Oneiric Admin Shell

`oneiric.admin_shell.AdminShell` is the shared base class for every
Bodai Core 7 admin shell. Subclasses extend it with component-specific
namespace helpers, magics, and banner text.

## Layout

```text
AdminShell (base, in oneiric)
├── MahavishnuShell   (mahavishnu — adds %repos, %workflow magics)
├── DharaShell        (dhara — adapter inventory, storage state)
├── SessionBuddyShell (session-buddy — channel/session inspection)
├── AkoshaShell       (akosha — distributed intelligence stubs)
└── CrackerjackShell  (crackerjack — quality-gate helpers)
```

## When to subclass

- If your repo needs to add IPython magics for in-shell navigation,
  subclass `AdminShell` and add them to the subclass.
- If your repo only needs the standard namespace (`settings`, `app`,
  `logger`), construct `AdminShell(component_name=...)` directly.

## Cross-component admin shells

All 5 per-repo admin shells share the `AdminShell` base class. See
`mahavishnu/docs/ADMIN_SHELL.md` for the most fully-developed reference
(MahavishnuShell adds `%repos`, `%workflow` magics).