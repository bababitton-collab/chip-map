"""Development probes. Not part of the build, and not part of the engine.

These answer questions about a data vendor -- which exchanges a subscription
covers, which company has a US depositary line -- and they carry the curated
hints and control lists that go with one particular map. That is exactly the
domain vocabulary the engine must not hold, so they live out here beside the
video renderer rather than inside chains/.

Run them by hand. Nothing in chains/ imports them.
"""
