import React, { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowUpRight,
  Check,
  ChevronRight,
  Clock3,
  Code2,
  GitPullRequest,
  Layers3,
  Loader2,
  LogOut,
  Play,
  RefreshCw,
  ShieldCheck,
  Terminal,
  X,
} from "lucide-react";
import "./style.css";

type Candidate = {
  id: string;
  name: string;
  version: string;
  target: string | null;
  score: number;
  severity: string;
  direct: boolean;
  dev: boolean;
  actionable: boolean;
  complete: boolean;
  advisory_ids: string[];
  advisory_urls: string[];
  score_parts: Record<string, number>;
  path: string;
  parent: string;
  dependency_paths: string[];
};
type Job = {
  id: string;
  state: string;
  package: string;
  target: string;
  created_at: string;
  updated_at: string;
  run_url?: string;
  pr_url?: string;
  events: { at: string; state: string; message: string }[];
  plan?: Plan;
  result?: Evidence;
  repair?: { diagnosis: string; uncertainty: string };
};
type Report = {
  passed: boolean;
  installed: boolean;
  test_count: number;
  install?: { exit_code: number; duration: number; log: string };
  commands: Record<
    string,
    { exit_code: number; duration: number; log: string }
  >;
};
type Evidence = {
  baseline: Report;
  candidate: Report;
  changes: Record<string, string>;
  diffs?: Record<string, string>;
  new_advisories?: string[];
  removed_advisories?: string[];
  remaining_advisories?: string[];
};
type Plan = {
  id: string;
  hash: string;
  repo: string;
  package: string;
  installed: string;
  target: string;
  base_sha: string;
  allowed_paths: string[];
  commands: string[];
  timeout_minutes: number;
  node: string;
  npm: string;
  target_url: string;
  release_notes: { text: string; url: string; verified: boolean };
  sources: Record<string, string>;
};
type Dashboard = {
  repo: string;
  configured: boolean;
  model_configured: boolean;
  slack_configured: boolean;
  scan: {
    at: string;
    complete: boolean;
    warnings: string[];
    package_count: number;
    dependabot: { title: string; url: string }[];
  } | null;
  visible_candidates: Candidate[];
  jobs: Job[];
};
const terminal = new Set(["succeeded", "blocked", "cancelled", "stale"]);
const label = (s: string) => s.replaceAll("_", " ");
const time = (s?: string) =>
  s
    ? new Date(s).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Not yet";

