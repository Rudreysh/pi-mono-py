# Python Port Parity Checklist

This document tracks behavioral parity between the TypeScript packages (`packages/*`) and the Python port (`python/src/pi_mono`). Use it when reviewing releases or planning follow-up work.

## Legend

| Status | Meaning |
|--------|---------|
| **Match** | Same behavior and API surface for the covered scope |
| **Partial** | Core behavior works; gaps remain in edge cases or polish |
| **Diverge** | Intentional difference (documented below) |
| **Missing** | Not yet ported |

## Packages

| Area | TS source | Python target | Status |
|------|-----------|---------------|--------|
| AI providers & models | `packages/ai` | `pi_mono.ai` | **Partial** | Catalog synced to TS v1.0.2; sampling by thinking level, capacity retries, Z.AI CN overflow. Codemode/classifiers/image unification remain gaps |
| Agent runtime | `packages/agent` | `pi_mono.agent` | **Partial** | `finishTurn` / `prepareRequest` / `thinkingLevel` on assistant messages; harness still has the pre-1.0 durable surface |
| Terminal UI | `packages/tui` | `pi_mono.tui` | **Partial** | Fullscreen alt-screen is a working subset (scroll/search/jump); not the full TS renderer |
| Coding agent CLI | `packages/coding-agent` | `pi_mono.coding_agent` | **Partial** | Fullscreen TUI, powershell, MCP stdio host; `.ts` extensions and Cursor protobuf remain divergences |
| Protocol | `packages/protocol` | `pi_mono.protocol` | **Partial** | CBOR + length-prefixed framing, protocol version 8 |
| Client | `packages/client` | `pi_mono.client` | **Partial** | Unix-socket remote client |
| Server | `packages/server` | `pi_mono.server` | **Partial** | Unix-socket remote server |
| Telemetry | `packages/telemetry` | `pi_mono.telemetry` | **Partial** | Noop + in-memory spans |
| Session backends | `packages/session-backends` | `pi_mono.session_backends` | **Partial** | SQLite session repo |
| Chord | `packages/chord` | `pi_mono.chord` | **Partial** | In-process context + replicated state; no plugin bundles |

## CLI & modes

