"""Model Context Protocol server for the Bio Pipeline Manager.

Exposes the project's HTTP API (pipelines, jobs, job definitions, published
jobs, runs, queues, schedules, type library, users, packages) as MCP tools so an
agent or LLM — e.g. Claude Desktop / Cowork — can read, create, update, and run
these entities.
"""

__version__ = "0.1.0"
