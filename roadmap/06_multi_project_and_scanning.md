# Multi-Project Support & Offline Scanning

## Project registration

A "project" is just a registered root folder (`projects` table, [03_sqlite_schema.md](03_sqlite_schema.md)).
Registering a project does not scan anything by itself — scanning is a separate, explicit step,
so registering 10 projects up front doesn't trigger 10 expensive scans.

## The offline scanner

Walks a project's `root_path`, calls the `DXFExtractor` implementation of `DrawingExtractor`
(see [04_drawing_extractor_design.md](04_drawing_extractor_design.md)) on every `.dwg` file found,
and writes the result into the `drawings`/`entities`/`entity_properties`/`entity_geometry`/
`relationships` tables. Runs with **zero running AutoCAD instances** — this is pure file parsing.

## Incremental rescan

Before re-extracting a file: check `file_size` + `file_modified_at` first (a cheap OS `stat`
call); only compute a fresh `file_hash` if those differ; only re-run the extractor if the hash
actually changed. Unchanged files are skipped entirely on a rescan. No background file watcher —
this tool is invoked on demand, not run as a daemon; add one later only if that changes.

## The rule that actually solves the "100 files" concern

**Don't open 100 drawings.** Not in AutoCAD, not via COM, not as "workers." The scanner already
indexed everything once; from then on, every request is answered by querying SQLite, and only
the files an operation actually needs ever get opened live.

```
User: "Increase P-101 discharge pipe by 50mm everywhere"

SQLite already knows:
    P-101 appears in → PID-001.dwg, GA-004.dwg, PIPE-012.dwg

        ↓
    Open only those 3 files (explicitly, by path — see 05_structured_operations_and_editing.md)
        ↓
    Modify → validate → save
        ↓
    The other 97 files in the project are never touched.
```

## The read/write parallelism split — the one thing every proposal in this discussion had to be
corrected on

It's tempting to draw "4-8 worker pool" and assume it applies uniformly. It doesn't, because
reading and writing have fundamentally different constraints:

| | Reads (metadata extraction) | Writes (actual edits) |
|---|---|---|
| Goes through AutoCAD? | No — `DXFExtractor`, pure file parsing | Yes — one live COM session |
| Parallelizable? | **Yes** — `concurrent.futures.ProcessPoolExecutor` across many files at once, safely | **No**, not meaningfully — one AutoCAD process, one automation channel, calls processed strictly one at a time regardless of how many documents happen to be open |
| Bottleneck at scale | None to speak of, for hundreds of files | Whatever it takes to open/edit/save N *affected* files, one at a time — and N is small because the scanner already narrowed it down |

**Practical implication:** build the extraction/scan side with real parallelism from the start
(it's basically free — no shared state, no AutoCAD, no license concerns). Build the write side as
a single-consumer queue. Do not spend effort building a "4-worker CAD pool" against one AutoCAD
instance — it will not give you 4x throughput, because most COM calls implicitly act on
`ActiveDocument` and switching between documents to fake concurrency just adds overhead without
adding parallelism.

## Anti-patterns to avoid

- Opening a folder of files in the AutoCAD UI just to "let the app see them" — the scanner never
  needs AutoCAD open at all.
- Running multiple AutoCAD.exe processes to get write-side parallelism for a single-user desktop
  tool — this burns license seats and doesn't match the actual bottleneck (COM channel
  serialization happens per-process anyway; you'd need N licensed instances to get real
  N-way write parallelism, which is a real cost for a marginal, rarely-needed benefit at this
  project's scale).
