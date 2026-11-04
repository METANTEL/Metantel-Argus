# The memory

Argus never puts a site's raw feeds in a model's context. It compiles them into a memory and every agent works through that
memory: it asks for exact figures, searches the notes, reads what other agents wrote, and coordinates with the others. This
document says which memory is the reference, what the harness asks of a memory, and how to put another behind it.

## The reference: Metantel's Managed Memory Harness

[`argus/memory/metantel.py`](../argus/memory/metantel.py) is the client of Metantel's **Managed Memory Harness**, the memory
Argus is built and measured on. For a client it is the easy path: send it the data, and describe workflow changes in plain
language ([`argus/boards.py`](../argus/boards.py) drafts them from a sentence); the rest is managed. A space on it and its keys
come from Metantel; set them as `ARGUS_SPACE`, `ARGUS_INGEST_KEY` and `ARGUS_SERVE_KEY` (see
[`argus/config.py`](../argus/config.py)). What it does inside is Metantel's own business: Argus relies only on the verbs
below.

`DryEdip` in the same module records what would be sent and answers reads with nothing, for trying a pipeline without
touching a space.

## What the harness asks of a memory

Two protocols, in [`argus/memory/__init__.py`](../argus/memory/__init__.py).

**`Memory`** reads and writes the site's knowledge. The reasoning agent, the replay and the section managers use only these.

| Verb | Does |
|---|---|
| `search(query, limit, codes, passages)` | items and records that answer a request in plain words, best first, with the item each came from and its tags |
| `items(limit, codes)` | what the memory holds, newest first |
| `tables()` | the tables and their columns (name, kind, role) |
| `query(plan, question, table, budget)` | an exact answer over every row: counts, sums, latest state, durations, gaps, traces; `text` for reading and `result` with the rows |
| `ingest(name, text, kind, tags)` | put an item in under a stable name; ingesting the name again replaces it, so a rerun does not duplicate |
| `ingest_table(name, header, rows, tags)` | create or replace a table from rows |
| `append(artifact, rows)` | add rows to a table |

**`Coordination`** is how agents coordinate through the memory (the hive, [`HIVE.md`](HIVE.md)).

| Verbs | Does |
|---|---|
| `presence`, `leave`, `roster` | who is there, in what role and section |
| `intend`, `clear` | say what you will change and why before you do; a collision with another agent's intent comes back at once |
| `claim`, `state`, `release` | take a shared copy of a named resource at a version; take it to write, and every other holder's copy goes stale; ask whether your copy is still current |
| `send`, `inbox` | a direct line between agents, with receipts |
| `card`, `cards`, `resolve` | what agents cannot settle goes to people as a decision with each agent's position; a person resolves it |
| `signals` | what happened since a cursor |
| `add_facts`, `facts`, `correct` | facts: one dated sentence each, with subjects; a correction is a new fact and the old one is kept, marked replaced |

## What the harness relies on

- **Idempotent writes.** Items are named; ingesting a name replaces it. A replay can be run again.
- **Exact answers.** Counts, latest state, durations and gaps are computed by the memory over every row, not estimated from
  what a search returned. This is what lets an answer cite where each number came from.
- **Time on everything.** Queries take a time window and an `as_of`; documents carry a `t=` tag. The agent keeps itself at a
  moment (`Agent(bounded=True)`): it caps every window at that moment and drops anything stamped later, so a replayed site can
  be asked "what did we know then?".
- **Claims that go stale.** A write claim on a resource marks every other holder's copy stale, and a holder can ask. That is
  how one agent's correction reaches every agent that relied on the old picture.

## Putting another memory behind the harness

Implement the seven `Memory` verbs and pass the object where Argus takes `Edip()`: the [`Agent`](../argus/agent.py) and the
[`Replay`](../argus/replay.py) take the protocol, not the class. The hive's members, managers and supervisors
([`argus/hive/`](../argus/hive)) take a `Coordination`; [`Link`](../argus/hive/link.py) is its implementation for the Managed
Memory Harness, and a backend brings its own. Raise `EdipError(status, body)` for failures (404 for a table that does not
exist yet; the agent reads it as "nothing there").

The smallest useful memory, enough to replay a feed into, is a few lines
([`tests/test_memory.py`](../tests/test_memory.py) runs this one):

```python
class Notebook:
    def __init__(self):
        self.tables, self.items = {}, {}

    def ingest(self, name, text, kind="document", tags=None):
        if kind == "table":
            self.tables[name] = [line.split(",") for line in text.strip().splitlines()]
        else:
            self.items[name] = text

    def append(self, name, rows):
        self.tables[name] += [[str(v) for v in r] for r in rows]
```

A memory the reasoning agent can work from also needs `search`, `tables` and `query`. The plans the agent writes for `query`
are described in the `table_query` tool of [`argus/agent.py`](../argus/agent.py); a backend that cannot run one should raise
`EdipError` so the agent tries another way.

## What goes to a model

Only what a tool returned: an exact answer, the passages of a search, a fact. Never the feed. Development runs on Muse Spark
1.3 Contributor, which lets Meta train on what it is sent, so it is for public data only; a deployment on private data sets
`ARGUS_CHAT_MODEL=muse-spark-1.3` (Standard) or runs the models on its own hardware.
