# Bundled midea-lan library

This directory contains the pure-Python `midea-lan` wheel used by this custom
integration. It is loaded before any globally installed copy so Home Assistant
startup does not fetch the midea-lan source from Git.

The exact source commit, artifact hash, and license are recorded in
`PROVENANCE.json`. Rebuild the wheel from that commit and compare its SHA-256
before replacing it.
