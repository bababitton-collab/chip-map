"""A living map of the AI chip supply chain.

Who holds each chokepoint, who is trying to break it, and which question
gets answered on which day. Every claim in the map carries a source URL;
"estimate" means no source was found.

This package builds the whole thing from two public APIs and the curated
map in data/. It imports nothing outside itself and reads no path outside
this repository -- pinned mechanically in tests/test_isolation.py -- which
is what lets the weekly build run on a CI runner rather than on a laptop.

It is a map of exposures. It is not a trading signal, not investment
advice, and not a recommendation to anyone.
"""
