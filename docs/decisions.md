# Decisions

Short records of choices that shape the code, newest last.

## 1. A clean history

The repository Jig was started in already held an unrelated, pre-hackathon project. To keep
"every line written during the hackathon" literally true, Jig lives on an orphan branch whose
first commit is the start of this project. It shares no history or files with the earlier code.

## 2. Local web app first, desktop shell later

Jig runs as a local web app: `python scripts/jig.py start` serves the built UI from the FastAPI
backend and opens the browser. This is the fallback the brief allows, and it works the same on
macOS and Windows today. The desktop wrapper (Electron or Tauri) is a Nov 3 polish item.
Electron is the likely pick because it needs no Rust toolchain on either OS. The hard part
either way is bundling the Python backend with OpenCascade (several hundred MB), which the
launcher sidesteps.

## 3. The part program is the single source of truth

A part is a build123d Python file in a fixed shape: UPPER_CASE numeric parameters with
`unit | description | flags` comments, one function per feature with a `kind | label`
docstring, and a `FEATURES` list. The feature tree, parameters, locks, and Code tab are all
derived from it by `jig.cad.program`. A UI edit rewrites one literal at its AST position, so
the round trip is lossless (see `tests/test_program.py`). This makes the two-way Code tab a
parsing problem rather than a synchronisation problem, and exports are just the file.

## 4. Sandbox: static allowlist plus process isolation

Generated code is checked by `jig.cad.sandbox.validate` and then run by `jig.cad.runner` in its
own process with:

- imports limited to `math` and public names from `build123d`, checked statically and again at
  runtime by an import guard (plain `import build123d` is refused because its submodules
  reach `os`);
- no names or attributes starting with `_`, and no `open`, `eval`, `exec`, `getattr`, etc.;
- none of build123d's `import_*` / `export_*` helpers (the runner does the file output into the
  build folder itself);
- restricted builtins, sockets disabled, a CPU rlimit on POSIX, and a wall-clock timeout
  everywhere;
- one process per build, so nothing carries over between builds. A pre-warmed spare process
  hides the build123d import time.

This is not an OS-level jail. It is aimed at keeping a confused model, not a determined
attacker, inside the lines. An OS sandbox (seccomp, App Sandbox, AppContainer) would differ per
platform and is out of scope for the hackathon.

## 5. One small HTTP client instead of the OpenAI SDK

The Meta Model API and Baseten both speak OpenAI Chat Completions, so `jig.ai.client` is about
200 lines of httpx with retries (429, 5xx, network), no retries on other 4xx, provider fallback,
and cost metering. It keeps dependencies small and makes it obvious in the code that only Meta
endpoints are called.

## 6. Model IDs and prices in one file; the meter over-estimates

`backend/src/jig/config/models.toml` holds every model ID, provider URL, and price. Where Meta
has not published a price we could verify (SAM, Muse Image, the hackathon Muse Spark Open
deployment), the meter uses a deliberate over-estimate so a $150 credit pool cannot be
overspent by surprise.

## 7. Licenses

- **gmsh** (meshing for FEA) is GPL-2.0-or-later. It is the mesher the project brief names, so
  it is used, and it runs only inside the separate FEA worker process. Jig's own code stays MIT;
  anyone redistributing a bundled binary must follow the GPL. Netgen (LGPL-2.1) is the drop-in
  alternative if that ever matters.
- Pending: **meta-sam-parser** (decodes SAM 3.1's segmentation output) is under Meta's SAM License. The
  alternative is writing our own decoder for the documented grammar.

## 8. FEA you can trust, and a report that shows why

Modelled on how a careful team validates a fast model against a trusted one:

- 10-node tetrahedra only (4-node ones are far too stiff in bending).
- Loads applied as exact consistent nodal forces for 6-node faces.
- Two meshes per run, and a third, finer one when the first two disagree; the result counts only
  if the peak stress moves under 10 % and the largest displacement under 5 % between the two
  finest, and if the reactions balance the loads within 1 %.
- CalculiX runs its solver on one thread. Multithreaded SPOOLES gave different answers for the
  same input deck (up to 0.8 % in peak stress), enough to flip a borderline convergence verdict.
  One thread costs about 10 s per analysis and makes every verdict repeatable.
- Peak stress is taken more than one element size away from fully fixed faces, because stress at
  an idealised clamp edge is a singularity that grows with refinement. The raw peak is still
  reported.
- The pipeline is regression-tested against beam theory (cantilever: 0.7 % deflection, 1 %
  stress) on every change.
- The verdict (pass, fail, unconfirmed, invalid) is computed from numbers by code. The report
  is fixed templates filled with those numbers, so no model can write a figure into it.

## 9. Agents propose, code decides

- The Planner, Modeler and Fixer run on Muse Spark; the Verifier's design review runs on Muse
  Spark Open (Baseten) and falls back to Muse Spark when Baseten is unreachable or has no key.
  The trace says which model answered every call.
- No model decides PASS. The verdict comes from checks that measure the result: the part format,
  parameter limits, locks, one valid solid, size against the plan, the load case, and FEA; for
  boards, DRC and ERC on the routed copper. The model review can only send work back to the Fixer.
- Locked parameters are restored by code after every model edit, whatever the model wrote.
- A fix may change the part, never the test: once the first program defines its loads and
  `min_safety_factor`, a later program that lowers either fails a check and goes back to the
  Fixer. Weakening the test is the cheapest way for a model to "pass", so it is ruled out.
- A loaded part without a converged FEA run is reported as "not load-tested", never PASS.
- The models are told the formats from the same source the parsers enforce, and the board
  catalog they see is generated from the part library, so they are never told about a part or
  pin that does not exist.
- Tests drive the whole loop against a scripted mock of the Meta Model API: the models' answers
  are fixed, everything else (builds, checks, routing, DRC/ERC) is real.
