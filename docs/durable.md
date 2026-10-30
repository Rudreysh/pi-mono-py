# Pi Durable

The current TypeScript tree is **pi v1.0.4**, plus commits that landed after that release and are still listed as unreleased. That version is not named Durable.

**Durable** is one package inside pi: `@earendil-works/pi-durable`, currently also at 1.0.4. It is marked experimental. Its API can change between releases. The package is a crash-safe agent runtime. The interactive coding agent you run with `pi` is still the older session loop in `packages/coding-agent`. Durable is the runtime the project is building so a conversation can survive the process dying in the middle of a turn.

A second new package, `@earendil-works/pi-env`, is the remote half of that idea: the same file and shell operations on another machine, reached over SSH. Durable calls those operations an **environment**. pi-env is one environment that happens to be remote.

## The problem it solves

The coding agent today appends messages to a session file and calls the model in-process. If the process exits while a tool is running, or while the model stream is open, that turn is gone. The transcript may contain the user message and not the answer. Starting pi again does not continue the tool call.

Durable reverses the order. It writes the intent to storage first, then does the work, then writes the result. Reopening the same storage and calling `resume()` continues from the last committed step. Nothing is shown to a watcher until that commit is stored.

## The pieces

One open storage plus the code that runs agents on it is a **harness**. Every change goes through one line of atomic commits.

A **conversation** is a transcript of immutable **entries**. `root()` creates the root conversation the first time and returns the same one after a restart. A handle holds no transcript in memory. You compare conversations by id. The model sees entries from the newest reset onward.

An entry is one record: a user message (`pi.user`), a model response (`pi.assistant`), a tool result (`pi.tool-result`), a system-prompt change (`pi.system`), a reset (`pi.reset`), a compaction, or a kind you define.

A **commit** is the only write. One callback can append entries, edit documents, and create tasks. The storage stores all of that or none of it.

A **document** is typed JSON stored beside the transcript and edited inside a commit. Built-in documents include:

| Document | What it holds |
|---|---|
| `pi.agent` | Model, thinking level, extensions, tools, instructions, working directory |
| `pi.provider` | A UUID the provider uses for prompt-cache and session affinity |
| `pi.live` | The generation and tool calls that are running |
| `pi.inbox` | Queued submissions |
| `pi.usage` | Token and cost totals |

A **task** is a state machine that checkpoints every step. The harness runs an answer as built-in tasks: `pi.generation` calls the model and owns one `pi.tool` task per tool call. If the process dies during a tool, a tool declared `replay: "safe"` runs again. Any other tool becomes an `interrupted` error result, with whatever output was already committed.

A **submission** is something you hand the conversation: user input, or an entry to write. `wait()` resolves when it is answered or has failed. The same `requestId` after a restart returns the existing submission instead of sending the prompt twice.

A **turn** is one model response plus its tool calls. A **run** is every turn from an input until the final answer. The conversation is busy while a run is going.

An **extension** is a named bundle of tools, system-prompt sections, hooks, wrappers, and tasks. The process installs extensions in a **registry**. The registry is not stored. Each conversation stores the extension names it selected.

An **agent** is what that conversation runs with. `configure()` changes it in one commit.

Every async call takes a Chord **context**. That context carries cancellation. Cancelling a wait cancels the wait, not the work.

## One question, written down

```text
submit(input) → pi.user
  pi.generation → pi.system (only if the prompt or tools changed), pi.assistant (tool calls)
    pi.tool × n → pi.tool-result × n
  pi.generation → pi.assistant (answer) → submission done
```

`Harness.open(storage)` opens a session. `MemoryStorage` keeps it in memory and disappears with the process. `openNodeSqliteStorage(file)` and `openNodeJsonlStorage(directory)` keep it. `openDurableObjectSqliteStorage` uses the SQLite storage of one Cloudflare Durable Object. The name "Durable Object" is Cloudflare's. It is not a second pi product. One process owns a storage at a time. There is no lock across processes.

SQLite runs in WAL mode with `synchronous = NORMAL`. A process crash keeps committed work. A power loss can drop the newest commit. JSONL can pass `{ fsync: true }` to flush before each commit marker.

`harness.resume()` starts the scheduler for work the last process left unfinished. Submitting or waiting starts it too. Each conversation has its own provider session id. A fork or a child gets a new one.

## Tools and the environment

