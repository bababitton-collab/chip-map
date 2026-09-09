"""Vendored HTTP clients.

Lifted from the shared ``core`` package this repository was split out of. It is
a copy, not a dependency: chip-map builds in CI from a checkout of itself and
nothing else, and a second repository on the import path would put that back.
The two copies are expected to drift; this one is the one this build uses.
"""
