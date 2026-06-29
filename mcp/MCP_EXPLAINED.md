# Understanding MCP — Concept, Protocol, and Transport

A plain-language explainer for how a **Model Context Protocol (MCP)** server and
client work together with an LLM, using this project's `bio-pipeline-manager`
server as the running example.

---

## 1. The problem MCP solves

An LLM (Claude, etc.) can only do one thing on its own: **read text and write
text**. It cannot open a file, call an API, or run code. To make it *useful*
against real systems, you have to give it a way to *act* — and let it discover
what actions are available.

Before MCP, every app wired up every tool by hand: each LLM host needed custom
code for each external system. That's an **N×M** integration problem (N hosts ×
M tools). MCP replaces it with **one standard interface** — like USB-C for AI
tools. Build one MCP server for your system, and *any* MCP-capable host can use
it.

```
  Without MCP (N×M custom glue)         With MCP (one standard)

  Host A ── glue ── Tool 1              Host A ─┐
  Host A ── glue ── Tool 2              Host B ─┼── MCP ──┬── Tool 1 (server)
  Host B ── glue ── Tool 1              Host C ─┘         ├── Tool 2 (server)
  Host B ── glue ── Tool 2                                └── Tool 3 (server)
   ... every pair wired by hand          one protocol, plug & play
```

---

## 2. The four roles

It's tempting to picture "LLM ↔ server," but there are really **four** players:

| Role | What it is | In this project |
|---|---|---|
| **LLM** | The model. Reads/writes text; decides *what* to do. | Claude |
| **Host** | The app the LLM runs in. Orchestrates everything. | Claude Desktop / Cowork |
| **MCP client** | A connector *inside the host*, one per server. Speaks MCP. | provided by the host |
| **MCP server** | Your program. Publishes tools and *does* the work. | the `mcp/` package |

The crucial rule: **the LLM never talks to the server directly.** The model only
ever emits text ("I want to call tool X"). The *host* turns that into a real call
through the *client*, and feeds the result back to the model.

```
            ┌──────────────────────────────────────────┐
            │   HOST  (Claude Desktop / Cowork)        │
            │                                          │
   you ───► │   ┌────────┐   decides    ┌────────────┐ │   transport   ┌───────────────┐   HTTP    ┌──────────────┐
            │   │  LLM   │ ───────────► │ MCP client │ │ ════════════► │  MCP server   │ ════════► │ bioPipeline  │
            │   │(Claude)│ ◄─────────── │            │ │  (stdio/HTTP) │ (mcp/ package)│  /api/v1  │   backend    │
            │   └────────┘   result     └────────────┘ │               └───────────────┘           └──────────────┘
            └──────────────────────────────────────────┘
                         ▲                                          ▲                          ▲
                 model picks the tool            speaks the MCP protocol (JSON-RPC)   translates MCP → REST
```

- **LLM brings judgment** — *which* tool, *what* arguments, from a fuzzy request.
- **Server brings capability** — the deterministic muscle that actually runs it.
- Neither can do the job alone.

---

## 3. The protocol layer (what is said)

MCP is built on **JSON-RPC 2.0** — small, structured request/response messages.
The protocol defines the *vocabulary*, and it is **identical on every transport**.

### The handshake (once, at connect time)

```
client → server   initialize          "hi, I speak MCP v2025-06-18, here's who I am"
server → client   (capabilities)      "hi, I'm bio-pipeline-manager; I offer tools"
client → server   tools/list          "what can you do?"
server → client   (tool descriptors)  [ run_published_job, publish_published_job, ... ]
```

