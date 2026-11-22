"""Statement parsers: `parse(data: bytes)` per source, each with its own PARSER_VERSION.

Bump a module's PARSER_VERSION whenever its output for the same file changes, so data
parsed by different versions can be told apart (and reparsed) later.
"""
