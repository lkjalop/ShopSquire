"""External-source connectors (EDGE, not agnostic core).

Connectors know about the outside world (retailer domains, feed formats, transports). They stay OUT of
``_CORE_MODULES``: core consumes the opaque rows they write (competitor_observation, ...), never the
connector itself. Region/vertical specifics live in config JSON, not code.
"""
