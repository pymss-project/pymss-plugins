"""BPM and musical-key operations backed by the packaged rba CLI."""


def setup(plugin):
    from .backend.operations import setup as register_operations

    register_operations(plugin)
    return plugin