Tools do not touch the disk themselves. They go through the call's **environment**: read, write, list, and run a shell. The default environment is the local machine (`NodeExecutionEnv`). pi-env supplies the same operations on a remote machine.

`read`, `write`, `edit`, and `bash` ship as the `CodingTools` extension. As of 1.0.4 there is also `createPowerShellTool()`, which runs `pwsh` or Windows PowerShell through an argv array so no extra shell parses the command.

A tool can stream with `api.output()`. If `execute()` returns no content, that stream is the result. A result can report usage, which is added to `pi.usage`. `control: { terminate: true }` on every result of a round ends the run without another model request.

The system prompt is rendered from the selected extensions' sections before each request. Only a section or tool set that changed is written again as a `pi.system` entry, so the provider prompt cache stays warm. A section that returns a new string every time, such as the current clock, defeats that cache.

## Ownership

A conversation or a task can own other work.

Aborting a conversation withdraws queued inputs, aborts the tasks of the current run, and resolves when the conversation is idle. Abort runs bottom-up: owned work finishes aborting before the owner's abort handler runs.

A subagent tool creates a child conversation inside the same commit that remembers the child, then submits to it. A crash during a replay-safe tool finds that same child instead of creating a second one. Aborting the parent aborts the child.

`{ background: true }` is a boundary. Work it owns survives the parent's abort and does not keep the parent busy.

A task can also wait on child tasks. While it waits it runs no code. `allSettled` resumes when every child is done. `failFast` aborts the rest at the first failure. A task that has decided its outcome but still owns running work is `completing`. It becomes terminal only when that work is done.

`harness.taskGraph()` is a live tree of those tasks for a panel or a debugger. A task appears in the commit that creates it and leaves in the commit that makes it terminal. After a restart, tasks that were `running` show as `pending` until they run again.

## What changed in this release

v1.0.2 was the previous tree this repo had merged. Durable's own additions since then:

**1.0.3.** The environment can open one file for bounded reads, list a directory a page at a time, run a program as an argv array (no shell), and watch files. Shell output can omit bytes outside the window the caller keeps, so a remote environment does not transfer output that will be thrown away. The `read` tool reads the header, one line scan, and the lines it shows, instead of loading the whole file. Progress snapshots no longer move the start of a later output window.

**1.0.4.** `createPowerShellTool()`. The `read` tool tolerates a file that grows while it is read, such as a live log. Watching a directory that is replaced at the same path installs a new watcher. A symlink target reports changes to the file it points at. A permission failure is `permission_denied` instead of looking like a missing path.

**After 1.0.4, still unreleased.** These are on `main` and are in this checkout:

- Scans of conversations, entries, tasks, and submissions can go oldest-first or newest-first. A cursor continues in the order it was created with.
- `TaskRuntime.context()` takes the cutoff as `{ at }`, matching `Conversation.context()`.
- `Conversation.context(context, { at })` returns the model context as of an earlier entry, the view a fork at that entry would start with, without creating a conversation.
- Tools and hooks receive `models`, the same catalog and credentials generation uses.
- Task records store `startedAt` and `endedAt`. Assistant messages and tool results store `durationMs`, how long the model request or `execute()` took. Interrupted calls have no duration.
- An idle conversation keeps its last context read in memory for `settings.contextRetentionMs` (default ten minutes). The next request scans only entries committed since that read. `0` drops the cache as soon as the conversation is idle.
- The first system message, and the baseline after compaction or reset, leads the model context. Providers that can change tools mid-conversation, such as Anthropic, then keep the prompt cache instead of rewriting the whole prompt.
- `openDurableObjectSqliteStorage()` is the Cloudflare adapter.

pi-env 1.0.4 is the first release of that package: a daemon on the remote machine, SSH bootstrap that verifies the daemon by SHA-256 before starting it, native file watches, and output windows so dropped command output is not transferred.

## What the Python tree has

`python/src/pi_mono/durable/` is only the storage foundation: document definitions, an in-memory commit log, and a session transaction. It does not run generations, tools, watches, or resume. The Python app you start with `python -m pi_mono.coding_agent` is the coding-agent session, not this harness.

Porting Durable itself means porting the harness, the task scheduler, the environment, and then pi-env. That is a separate project from matching a CLI flag or a retry rule. Those smaller v1.0.4 behavior changes are tracked in `parity.md`.
