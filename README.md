# pymss-plugins

Official plugin registry and plugin collection for [pymss](https://github.com/pymss-project/pymss).

This repo does two things:

1. **`registry.json`** — the catalog `pymss install <name>` fetches. It maps short plugin names to their source (git URL, or a subdirectory of this repo).
2. **`plugins/`** — the official plugins themselves, one subdirectory per plugin.

## Install a plugin

```sh
pymss install loudnorm        # resolves via registry.json
pymss plugins list            # show installed plugins + load status
```

## Available plugins

| Name | Capability | Description |
|---|---|---|
| [`loudnorm`](./plugins/loudnorm) | `lufs_normalize` | LUFS-based loudness normalization (broadcast/streaming standard) |

## Write a plugin

A plugin is a Python package that calls `pymss.plugins.register_capability` (and optionally `register_node` / `register_cli`) at import time. Drop it under `plugins/<name>/` with an `__init__.py`, add an entry to `registry.json`, and send a PR.

Minimal plugin:

```python
# plugins/myplugin/__init__.py
from pymss.plugins import register_capability

@register_capability("myplugin_thing")
def thing(audio, sample_rate, strength=0.5):
    ...  # numpy audio in, numpy audio out
```

See [plugins/loudnorm](./plugins/loudnorm) for a full example with a capability, a workflow node, and dependency declaration.

## Plugin dependencies

Each plugin declares its own dependencies in its `pyproject.toml` (or `requirements.txt`). pymss does not auto-install them — install them yourself, e.g. `pip install pyloudnorm`. A plugin that fails to import reports a clear error via `pymss plugins list`.
