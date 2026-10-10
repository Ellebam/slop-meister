# Codex plugins

Optional. This keeps the `gopls-lsp` plugin available to Codex from a local marketplace, so short Codex runs never wait on a Git refresh of the plugin catalog. It only matters for Go work in Codex. Slopmeister does not install or manage any of it, the files below are the operator's own Codex settings.

[Overview](../README.md) · [All documentation](README.md)

## Set it up

1. Check which plugins you already use from the `claude-plugins-official` marketplace with `codex plugin list --marketplace claude-plugins-official --json`. Every one you still need must go into the local catalog too.
2. Pick a stable folder as the marketplace root. Copy each plugin from a trusted installed version into `./plugins/<name>` under it, manifest and license included.
3. Write `.agents/plugins/marketplace.json` in that root with the marketplace name `claude-plugins-official` and a local `gopls-lsp` entry pointing at `./plugins/gopls-lsp`.
4. Point Codex at the root in `~/.codex/config.toml`, with its absolute path. If a Git-backed `[marketplaces.claude-plugins-official]` table exists, replace it with this one.

```toml
[marketplaces.claude-plugins-official]
source_type = "local"
source = "/absolute/path/to/local-marketplace"

[plugins."gopls-lsp@claude-plugins-official"]
enabled = true
```

5. Confirm with `codex plugin list --marketplace claude-plugins-official --json`. On a fresh Codex home, install the plugin first with `codex plugin add gopls-lsp@claude-plugins-official`.

## Good to know

- The local copy only changes when you replace it. Updating the plugin is a deliberate copy, never automatic.
- Codex sessions that are already running may keep the old marketplace until they exit.
- The key names come from the [Codex configuration reference](https://developers.openai.com/codex/config-reference) and the [local marketplace guide](https://developers.openai.com/plugins/build/plugins).
