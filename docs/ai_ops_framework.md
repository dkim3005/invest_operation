# AI-driven operational implementation framework

How AI and automation are introduced into the Investment Operations workflow in
a controlled way. This is the standard PoolDesk follows; it is also a template
for assessing any candidate automation.

## 1. Principle: automate the work, keep the judgement

Operations work splits into two kinds of task:

- **Mechanical** — ingesting feeds, validating schemas, comparing two records,
  recomputing a value, formatting a report. Deterministic, high-volume,
  rules-based. **Automate fully.**
- **Judgemental** — deciding whether a break is acceptable, approving a NAV,
  signing off a control. Needs accountability and context. **Keep with a
  person; let automation prepare, prioritise and document the decision.**

PoolDesk automates every mechanical step and stops at the judgement. The AI
assistant *triages* breaks — it never closes one. Breaks stay `OPEN` until a
human resolves them.

## 2. Choosing what to automate

A task is a good automation candidate when it is:

1. **Repetitive** — it runs daily/weekly on the same shape of input.
2. **Specifiable** — the correct behaviour can be written down.
3. **Verifiable** — the output can be checked (a reconciliation, a test, a
   total that must tie out).
4. **Recoverable** — an error can be detected and re-run safely.

If a task fails (3) or (4), automate only the preparation and leave the
decision to a person. The data-quality and reconciliation engines are designed
around (3): they exist to make the rest of the pipeline verifiable.

## 3. Where the LLM is used — and where it is not

| Used for | Not used for |
|---|---|
| Classifying a break's probable root cause | Deciding a break is resolved |
| Suggesting the owner team and priority | Posting an accounting entry |
| Drafting a resolution note for a human to review | Approving or signing off a NAV |

The LLM works on a **structured, bounded input** (one break plus its context)
and returns a **structured, schema-validated output**. It never sees free rein
over the data. Guardrails:

- **Structured I/O** — the model returns a fixed schema (root cause, owner,
  priority, note); anything else is rejected.
- **Deterministic fallback** — if the API key is absent or a call fails, a
  rule-based classifier produces the same fields, so the pipeline never
  depends on the model being available.
- **Human-in-the-loop** — the model's output is advisory; the break stays
  `OPEN` and a person decides.
- **Auditability** — every AI field is stored next to the break in
  `recon_exception`, so any triage decision can be reviewed later.

## 4. Standard workflow for a new automated process

1. **Document the manual process first** — inputs, steps, the control that
   proves it worked. (See `docs/process_flow.md`, `docs/control_matrix.md`.)
2. **Build it as small, idempotent steps** — each step re-runnable without
   side effects, so a failure is recoverable.
3. **Add the verification control** — a check that proves the step's output is
   correct, with evidence written to a table.
4. **Add monitoring** — time each step, log start/finish/outcome, surface
   failures (here: `reports/pipeline.log` and the run-status JSON).
5. **Keep a human gate** on any judgement or outward-facing action.
6. **Document the result** — a runbook entry and a control-matrix row, so the
   process is maintainable and auditable by someone else.

## 5. Definition of done for an automated process

An automated process is "done" only when it is **idempotent**, **monitored**,
**verified by a control**, **documented**, and **degrades gracefully** when a
dependency is unavailable. PoolDesk's pipeline meets all five — that is what
makes it safe to run unattended.

*This framework is a learning portfolio artifact written for the IMCO
Investment Operations (AI, Data and Process Optimization) internship.*
