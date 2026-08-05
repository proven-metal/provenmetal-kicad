"""ProvenMetal KiCad plugin.

Reads a KiCad project's BOM, pushes it to ProvenMetal Central for sourcing, and
reports whether every part is in stock or sourceable within a week.

The package is split so the pure logic (fields, grouping, verdict, api) has no
dependency on KiCad's IPC library or any GUI toolkit and can be unit-tested
standalone; only kicad_env, ui and entry touch KiCad/wx.
"""

__version__ = "0.1.7"

# The plugin identifier, matching plugin.json. Used for the KiCad settings path
# and as a namespace for credential/config storage.
IDENTIFIER = "com.provenmetal.kicad"