| Feature | Status | Notes |
|---------|--------|-------|
| `parseArgs` / CLI flags | **Match** | Empty `--models` entries ignored (#10334); `--provider` requires `--model` (#10236) |
| Print mode (`-p`, `--print`) | **Match** | Text and JSON output |
| JSON event mode (`--mode json`) | **Match** | |
| RPC mode (`--mode rpc`) | **Match** | Preflight prompt semantics, `get_commands`, `parentSession` aligned with TS |
| Interactive TUI | **Partial** | Fullscreen/`tuiMode` alt-screen is available; editor-area selectors remain for overlays |
| `pi config` | **Match** | `-l` project-local scope, Tab switch, `--approve`/`--no-approve` |
| Session fork / resume / import | **Match** | |
| `pi update` self-update | **Partial** | CLI flags present; install path depends on distribution method; version-check failures skip update instead of forcing it |
| Export HTML / share | **Partial** | Export exists; share flow lighter than TS |

## Trust & security

| Feature | Status | Notes |
|---------|--------|-------|
| `ProjectTrustStore` inheritance | **Match** | |
| Trust-requiring resource detection | **Match** | |
| Interactive trust selector | **Match** | |
| `/trust` slash command | **Match** | |
| Extension `project_trust` event | **Match** | |
| `--approve` / `--no-approve` | **Match** | |

## Extensions

| Feature | Status | Notes |
|---------|--------|-------|
| Python extension loader | **Match** | `.py` extensions via `default(pi)` factory |
| Event hooks (`session_start`, `input`, etc.) | **Match** | Includes `agent_settled`, `before_provider_headers`, `api.exec()` |
| Tool registration | **Match** | |
| Entry / message renderers | **Match** | Display-only custom entries via `register_entry_renderer` |
| Shortcut registration + conflict detection | **Match** | |
| Extension UI (select/confirm/input/notify) | **Match** | Interactive + RPC bridge |
| TypeScript extension runtime | **Diverge** | Python port runs `.py` extensions only; TS extensions are not executed |
| npm extension packages | **Partial** | Package manager resolves extension paths; resource loader + settings wiring; `.py` only (TS npm extensions not executed) |

## Session storage

| Feature | Status | Notes |
|---------|--------|-------|
| JSONL session format | **Match** | |
| Labels | **Match** | |
| Custom entries | **Match** | |
| Branching / tree | **Match** | |
| Compaction | **Match** | |
| Session migration | **Partial** | Core paths covered; not every TS migration scenario |

## Tools

| Feature | Status | Notes |
|---------|--------|-------|
| read / write / edit / bash / grep / find / ls | **Match** | Bash uses `OutputAccumulator` + `fullOutputPath` when truncated | |
| `fd` / `rg` via tools-manager | **Match** | Auto-download on supported platforms |
| Image read pipeline (EXIF, convert) | **Match** | Wired into read tool + show-images selector |
| MCP tools | **Partial** | Stdio JSON-RPC MCP client/host; not the full TS manager |

## Interactive UI (P3 polish)

| Feature | Status | Notes |
|---------|--------|-------|
| Message rendering (thinking, tools, diffs) | **Match** | |
| Footer (cwd, tokens, context, cache hit rate) | **Match** | |
| Settings selector | **Match** | Phase 2 settings + show-images selector submenu |
| Theme picker | **Match** | Custom theme file watcher via `set_theme(..., enable_watcher=True)`; polling `FSWatcher` with error handler (#2791) |
| Session / model / OAuth selectors | **Match** | Scrollable model list with provider-first then model step; error/empty states; scoped-model reorder |
| User-message fork selector | **Match** | |
| Changelog / version check on startup | **Match** | |
| Clipboard images | **Partial** | Wayland/X11/macOS subprocess paths; platform-dependent |
| Thinking block toggle (`ctrl+t`) | **Match** | Rebuilds chat and preserves pending tools |
| Scoped model reorder | **Match** | Alt+Up/Down in scoped models selector |
| RPC embedder client (`RpcClient`) | **Match** | Fake-server integration tests |
| Terminal OSC background colors | **Match** | `terminal_colors.py` |
| Tool definition factories for extensions | **Match** | `create_read_tool_definition()` + wrapper helpers |
| Windows npm self-update quarantine | **Match** | `windows_self_update.py` |
| Package manager semver ranges | **Partial** | `max_satisfying()` for npm update checks; latest-version fallback uses semver max (not lexicographic) |

## AI / providers

| Feature | Status | Notes |
|---------|--------|-------|
| Provider modules | **Match** | Anthropic, OpenAI, Google, Bedrock, Mistral, etc. |
| Model catalog sync | **Match** | `python/scripts/generate_models.py` syncs from TS catalogs |
| OAuth flows | **Match** | Provider-specific; Copilot model picker filter included |
| Cursor auth | **Match** | CLI `agent login` via `/login`; stale OAuth in `auth.json` warned and cleared after CLI login |
| Cursor subscription proxy | **Diverge** | Python uses CLI bridge; TS has protobuf proxy path (see `python/docs/cursor.md`) |
| Image generation | **Match** | OpenRouter image provider |

## Testing

| TS suite area | Python tests | Status |
|---------------|--------------|--------|
| `args.test.ts` | `test_phase5_parity.py`, `test_coding_agent_cli.py` | **Match** (high-value cases) |
| `rpc.test.ts` | `test_coding_agent_rpc.py`, `test_rpc_client.py`, `test_rpc_prompt_response_semantics.py`, `test_phase5_parity.py` | **Match** (unit + fake-server RpcClient + preflight semantics) |
| `trust-manager.test.ts` | `test_phase5_parity.py`, `test_project_trust_p0.py` | **Match** |
| `extensions-runner.test.ts` | `test_phase3_extensions.py`, `test_phase5_parity.py` | **Partial** |
| `session-manager/*.test.ts` | `test_phase5_parity.py`, `harness/test_session.py` | **Partial** |
| `footer-width.test.ts` | `test_footer.py` | **Match** |
| `suite/regressions/4167-*` | `tests/suite/regressions/test_4167_*` | **Match** |
| `suite/regressions/3217-*` | `tests/suite/regressions/test_3217_*` | **Match** |
| `suite/regressions/5868-*` | `test_phase5_parity.py` | **Match** |
| `suite/regressions/5080-*` | `tests/suite/regressions/test_5080_*` | **Match** |
| `suite/regressions/5724-*` | `tests/suite/regressions/test_5724_*` | **Match** |
| `suite/regressions/5208-*` | `tests/suite/regressions/test_5208_*` | **Match** |
| `suite/regressions/5303-*` | `tests/suite/regressions/test_5303_*` | **Match** |
| `suite/regressions/5109-*` | `tests/suite/regressions/test_5109_*` | **Match** |
| `suite/regressions/2835-*` | `tests/suite/regressions/test_2835_*` | **Match** |
| `suite/regressions/3317-*` | `tests/suite/regressions/test_3317_*` | **Match** |
| `suite/regressions/2753-*` | `tests/suite/regressions/test_2753_*` | **Match** |
| `suite/regressions/3616-*` | `tests/suite/regressions/test_3616_*` | **Match** |
| `suite/regressions/5433-*` | `tests/suite/regressions/test_5433_*` | **Match** |
| `suite/regressions/3686-*` | `tests/suite/regressions/test_3686_*` | **Match** |
| `suite/regressions/3303-*` | `tests/suite/regressions/test_3303_*` | **Match** |
| `suite/regressions/5661-*` | `tests/suite/regressions/test_5661_*` | **Match** |
| `suite/regressions/3982-*` | `tests/suite/regressions/test_3982_*` | **Match** |
| `suite/regressions/2023-*` | `tests/suite/regressions/test_2023_*` | **Match** |
| `suite/regressions/3302-*` | `tests/suite/regressions/test_3302_*` | **Match** |
| `suite/regressions/3592-*` | `tests/suite/regressions/test_3592_*` | **Match** |
| `suite/regressions/2781-*` | `tests/suite/regressions/test_2781_*` | **Match** |
| `suite/regressions/2791-*` | `tests/suite/regressions/test_2791_*` | **Match** |
| `suite/regressions/2860-*` | `tests/suite/regressions/test_2860_*` | **Match** |
| `suite/regressions/3688-*` | `tests/suite/regressions/test_3688_*` | **Match** |
| `suite/regressions/5596-*` | `tests/suite/regressions/test_5596_*` | **Match** |
| `suite/regressions/1717-*` | `tests/suite/regressions/test_1717_*` | **Match** |
| Other `suite/regressions/*` | — | **Match** |

## CI

| Check | Status |
|-------|--------|
| `npm run check` + `npm test` | **Match** (existing `ci.yml`) |
| `pytest` | **Match** (added in `ci.yml`) |
| `ruff check` + `ruff format --check` (coding_agent) | **Match** (added in `ci.yml`) |
| `mypy` (P3 modules) | **Match** (added in `ci.yml`) |
| Python model catalog sync (`generate_models.py --check`) | **Match** (CI + release publish job) |
| Real-provider e2e (`PI_E2E_PROVIDER`) | **Partial** | Gated pytest marker in `test_e2e_providers.py` |

## v0.86.0–v1.0.2 ports

| Feature | Status | Notes |
|---------|--------|-------|
| `samplingParamsByThinkingLevel` | **Match** | OpenAI completions/responses/Azure + `models.json` overrides |
| Retry "model is at capacity" | **Match** | `#10278` |
| Z.AI CN `Prompt exceeds max length` | **Match** | `#10208` |
| `--models` empty/trailing comma | **Match** | `#10334` |
| `--provider` without `--model` errors | **Match** | `#10236` |
| Slash autocomplete after leading whitespace | **Match** | `#10218` |
| Bedrock `thinking.block_binding` drop stale blocks | **Match** | Adaptive models except Opus/Sonnet 4.6 and GovCloud |
| Default TUI mode fullscreen | **Match** | `tuiMode` unset → fullscreen |
| `quietStartup: "header"` | **Partial** | Settings + selector; startup banner still a subset of TS |
| Agent `finishTurn` / `prepareRequest` | **Match** | Replaces `shouldStopAfterTurn` |
| Assistant `thinkingLevel` | **Match** | Recorded on loop results |
| Codex default `gpt-6.1-sol` | **Match** | `default_model_per_provider` |
| Model catalog JSON | **Match** | `generate_models.py` exports `MODELS`/`IMAGE_MODELS` from `models.generated.ts` |
| Codemode / virtual models / classifiers | **Missing** | QuickJS sandbox and unified image/classifier runtime not ported |
| MCP CIMD / project overrides / OAuth RFC 9207 | **Missing** | Python MCP remains stdio JSON-RPC |

## v0.83.0–v0.85.0 ports

| Feature | Status | Notes |
|---------|--------|-------|
| Tools honor `ctx.cwd` | **Match** | `resolve_execution_cwd()` on read/write/edit/bash/grep/find/ls |
| Single-object `edits` coercion | **Match** | Object or JSON object string becomes a one-element array |
| Write success text | **Match** | `Successfully wrote to {path}` (no UTF-16 byte count) |
| Skills in prompt when bash is the only file-read tool | **Match** | `format_skills_for_system_prompt(..., "bash")` |
| `AGENTS.override.md` + UTF-8 BOM strip | **Match** | Preferred over `AGENTS.md`; reads use `utf-8-sig` |
| Root README/AGENTS without skill frontmatter | **Match** | No diagnostics unless basename is `SKILL.md` |
| CLI `--` end-of-options | **Match** | Remaining args are messages / `@files` |
| Session import unique destination | **Match** | `name-N.ext` when the basename already exists |
| Fork/branch compaction `firstKeptEntryId` rewrite | **Match** | Labels stripped from the path are remapped |
| RPC/session abort cancels compaction | **Match** | Manual + auto compaction AbortControllers |
| `prepareNextTurn` only before another assistant turn | **Match** | Matches TS agent-loop |
| `Agent.reset()` while running | **Match** | Raises if `active_run` is set |
| `BeforeToolCallResult.terminate` | **Match** | Copied onto blocked tool error results |
| `send_custom_message` + `triggerTurn: false` while streaming | **Match** | Queued until `turn_end`; does not steer |
| JSON/RPC `message_update` | **Match** | Public events emit usage + assistant delta only |
| JSON/RPC `toolcall_start` id/name | **Match** | Added in `to_json_event()` |
| `defaultTools` setting | **Match** | Initial builtin selection; extension tools stay enabled |
| `/thinking` slash command | **Match** | Selector overlay + `/thinking <level>` |
| `pi auth check` / `print-api-key` / `print-bearer-token` | **Match** | Wired in `main.py` via `auth_command.py` |
| RPC `clear_queue` | **Match** | |
| `session_compact_failed` extension event | **Match** | Manual and auto compaction failures |
| `expandPromptTemplates` on `send_user_message` | **Match** | Defaults to false; option honored |
| `NO_PROXY` root + subdomain | **Match** | Exact domain also excludes subdomains |
| Fullscreen TUI / `tuiMode` | **Match** | `--tui-mode`, `--use-theme`, settings, `TuiAltScreen` |
| Windows `powershell` tool | **Match** | Same factory/name as TS; Windows-only at exec time |
| Extension `ui_prompt_start` / `ui_prompt_end` | **Match** | Wrapped select/confirm/input |
| `pi.registerMarkdownTransformer()` | **Match** | Applied to user/assistant markdown |
| `SessionManager.in_memory(..., entries=)` | **Match** | Restores external entries |
| Terminal capability overrides | **Match** | `PI_HYPERLINKS`, `PI_IMAGE_PROTOCOL`, `PI_TRUE_COLOR`, `set_capability_overrides` |
| Chord / protocol / client / telemetry / v4 sessions | **Partial** | Python modules exist: CBOR framing, unix client/server, sqlite repo, chord context. Not a line-for-line TS replica |
| Remaining AI streaming adapters (Fireworks GLM, Copilot Fable, etc.) | **Partial** | Mid-convo effort, Fireworks module, Codex SSE EOF flush, vLLM priority, `supportsMaxOutputTokens`, default User-Agent |

## v0.82.1 ports

| Feature | Status | Notes |
|---------|--------|-------|
| OAuth: OpenRouter PKCE | **Match** | `openrouter.py` with callback server + manual URL paste |
| OAuth: Kimi Coding device code | **Match** | `kimi_coding.py` RFC 8628 device grant |
| OAuth: xAI device code | **Match** | `xai.py` device code flow |
| OAuth: Radius gateway | **Partial** | `radius.py` device-code flow; browser PKCE callback stub |
| `KnownProvider`: qwen-token-plan, qwen-token-plan-cn, radius | **Match** | Types, env keys, display names, default models |
| `sessionAffinityFormat` replacing `sendSessionIdHeader` | **Match** | `OpenAIResponsesCompat.sessionAffinityFormat`; old field kept as deprecated alias |
| `ToolResultMessage.addedToolNames` | **Match** | Optional `list[str]` field |
| Constrained sampling helpers | **Match** | `constrained_sampling.py`: `supports_grammar_tools`, `supports_strict_tools`, resolve/create helpers |
| `retry_assistant_call` | **Match** | `retry.py`: policy + callbacks + DNS failure patterns |
| `bash_execution_update` event | **Match** | Emitted from `execute_bash`; `_bash_session_env` adds PI_SESSION_ID/FILE/PROVIDER/MODEL/REASONING_LEVEL |
| Remote catalog provider | **Partial** | `remote_catalog_provider.py` ETag-aware refresh skeleton; provider-specific parsing is overridable |
| Extension `ctx.scoped_models` | **Match** | Property on `ExtensionContext` protocol and runner |
| `pi auth print-api-key` | **Match** | Wired as `pi auth print-api-key` / `print-bearer-token` / `check` |
| Compaction retry events | **Match** | `summarization_retry_scheduled/attempt_start/finished` event types + callback builder |
| MCP placeholder | **Partial** | `mcp/__init__.py` stdio JSON-RPC `McpClient` / `McpManager`; not every TS transport |

## v0.82 P2 ports

| Feature | Status | Notes |
|---------|--------|-------|
| Per-request fetch injection (`StreamOptions.fetch`) | **Match** | Optional `fetch` callable on `StreamOptions`; `resolve_httpx_client` helper in `ai/utils/http_client.py` |
| TUI log directory honours `PI_CODING_AGENT_DIR` | **Match** | `tui.py` debug/crash logs use `get_agent_dir()` instead of hardcoded `~/.pi/agent` |
| `ToolResultMessage.usage` | **Match** | Optional `Usage` field on `ToolResultMessage` |
| `app.message.copy` keybinding (Ctrl+X) | **Match** | Default in `DEFAULT_APP_KEYBINDINGS`; handler copies last assistant text to clipboard |
| Evals stub package | **Partial** | `pi_mono.evals.EvalHarness` runs cases against a complete callback; not the TS vitest plugin |
| Narrow-terminal scroll indicator guard (#7015) | **Match** | `select_list.py` / `settings_list.py` guard `width <= 0` |

## Known scope gaps

These are intentional port boundaries, not open regression items. They stay **Partial** / **Missing** until explicitly scheduled.

| Area | Status | Notes |
|------|--------|-------|
| In-process MCP runtime | **Partial** | Stdio JSON-RPC client; not CIMD, project overrides, or full OAuth hardening |
| TypeScript `.ts` extensions | **Diverge** | Python runs `.py` extensions only |
| npm extension packages | **Partial** | Package manager resolves extension paths; resource loader + settings wiring; `.py` only (TS npm extensions not executed) |
| Cursor protobuf proxy | **Diverge** | Python uses CLI bridge (`python/docs/cursor.md`) |
| Clipboard images (interactive) | **Partial** | Wayland/X11/macOS subprocess paths; platform-dependent |
| Export HTML / share | **Partial** | Export exists; share flow lighter than TS |
| `pi update` self-update | **Partial** | CLI flags present; install path depends on distribution method; version-check failures skip update instead of forcing it |
| Session migration edge cases | **Partial** | Core paths covered; not every TS migration scenario |
| `extensions-runner.test.ts` breadth | **Partial** | Core runner covered; not every TS runner scenario |
| `session-manager/*.test.ts` breadth | **Partial** | Core session tests ported; not full TS matrix |
| Package manager semver ranges | **Partial** | `max_satisfying()` for npm update checks; latest-version fallback uses semver max (not lexicographic) |
| Real-provider e2e | **Partial** | Gated pytest marker; optional in CI |

## Intentional divergences

1. **Extension language**: Python port loads `.py` extensions; TypeScript `.ts` extensions are not executed in-process.
2. **Cursor transport**: CLI bridge instead of protobuf proxy (documented in `python/docs/cursor.md`). Browser OAuth tokens stored under `cursor` in `auth.json` are ignored; use `/login` → Cursor subscription.
3. **Distribution**: Python package via `pip`/PyPI story is separate from npm/Bun binaries; `pi update --self` behavior depends on install method.
4. **Platform**: `fcntl` trust store locking on Unix; Windows uses compatible patterns where available.

## Maintenance

When upstream changes land in TypeScript:

1. Port behavior to the matching `pi_mono` module.
2. Add or extend a Python test mirroring the TS test when practical.
3. Update this checklist if status changes.
4. On release, ensure `python/scripts/generate_models.py` stays in sync with `packages/ai` catalogs.