function App() {
  const [token, setToken] = useState("");
  const [signedIn, setSignedIn] = useState(false);
  const [checkingSession, setCheckingSession] = useState(true);
  const [data, setData] = useState<Dashboard | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [accepted, setAccepted] = useState(false);
  const [tab, setTab] = useState<"overview" | "evidence" | "diff">("overview");
  const hasActiveRun = data?.jobs.some((j) => !terminal.has(j.state)) || false;

  const api = useCallback(
    async <T,>(
      path: string,
      body?: unknown,
      credential?: string,
    ): Promise<T> => {
      const response = await fetch(`/api${path}`, {
        method: body === undefined ? "GET" : "POST",
        headers: {
          "Content-Type": "application/json",
          ...(credential ? { Authorization: `Bearer ${credential}` } : {}),
          ...(body === undefined ? {} : { "X-CSRF-Protection": "1" }),
        },
        credentials: "same-origin",
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const json = await response
        .json()
        .catch(() => ({
          detail:
            "The service could not complete the request. Please try again.",
        }));
      if (
        response.status === 401 &&
        path !== "/auth/login" &&
        path !== "/auth/session"
      ) {
        setSignedIn(false);
        setData(null);
        setJob(null);
        setCandidate(null);
        setPlan(null);
        setError("Your session has expired. Please sign in again.");
      }
      if (!response.ok)
        throw new Error(
          typeof json.detail === "string"
            ? json.detail
            : "Please check the entered values.",
        );
      return json;
    },
    [],
  );
  const refresh = useCallback(
    async () => setData(await api<Dashboard>("/dashboard")),
    [api],
  );
  useEffect(() => {
    let active = true;
    api("/auth/session")
      .then(() => api<Dashboard>("/dashboard"))
      .then((d) => {
        if (active) {
          setData(d);
          setSignedIn(true);
        }
      })
      .catch(() => {})
      .finally(() => {
        if (active) setCheckingSession(false);
      });
    return () => {
      active = false;
    };
  }, [api]);
  const act = async (name: string, fn: () => Promise<void>) => {
    setBusy(name);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy("");
    }
  };

  useEffect(() => {
    if (!signedIn) return;
    const timer = setInterval(
      () => {
        refresh().catch(() => {});
        if (job)
          api<Job>(`/jobs/${job.id}`)
            .then(setJob)
            .catch(() => {});
      },
      hasActiveRun ? 10000 : 60000,
    );
    return () => clearInterval(timer);
  }, [signedIn, refresh, api, job?.id, hasActiveRun]);

  if (checkingSession)
    return (
      <div className="session-check" role="status">
        <Loader2 className="spin" size={20} />
        Checking your session…
      </div>
    );

  if (!signedIn)
    return (
      <div className="login">
        <div className="login-art">
          <div className="brand">
            <ShieldCheck /> Dependency Steward
          </div>
          <span className="eyebrow">YOUR DEPENDENCIES. UNDER CONTROL.</span>
          <h1>
            From an upgrade
            <br />
            to a reviewed change.
          </h1>
          <p>
            Inspect. Test. Adapt. Deliver the evidence.
            <br />
            You keep the final say.
          </p>
          <div className="orbit">
            <Layers3 size={76} />
            <span>01 / DISCOVER</span>
            <span>02 / VALIDATE</span>
            <span>03 / REVIEW</span>
          </div>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            act("login", async () => {
              await api("/auth/login", {}, token);
              setToken("");
              await refresh();
              setSignedIn(true);
            });
          }}
        >
          <span className="eyebrow">OPERATOR WORKSPACE</span>
          <h2>Welcome back.</h2>
          <p>Sign in to review your repository and authorize upgrades.</p>
          <label htmlFor="token">Operator token</label>
          <input
            id="token"
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            autoComplete="off"
            required
            minLength={24}
          />
          {error && (
            <div role="alert" className="error">
              {error}
            </div>
          )}
          <button disabled={!!busy} className="primary">
            {busy ? (
              <Loader2 className="spin" size={18} />
            ) : (
              <ArrowUpRight size={18} />
            )}{" "}
            Open workspace
          </button>
          <small>
            Your session lasts up to four hours and stays signed in through
            refresh.
          </small>
        </form>
      </div>
    );

  const counts = {
    active: data?.jobs.filter((j) => !terminal.has(j.state)).length || 0,
    complete: data?.jobs.filter((j) => j.state === "succeeded").length || 0,
  };
  return (
    <div className="shell">
      <aside>
        <a className="brand" href="/">
          <ShieldCheck />{" "}
          <span>
            Dependency
            <br />
            <b>Steward</b>
          </span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <button className="nav active" onClick={() => setJob(null)}>
          <Layers3 size={18} />
          Upgrade queue <span>{data?.visible_candidates.length || 0}</span>
        </button>
        <div className="side-note">
          <ShieldCheck size={20} />
          <b>
            Human reviewed.
            <br />
            Evidence backed.
          </b>
          <p>Draft PRs only. Every upgrade starts with your authorization.</p>
        </div>
        <button
          className="nav logout"
          disabled={busy === "logout"}
          onClick={() => {
            act("logout", async () => {
              await api("/auth/logout", {});
              setToken("");
              setSignedIn(false);
              setData(null);
              setJob(null);
              setCandidate(null);
              setPlan(null);
            });
          }}
        >
          <LogOut size={17} />
          Sign out
        </button>
      </aside>
      <main>
        <header>
          <div className="breadcrumb">
            Workspace <ChevronRight size={14} />
            <b>{job ? "Upgrade run" : "Upgrade queue"}</b>
          </div>
          <span className="operator">
            <span /> Operator workspace
          </span>
        </header>
        <div className="content">
          <div className="page-heading">
            <div>
              <span className="eyebrow">DEPENDENCY OPERATIONS</span>
              <h1>
                {job
                  ? `${job.plan?.package || "Upgrade"} run`
                  : "A clear path to the next upgrade."}
              </h1>
              <p>
                {job
                  ? "Follow the work. Inspect the evidence. Review the result."
                  : "Prioritize the change, validate it, and hand off a reviewable pull request."}
              </p>
            </div>
            <button
              className="primary"
              disabled={!!busy || !data?.configured}
              onClick={() =>
                act("scan", async () => {
                  setData(await api<Dashboard>("/scan", {}));
                })
              }
            >
              {busy === "scan" ? (
                <Loader2 size={16} className="spin" />
              ) : (
                <RefreshCw size={16} />
              )}{" "}
              Scan now
            </button>
          </div>
          {error && (
            <div role="alert" className="error">
              {error}
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {!data?.configured && (
            <div className="notice">
              Connect the owned public repository using the server’s GITHUB_REPO
              and GITHUB_TOKEN settings, then scan.
            </div>
          )}
          {!job ? (
            <>
              <div className="stats">
                <Stat
                  title="Packages inspected"
                  value={data?.scan?.package_count ?? "—"}
                  sub={`Last scan · ${time(data?.scan?.at)}`}
                  icon={<Layers3 />}
                />
                <Stat
                  title="Ready to investigate"
                  value={data?.visible_candidates.length || 0}
                  sub="Ranked by deterministic evidence"
                  icon={<Code2 />}
                />
                <Stat
                  title="In progress"
                  value={counts.active}
                  sub="One active upgrade per repository"
                  icon={<Clock3 />}
                />
                <Stat
                  title="Draft PRs delivered"
                  value={counts.complete}
                  sub="Ready for a human review"
                  icon={<GitPullRequest />}
                />
              </div>
              <section className="panel">
                <div className="section-title">
                  <div>
                    <h2>
                      Upgrade queue{" "}
                      <span className="badge">
                        {data?.visible_candidates.length || 0}
                      </span>
                    </h2>
                    <p>{data?.repo || "Repository not connected"}</p>
                  </div>
                  <span className="subtle">
                    {data?.scan?.complete
                      ? "Advisory data complete"
                      : "Awaiting complete scan"}
                  </span>
                </div>
                {data?.scan?.warnings.map((w) => (
                  <div className="notice" key={w}>
                    {w}
                  </div>
                ))}
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>DEPENDENCY</th>
                        <th>VERSION CHANGE</th>
                        <th>PRIORITY</th>
                        <th>FINDINGS</th>
                        <th>WORKFLOW</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data?.visible_candidates.map((c) => (
                        <tr key={c.id}>
                          <td>
                            <b>{c.name}</b>
                            <small>
                              {c.dev ? "Development" : "Production"} ·{" "}
                              {c.direct
                                ? "Direct dependency"
                                : "Transitive dependency"}
                            </small>
                          </td>
                          <td>
                            <code>{c.version}</code>
                            <span className="arrow">→</span>
                            <code>{c.target || "Investigate"}</code>
                          </td>
                          <td>
                            <span
                              className={`score ${c.score >= 70 ? "high" : ""}`}
                            >
                              {c.score}
                              <small>/100</small>
                            </span>
                            <small>{c.severity}</small>
                            <details className="score-details">
                              <summary>Why this score?</summary>
                              <dl>
                                {Object.entries(c.score_parts).map(
                                  ([key, value]) => (
                                    <React.Fragment key={key}>
                                      <dt>{label(key)}</dt>
                                      <dd>+{value}</dd>
                                    </React.Fragment>
                                  ),
                                )}
                              </dl>
                              <small>
                                {c.complete
                                  ? "Current advisory data complete"
                                  : "Incomplete evidence; investigate"}
                              </small>
                            </details>
                          </td>
                          <td>
                            {c.advisory_ids.length ? (
                              c.advisory_ids.map((a, i) => (
                                <a
                                  key={a}
                                  href={c.advisory_urls[i]}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="advisory"
                                >
                                  {a}
                                  <ArrowUpRight size={12} />
                                </a>
                              ))
                            ) : (
                              <span className="subtle">Version update</span>
                            )}
                          </td>
                          <td>
                            <button
                              className="outline"
                              disabled={!c.actionable || !!busy}
                              onClick={() => {
                                setCandidate(c);
                                setTarget(c.target || "");
                                setPlan(null);
                                setAccepted(false);
                              }}
                            >
                              Review plan
                              <ChevronRight size={14} />
                            </button>
                            <div className="row-actions">
                              <select
                                aria-label={`Snooze ${c.name}`}
                                defaultValue=""
                                disabled={!!busy}
                                onChange={(e) => {
                                  const days = Number(e.target.value);
                                  e.target.value = "";
                                  if (days)
                                    act("snooze", async () =>
                                      setData(
                                        await api<Dashboard>(
                                          `/candidates/${c.id}/action`,
                                          { days },
                                        ),
                                      ),
                                    );
                                }}
                              >
                                <option value="" disabled>
                                  Snooze…
                                </option>
                                <option value="1">1 day</option>
                                <option value="7">7 days</option>
                                <option value="30">30 days</option>
                              </select>
                              <button
                                disabled={!!busy}
                                onClick={() =>
                                  act("ack", async () =>
                                    setData(
                                      await api<Dashboard>(
                                        `/candidates/${c.id}/action`,
                                        { days: 0 },
                                      ),
                                    ),
                                  )
                                }
                              >
                                Acknowledge
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {!data?.visible_candidates.length && (
                  <div className="empty">
                    <Layers3 />
                    <h3>
                      {data?.scan
                        ? "No visible upgrade candidates"
                        : "Your first scan starts here"}
                    </h3>
                    <p>
                      {data?.scan
                        ? "No current candidates, or they have been snoozed. Scan again to check for changes."
                        : "Connect a repository, then scan to inspect exact installed versions and available updates."}
                    </p>
                  </div>
                )}
              </section>
              <section className="panel runs">
                <div className="section-title">
                  <div>
                    <h2>Recent runs</h2>
                    <p>Every decision leaves a trail.</p>
                  </div>
                </div>
                {data?.jobs.length ? (
                  data.jobs.map((j) => (
                    <button
                      className="run-row"
                      key={j.id}
                      onClick={() =>
                        act("job", async () => {
                          setJob(await api<Job>(`/jobs/${j.id}`));
                          setTab("overview");
                        })
                      }
                    >
                      <div className={`run-icon ${j.state}`}>
                        <GitPullRequest size={18} />
                      </div>
                      <div>
                        <b>
                          {j.package}{" "}
                          <span className="subtle">→ {j.target}</span>
                        </b>
                        <small>{time(j.created_at)}</small>
                      </div>
                      <span className={`status ${j.state}`}>
                        {label(j.state)}
                      </span>
                      <ChevronRight size={16} />
                    </button>
                  ))
                ) : (
                  <div className="empty compact">
                    Authorized upgrades will appear here.
                  </div>
                )}
              </section>
              <div className="integrations">
                <span>
                  <Check size={14} /> GitHub + npm + OSV
                </span>
                <span>
                  {data?.model_configured ? (
                    <Check size={14} />
                  ) : (
                    <Clock3 size={14} />
                  )}
                  Gemini{" "}
                  {data?.model_configured ? "connected" : "not configured"}
                </span>
                <span>
                  {data?.slack_configured ? (
                    <Check size={14} />
                  ) : (
                    <Clock3 size={14} />
                  )}
                  Slack{" "}
                  {data?.slack_configured ? "connected" : "not configured"}
                </span>
              </div>
            </>
          ) : (
            <section className="panel job-panel">
              <div className="section-title">
                <div>
                  <button className="text-button" onClick={() => setJob(null)}>
                    ← Back to queue
                  </button>
                  <h2>
                    {job.plan?.package} <code>→ {job.plan?.target}</code>{" "}
                    <span className={`status ${job.state}`}>
                      {label(job.state)}
                    </span>
                  </h2>
                  <p>
                    Base {job.plan?.base_sha.slice(0, 12)} · Updated{" "}
                    {time(job.updated_at)}
                  </p>
                </div>
                <div className="button-group">
                  {job.pr_url && (
                    <a
                      className="primary"
                      href={job.pr_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Review draft PR <ArrowUpRight size={15} />
                    </a>
                  )}
                  {job.run_url && (
                    <a
                      className="outline"
                      href={job.run_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      GitHub run <ArrowUpRight size={15} />
                    </a>
                  )}
                  {!terminal.has(job.state) && (
                    <button
                      className="outline"
                      disabled={!!busy || job.state === "publishing"}
                      onClick={() =>
                        act("cancel", async () => {
                          setJob(await api<Job>(`/jobs/${job.id}/cancel`, {}));
                          await refresh();
                        })
                      }
                    >
                      Cancel run
                    </button>
                  )}
                </div>
              </div>
              <div className="tabs">
                {(["overview", "evidence", "diff"] as const).map((t) => (
                  <button
                    key={t}
                    className={tab === t ? "selected" : ""}
                    onClick={() => setTab(t)}
                  >
                    {t === "overview"
                      ? "Run timeline"
                      : t === "evidence"
                        ? "Validation evidence"
                        : "File changes"}
                  </button>
                ))}
              </div>
              {tab === "overview" && (
                <div className="timeline">
                  {job.events.map((e, i) => (
                    <div className="timeline-event" key={i}>
                      <div className="timeline-dot" />
                      <div>
                        <b>{label(e.state)}</b>
                        <p>{e.message}</p>
                        <small>{time(e.at)}</small>
                      </div>
                    </div>
                  ))}
                  {!terminal.has(job.state) && (
                    <p className="subtle">
                      <Clock3 size={14} /> The worker reconciles runs every five
                      minutes. You can close this page.
                    </p>
                  )}
                  {job.repair && (
                    <div className="notice">
                      <b>Compatibility diagnosis</b>
                      <p>{job.repair.diagnosis}</p>
                      <p>{job.repair.uncertainty}</p>
                    </div>
                  )}
                </div>
              )}
              {tab === "evidence" &&
                (job.result ? (
                  <div className="evidence-grid">
                    {(["baseline", "candidate"] as const).map((stage) => (
                      <div key={stage}>
                        <h3>
                          {stage === "baseline" ? "Baseline" : "Candidate"}{" "}
                          <span
                            className={`status ${job.result![stage]?.passed ? "succeeded" : "blocked"}`}
                          >
                            {job.result![stage]?.passed ? "Passed" : "Failed"}
                          </span>
                        </h3>
                        <p>
                          {job.result![stage]?.test_count || 0} tests recorded
                        </p>
                        {Object.entries({
                          ...(job.result![stage]?.install
                            ? { "npm ci": job.result![stage].install! }
                            : {}),
                          ...(job.result![stage]?.commands || {}),
                        }).map(([name, result]) => (
                          <details key={name}>
                            <summary>
                              <Terminal size={14} />
                              {name}
                              <span>
                                Exit {result.exit_code} ·{" "}
                                {result.duration.toFixed(1)}s
                              </span>
                            </summary>
                            <pre>{result.log || "No output"}</pre>
                          </details>
                        ))}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty">
                    Test evidence will appear after the execution run completes.
                  </div>
                ))}
              {tab === "diff" &&
                (job.result ? (
                  <div className="diffs">
                    {Object.entries(job.result.changes).map(([path, text]) => (
                      <details key={path}>
                        <summary>
                          <Code2 size={15} />
                          {path}
                        </summary>
                        <pre className="unified-diff">
                          {(job.result?.diffs?.[path] || text)
                            .split("\n")
                            .map((line, index) => (
                              <span
                                key={index}
                                className={
                                  line.startsWith("+")
                                    ? "added"
                                    : line.startsWith("-")
                                      ? "removed"
                                      : line.startsWith("@@")
                                        ? "hunk"
                                        : ""
                                }
                              >
                                {line}
                                {"\n"}
                              </span>
                            ))}
                        </pre>
                      </details>
                    ))}
                  </div>
                ) : (
                  <div className="empty">No tested file changes yet.</div>
                ))}
            </section>
          )}
          <footer>
            <ShieldCheck size={15} /> Reviewed plans. Isolated runs. Evidence
            before publication.
          </footer>
        </div>
      </main>
      {candidate && (
        <div className="modal-backdrop">
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="plan-title"
            className="modal"
          >
            <div className="section-title">
              <div>
                <span className="eyebrow">AUTHORIZE AN UPGRADE</span>
                <h2 id="plan-title">{candidate.name}</h2>
              </div>
              <button
                className="icon-button"
                aria-label="Close plan"
                onClick={() => {
                  setCandidate(null);
                  setPlan(null);
                }}
              >
                <X />
              </button>
            </div>
            {!plan ? (
              <>
                <p>
                  Choose an exact published version. The plan records the
                  current repository commit and the permitted changes.
                </p>
                <label htmlFor="target">Target version</label>
                <input
                  id="target"
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                />
                <button
                  className="primary"
                  disabled={!!busy}
                  onClick={() =>
                    act("plan", async () =>
                      setPlan(
                        await api<Plan>("/plans", {
                          package: candidate.name,
                          target,
                        }),
                      ),
                    )
                  }
                >
                  {busy === "plan" && <Loader2 className="spin" size={16} />}
                  Prepare plan <ChevronRight size={16} />
                </button>
              </>
            ) : (
              <>
                <div className="plan-version">
                  <code>{plan.installed}</code>
                  <ChevronRight />
                  <code>{plan.target}</code>
                  <a href={plan.target_url} target="_blank" rel="noreferrer">
                    npm <ArrowUpRight size={13} />
                  </a>
                </div>
                <dl>
                  <dt>Repository</dt>
                  <dd>{plan.repo}</dd>
                  <dt>Base commit</dt>
                  <dd>
                    <code>{plan.base_sha.slice(0, 12)}</code>
                  </dd>
                  <dt>Source repair paths</dt>
                  <dd>{plan.allowed_paths.join(", ")}</dd>
                  <dt>Required checks</dt>
                  <dd>{plan.commands.join(" · ")}</dd>
                  <dt>Execution budget</dt>
                  <dd>
                    {plan.timeout_minutes} minutes per job · one repair attempt
                  </dd>
                  <dt>Toolchain</dt>
                  <dd>
                    Node {plan.node} · npm {plan.npm}
                  </dd>
                </dl>
                {plan.release_notes && (
                  <details className="release-context">
                    <summary>
                      Release-note evidence <ArrowUpRight size={14} />
                    </summary>
                    <p>
                      <a
                        href={plan.release_notes.url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open source
                      </a>
                      {!plan.release_notes.verified &&
                        " · Notes unavailable; target metadata verified"}
                    </p>
                    <pre>{plan.release_notes.text}</pre>
                  </details>
                )}
                <div className="notice">
                  May change this dependency, its lockfile, and the listed
                  source files. Tests and workflows remain unchanged. A passing
                  result creates a draft PR for your review.
                </div>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={accepted}
                    onChange={(e) => setAccepted(e.target.checked)}
                  />
                  <span>
                    I authorize this exact plan, its execution, and draft PR
                    publication if validation passes.
                  </span>
                </label>
                <button
                  disabled={!accepted || !!busy}
                  className="primary"
                  onClick={() =>
                    act("start", async () => {
                      const j = await api<Job>("/jobs", {
                        plan_id: plan.id,
                        plan_hash: plan.hash,
                        publish_draft: true,
                      });
                      setJob(j);
                      setCandidate(null);
                      setPlan(null);
                      setTab("overview");
                      await refresh();
                    })
                  }
                >
                  {busy === "start" ? (
                    <Loader2 size={16} className="spin" />
                  ) : (
                    <Play size={16} />
                  )}
                  Authorize & start
                </button>
                <small className="subtle">Plan {plan.hash.slice(0, 16)}</small>
              </>
            )}
            {error && (
              <div role="alert" className="error">
                {error}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function Stat({
  title,
  value,
  sub,
  icon,
}: {
  title: string;
  value: number | string;
  sub: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="stat">
      <div>
        {title}
        {icon}
      </div>
      <strong>{value}</strong>
      <small>{sub}</small>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