The host hands that tool list to the LLM as context. Now the model *knows the
tools exist* — but they're just a menu of names, descriptions, and input shapes.
**This is the only thing the model sees**, which is why each tool has a clear,
action-oriented description (e.g. *"Run a published job by supplying its field
`values`."*). Good descriptions → correct tool selection.

### A tool call (every time the model acts)

```
client → server   tools/call { name: "run_published_job",
                               arguments: { published_job_id: "...", values: {...} } }
server → client   { content: [ ... result ... ] }      // or an error
```

### Beyond tools

MCP servers can expose three kinds of capability (this server uses the first):

- **Tools** — actions the model can invoke (our 71 endpoints-as-tools).
- **Resources** — read-only data the host can load as context (files, records).
- **Prompts** — reusable prompt templates the user can pick.

---

## 4. The transport layer (how it's carried)

The **protocol** is the messages; the **transport** is the pipe those messages
travel through. MCP defines **two standard transports** — *both* are "the
standard." Choosing one is about **where the host runs relative to the server**.

```
   ┌────────────────────────── stdio ──────────────────────────┐
   │  Host launches the server as a LOCAL SUBPROCESS and pipes │
   │  JSON-RPC over stdin/stdout. Requires same machine.       │
   │                                                           │
   │     Host  ──spawn──►  server process                      │
   │     Host  ──stdin──►  server                              │
   │     server ──stdout──►  Host                              │
   └───────────────────────────────────────────────────────────┘

   ┌─────────────────── streamable HTTP ───────────────────────┐
   │  Server is a NETWORK ENDPOINT at a URL. Host calls it over│
   │  HTTP. Works when the host is somewhere else (the cloud). │
   │                                                           │
   │     Host  ──HTTPS POST /mcp──►  server endpoint           │
   │     server ──response/stream──►  Host                     │
   └───────────────────────────────────────────────────────────┘
```

| | **stdio** | **streamable HTTP** |
|---|---|---|
| Server location | Same machine as host | Anywhere reachable by URL |
| How it's launched | Host spawns a subprocess | You run it; host connects to a URL |
| Used by | **Claude Desktop** (local app) | **Cowork / claude.ai** (cloud) |
| Auth | Implicit (local, trusted) + env-var creds | **Must** authenticate the endpoint (token / OAuth) + TLS |
| In this project | `server.py` → `bio-pipeline-mcp` | `http_server.py` → `bio-pipeline-mcp-http` |

### Why Cowork needs HTTP (the key insight)

Cowork doesn't run on your laptop — it runs in Anthropic's cloud. There is **no
local process for it to spawn** and no stdin/stdout to attach to. The only way
something remote can reach a server on your side is **over the network**. That's
not a different protocol — it's the *same* MCP, the *same* tools — just carried
over HTTP instead of a local pipe. Because the endpoint now lives on a network,
it must be authenticated (a shared-secret bearer token here) and served over TLS.

---

## 5. End-to-end request lifecycle

```mermaid
sequenceDiagram
    actor U as User
    participant L as LLM (Claude)
    participant H as Host (Desktop / Cowork)
    participant C as MCP client
    participant S as MCP server (mcp/)
    participant A as bioPipeline API

    rect rgb(238,244,255)
    note over H,S: Connect time — discovery (once)
    C->>S: initialize
    S-->>C: capabilities + serverInfo
    C->>S: tools/list
    S-->>C: [ run_published_job, ... ]
    C-->>H: tool menu
    H-->>L: tools available as context
    end

    rect rgb(238,255,244)
    note over U,A: Per request — invocation
    U->>L: "run the QC pipeline on sample A"
    L-->>H: intent: call run_published_job(values=…)
    H->>C: tools/call
    C->>S: tools/call (JSON-RPC, over the transport)
    S->>A: POST /published-jobs/catalog/{id}/runs
    A-->>S: 201 run record
    S-->>C: tool result (JSON)
    C-->>H: result
    H-->>L: result
    L-->>U: "Done — run started; here's the status."
    end
```

A single user turn may loop through several tool calls (call → read result →
call again) before the model writes its final answer.

---

## 6. The trust boundary

The model can **ask** for anything — but the **server decides what's actually
possible**. That makes the server the security boundary:

- This server logs into the backend with one account; its **role** gates the
  surface (admin = everything, researcher = catalog/run only). An admin tool
  requested under a researcher account simply fails with 403.
- Credentials live only in the server's environment and are **never** returned by
  any tool.
- Over HTTP, the endpoint itself is authenticated (bearer token) and should be
  TLS-only — it is a fully-privileged gateway to the backend.

---

## 7. How it maps to this project

```
mcp/bio_pipeline_mcp/
  server.py       ← FastMCP instance + 71 @tool functions   (stdio transport)
  http_server.py  ← same instance, served over HTTP + auth   (HTTP transport)
  client.py       ← logs into the backend, holds the session cookie, calls /api/v1
  config.py       ← env-driven settings for both transports
```

- **Server** = the `mcp/` package — each tool is a thin wrapper over one backend
  route. It shares no code with the backend; it only speaks HTTP to `/api/v1`.
- **Client + Host** = Claude Desktop / Cowork — you don't write these.
- **Transport** = stdio for Desktop (`bio-pipeline-mcp`), streamable HTTP for
  Cowork (`bio-pipeline-mcp-http`). **Same 71 tools either way.**

### One-sentence summary

> **MCP is a standard menu-and-order protocol:** the server publishes a menu of
> tools, the LLM (through the host) reads the menu and places orders on your
> behalf, and the server fills them — over whichever transport (local stdio or
> network HTTP) fits where the host is running.

---

*See [README.md](README.md) for setup/connect instructions and
[CLAUDE.md](CLAUDE.md) for the tool catalog and operational workflows.*
