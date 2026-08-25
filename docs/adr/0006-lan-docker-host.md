# ADR-0006: Shared LAN Docker host for Postgres / pgvector

## Status

Accepted

## Context

The project is constrained to PostgreSQL with pgvector, Docker, and self-hostable
operation. The developer's workstation is not the only place containers run: a
machine on the local network already hosts databases for other projects.

## Decision

Run this project's Docker services — starting with PostgreSQL + pgvector — on a
**shared LAN Docker host**, not on the laptop's Docker Desktop by default.

Connection strings and Compose port bindings come from **local configuration**
(`docs/INFRASTRUCTURE.local.md` and/or `.env.local`), never from committed
files. Tracked docs describe the policy and placeholders only; see
[../INFRASTRUCTURE.md](../INFRASTRUCTURE.md).

Choose a host port that does not collide with other containers on that machine.
Prefer image `pgvector/pgvector:pg17` and a dedicated container/database for
this project.

## Consequences

- Development and later RAG/ingestion work can use one durable Postgres
  instance reachable from machines on the LAN.
- The laptop need not keep heavy DB containers running locally.
- Committed Compose / `.env.example` files must use placeholders
  (`DOCKER_HOST`, `HOST_PORT`), not real LAN addresses.
- Network availability of the LAN Docker host becomes a dependency for anything
  that needs the database.
- Real IP addresses, port maps, and credentials stay out of git history going
  forward; operators keep them in the gitignored local file.
