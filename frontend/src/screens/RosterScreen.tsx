import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  getAgentBuilderDetail,
  getCard,
  getSampleInput,
  getSettings,
  listCards,
  listSuggestions,
  getRespecQueue,
} from "../api/client";
import type { CardDetail, CardSummary } from "../api/types";
import { Corners, Meter } from "../components/Blueprint";
import {
  classLine,
  inferJsonType,
  pct,
  readableAnnotation,
  roman,
  titleize,
  XP_PER_LEVEL,
  XP_PER_TOOL_TIER,
  xpIntoLevel,
} from "../lib/format";

interface Props {
  dataVersion: number;
  onConfigure: () => void;
}

/** Per-agent API reference, assembled from the two endpoints that expose it. */
interface ApiReference {
  inputFields: { name: string; type: string }[];
  /** False once an agent declares a real input_model (refinement Phase 1) —
   * true only for the fallback path, inferring field names/types from the
   * saved sample input. Drives whether the panel says so. */
  inputInferredFromSample: boolean;
  outputFields: { name: string; type: string }[];
  exampleRequest: string;
}

interface GmStatus {
  model: string;
  queued: number;
  suggestions: number;
  lastRespec: string;
}

export function RosterScreen({ dataVersion, onConfigure }: Props) {
  const [cards, setCards] = useState<CardSummary[] | null>(null);
  const [cardsError, setCardsError] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, CardDetail>>({});
  const [expanded, setExpanded] = useState<string | null>(null);
  const [apiOpen, setApiOpen] = useState<Record<string, boolean>>({});
  const [apiRefs, setApiRefs] = useState<Record<string, ApiReference>>({});
  const [copiedName, setCopiedName] = useState<string | null>(null);
  const [gm, setGm] = useState<GmStatus | null>(null);

  const loadCards = useCallback(async () => {
    setCards(null);
    setCardsError(null);
    try {
      const summaries = await listCards();
      setCards(summaries);
      // The list endpoint has no backstory or unlock table, but the design shows
      // both on the collapsed card. Fetch each card's detail up front — a handful
      // of extra local requests, and the alternative would be a backend change.
      const loaded = await Promise.all(
        summaries.map((c) =>
          getCard(c.name)
            .then((d) => [c.name, d] as const)
            .catch(() => null),
        ),
      );
      setDetails(Object.fromEntries(loaded.filter((x): x is [string, CardDetail] => x !== null)));
    } catch (e) {
      setCards([]);
      setCardsError(`Could not load the roster.\n${e instanceof ApiError ? e.detail : String(e)}`);
    }
  }, []);

  const loadGm = useCallback(async () => {
    try {
      const [settings, queue, suggestions] = await Promise.all([
        getSettings(),
        getRespecQueue(),
        listSuggestions(),
      ]);
      setGm({
        model: settings.gm_model,
        queued: queue.length,
        suggestions: suggestions.length,
        lastRespec: queue.length ? "pending" : "up to date",
      });
    } catch {
      setGm(null);
    }
  }, []);

  useEffect(() => {
    void loadCards();
    void loadGm();
  }, [loadCards, loadGm, dataVersion]);

  const toggleCard = (name: string) => setExpanded((cur) => (cur === name ? null : name));

  const toggleApi = async (name: string) => {
    const opening = !apiOpen[name];
    setApiOpen((o) => ({ ...o, [name]: opening }));
    if (!opening || apiRefs[name]) return;

    // Input types come from the agent's real input_model when it has one
    // (refinement Phase 1, Task 4). An agent without one yet falls back to
    // inferring field names/types from the saved sample input — a proxy, not
    // a contract, so the panel says so (see inputInferredFromSample below).
    // Output types always come from the builder detail; sample input stays,
    // demoted to an illustrative example request rather than the input
    // source of truth.
    const [detail, sample] = await Promise.all([
      getAgentBuilderDetail(name).catch(() => null),
      getSampleInput(name).catch(() => null),
    ]);
    const hasRealInputSchema = detail?.input_fields_summary != null;
    setApiRefs((refs) => ({
      ...refs,
      [name]: {
        inputFields: hasRealInputSchema
          ? Object.entries(detail!.input_fields_summary!).map(([k, v]) => ({
              name: k,
              type: readableAnnotation(v),
            }))
          : Object.entries(sample ?? {}).map(([k, v]) => ({
              name: k,
              type: inferJsonType(v),
            })),
        inputInferredFromSample: !hasRealInputSchema,
        outputFields: Object.entries(detail?.output_fields_summary ?? {}).map(([k, v]) => ({
          name: k,
          type: readableAnnotation(v),
        })),
        exampleRequest: JSON.stringify({ input: sample ?? {} }, null, 2),
      },
    }));
  };

  const copyExample = (name: string, text: string) => {
    void navigator.clipboard
      ?.writeText(text)
      .catch(() => {})
      .then(() => {
        setCopiedName(name);
        setTimeout(() => setCopiedName((n) => (n === name ? null : n)), 1500);
      });
  };

  return (
    <div className="ak-screen">
      <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 1160 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <h1 className="ak-screen-title">Roster</h1>
          <p className="ak-screen-sub">
            Character progress per agent — levels, stats and unlocks grow through graded feedback on
            the Run screen.
          </p>
        </div>

        {cards === null && <div style={{ fontSize: 12.5, opacity: 0.5 }}>Loading roster…</div>}
        {cardsError && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10, fontSize: 12.5 }}>
            <div style={{ color: "#a03d33", whiteSpace: "pre-wrap" }}>{cardsError}</div>
            <button
              type="button"
              className="btn btn-secondary blueprint"
              onClick={() => void loadCards()}
              style={{ alignSelf: "flex-start" }}
            >
              <Corners />
              Retry
            </button>
          </div>
        )}

        <div className="ak-gm-banner blueprint">
          <Corners />
          <div style={{ fontSize: 28, lineHeight: 1.1, flex: "none" }}>🎲</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
              <span
                style={{
                  fontFamily: "var(--font-heading)",
                  fontWeight: 600,
                  fontSize: 19,
                  letterSpacing: "0.03em",
                  textTransform: "uppercase",
                }}
              >
                Game Master
              </span>
              <span className="ak-mono" style={{ fontSize: 11, opacity: 0.7 }}>
                trait synthesis · prompt suggestions
              </span>
            </div>
            <p style={{ margin: 0, fontSize: 12.5, lineHeight: 1.5, opacity: 0.8, maxWidth: "70ch" }}>
              Re-synthesizes each agent's traits from graded feedback and proposes system-prompt
              changes for your approval. Deterministic rules do the scoring — the GM never lets an
              agent grade itself.
            </p>
            <div
              className="ak-mono"
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: "6px 24px",
                fontSize: 11.5,
                opacity: 0.75,
                marginTop: 2,
              }}
            >
              <span>model: {gm?.model ?? "—"}</span>
              <span>last respec: {gm?.lastRespec ?? "—"}</span>
              <span>queued: {gm?.queued ?? 0}</span>
              <span>suggestions: {gm?.suggestions ?? 0}</span>
            </div>
          </div>
          <button type="button" className="ak-gm-configure" onClick={onConfigure}>
            Configure
          </button>
        </div>

        <div className="ak-roster-grid">
          {(cards ?? []).map((card) => {
            const detail = details[card.name];
            const isExpanded = expanded === card.name;
            const inLevel = xpIntoLevel(card.xp);
            const unlocks = detail?.unlock_table ?? [];
            const earned = unlocks.filter((u) => Number(u.level) <= card.level);
            const tools = Object.entries(detail?.tool_proficiency ?? {});
            const ref = apiRefs[card.name];

            return (
              <div
                key={card.name}
                role="button"
                tabIndex={0}
                className={`ak-roster-card blueprint${isExpanded ? " ak-expanded" : ""}`}
                onClick={() => toggleCard(card.name)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    toggleCard(card.name);
                  }
                }}
              >
                <Corners />
                <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
                  <div style={{ fontSize: 30, lineHeight: 1.1, flex: "none" }}>
                    {card.portrait || "🤖"}
                  </div>
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: 2,
                      flex: 1,
                      minWidth: 0,
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "baseline",
                        gap: 10,
                      }}
                    >
                      <span
                        style={{
                          fontFamily: "var(--font-heading)",
                          fontWeight: 600,
                          fontSize: 19,
                          letterSpacing: "0.03em",
                          textTransform: "uppercase",
                        }}
                      >
                        {card.title}
                      </span>
                      <span className="tag tag-outline" style={{ flex: "none" }}>
                        LV {card.level}
                      </span>
                    </div>
                    <span className="ak-mono" style={{ fontSize: 11, opacity: 0.55 }}>
                      {card.name} · {classLine(card.main_class, card.sub_class)}
                    </span>
                    {card.awaiting_respec && (
                      <span
                        className="ak-respec-badge"
                        style={{ alignSelf: "flex-start", marginTop: 2 }}
                      >
                        ⚠️ Awaiting respec
                      </span>
                    )}
                  </div>
                </div>

                {detail?.backstory && (
                  <p style={{ margin: 0, fontSize: 12, lineHeight: 1.5, opacity: 0.65 }}>
                    {detail.backstory}
                  </p>
                )}

                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <div
                    className="ak-mono"
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      fontSize: 10.5,
                      opacity: 0.6,
                    }}
                  >
                    <span>XP</span>
                    <span>
                      {card.xp} total · {inLevel}/{XP_PER_LEVEL} to LV {card.level + 1}
                    </span>
                  </div>
                  <Meter width={pct(inLevel, XP_PER_LEVEL)} />
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <div className="ak-kicker-sm">Base stats</div>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 1fr",
                      gap: "8px 16px",
                    }}
                  >
                    {Object.entries(card.base_stats).map(([name, value]) => (
                      <div key={name} style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            fontSize: 11,
                          }}
                        >
                          <span
                            style={{
                              letterSpacing: "0.06em",
                              textTransform: "uppercase",
                              opacity: 0.6,
                            }}
                          >
                            {titleize(name)}
                          </span>
                          <span className="ak-mono">{value}</span>
                        </div>
                        <Meter width={pct(value, 100)} small />
                      </div>
                    ))}
                  </div>
                </div>

                <div
                  style={{
                    borderTop: "1px solid var(--color-accent-200)",
                    paddingTop: 10,
                    display: "flex",
                    flexDirection: "column",
                    gap: 6,
                  }}
                >
                  <div
                    className="ak-kicker-sm"
                    style={{ color: "var(--color-accent-700)", opacity: 1 }}
                  >
                    Class stats · {classLine(card.main_class, card.sub_class)}
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 18px" }}>
                    {Object.entries(card.class_stats).map(([name, value]) => (
                      <span
                        key={name}
                        style={{
                          display: "inline-flex",
                          gap: 6,
                          alignItems: "baseline",
                          fontSize: 12,
                        }}
                      >
                        <span style={{ opacity: 0.65 }}>{titleize(name)}</span>
                        <span
                          className="ak-mono"
                          style={{
                            fontSize: 12.5,
                            fontWeight: 600,
                            color: "var(--color-accent-700)",
                          }}
                        >
                          {value}
                        </span>
                      </span>
                    ))}
                  </div>
                </div>

                {earned.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {earned.map((u) => (
                      <span key={String(u.unlock)} className="tag tag-accent">
                        {String(u.unlock)}
                      </span>
                    ))}
                  </div>
                )}

                {isExpanded && (
                  <>
                    <div
                      style={{
                        borderTop: "1px solid var(--color-neutral-300)",
                        paddingTop: 12,
                        display: "grid",
                        gridTemplateColumns: "1fr 1fr",
                        gap: 18,
                      }}
                    >
                      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                        <div className="ak-kicker-sm">Unlock table</div>
                        {unlocks.map((u) => {
                          const reached = Number(u.level) <= card.level;
                          return (
                            <div
                              key={`${u.level}-${String(u.unlock)}`}
                              style={{
                                display: "flex",
                                gap: 10,
                                alignItems: "baseline",
                                opacity: reached ? 1 : 0.45,
                              }}
                            >
                              <span
                                className={`tag ${reached ? "tag-accent" : "tag-neutral"}`}
                                style={{ flex: "none" }}
                              >
                                LV {String(u.level)}
                              </span>
                              <div
                                style={{
                                  display: "flex",
                                  flexDirection: "column",
                                  gap: 1,
                                  minWidth: 0,
                                }}
                              >
                                <span style={{ fontSize: 12.5, fontWeight: 600 }}>
                                  {String(u.unlock)}
                                </span>
                                <span
                                  style={{ fontSize: 11.5, lineHeight: 1.45, opacity: 0.65 }}
                                >
                                  {String(u.description ?? "")}
                                </span>
                              </div>
                            </div>
                          );
                        })}
                      </div>

                      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                        <div className="ak-kicker-sm">Tool proficiency</div>
                        {!detail && <span style={{ fontSize: 12, opacity: 0.5 }}>Loading…</span>}
                        {tools.map(([toolName, prof]) => (
                          <div
                            key={toolName}
                            style={{ display: "flex", flexDirection: "column", gap: 3 }}
                          >
                            <div
                              style={{
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "baseline",
                                gap: 8,
                              }}
                            >
                              <span style={{ fontSize: 12.5, fontWeight: 600 }}>
                                {titleize(toolName)} {roman(prof.tier)}
                              </span>
                              <span className="ak-mono" style={{ fontSize: 11, opacity: 0.6 }}>
                                {prof.xp} XP · {prof.xp % XP_PER_TOOL_TIER}/{XP_PER_TOOL_TIER} to
                                next tier
                              </span>
                            </div>
                            <Meter
                              width={pct(prof.xp % XP_PER_TOOL_TIER, XP_PER_TOOL_TIER)}
                              small
                            />
                          </div>
                        ))}
                        {detail && tools.length === 0 && (
                          <span style={{ fontSize: 12, opacity: 0.5 }}>No tools registered.</span>
                        )}
                      </div>
                    </div>

                    <div
                      style={{ borderTop: "1px solid var(--color-neutral-300)", paddingTop: 10 }}
                    >
                      <button
                        type="button"
                        className="ak-api-toggle"
                        onClick={(e) => {
                          e.stopPropagation();
                          void toggleApi(card.name);
                        }}
                      >
                        <span className="ak-chevron">{apiOpen[card.name] ? "▾" : "▸"}</span>API
                        reference
                      </button>
                      {apiOpen[card.name] && (
                        <div
                          style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: 10,
                            paddingTop: 10,
                            fontSize: 12,
                          }}
                        >
                          <div
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: 8,
                              flexWrap: "wrap",
                            }}
                          >
                            <span className="tag tag-neutral ak-mono">POST</span>
                            <span className="ak-mono" style={{ opacity: 0.7 }}>
                              /api/v1/agents/{card.name}/run
                            </span>
                          </div>
                          <div
                            style={{
                              display: "grid",
                              gridTemplateColumns: "1fr 1fr",
                              gap: 14,
                            }}
                          >
                            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                              <div className="ak-kicker-xs">Input</div>
                              {(ref?.inputFields ?? []).map((f) => (
                                <div
                                  key={f.name}
                                  className="ak-mono"
                                  style={{ fontSize: 11.5, opacity: 0.75 }}
                                >
                                  {f.name}: <span style={{ opacity: 0.6 }}>{f.type}</span>
                                </div>
                              ))}
                              {ref && ref.inputFields.length === 0 && (
                                <span style={{ opacity: 0.5 }}>
                                  {ref.inputInferredFromSample
                                    ? "No sample input saved."
                                    : "No input fields declared."}
                                </span>
                              )}
                              {ref && ref.inputFields.length > 0 && ref.inputInferredFromSample && (
                                <span style={{ opacity: 0.45, fontSize: 10.5, fontStyle: "italic" }}>
                                  inferred from sample input — not a declared schema
                                </span>
                              )}
                            </div>
                            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                              <div className="ak-kicker-xs">Output</div>
                              {(ref?.outputFields ?? []).map((f) => (
                                <div
                                  key={f.name}
                                  className="ak-mono"
                                  style={{ fontSize: 11.5, opacity: 0.75 }}
                                >
                                  {f.name}: <span style={{ opacity: 0.6 }}>{f.type}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                            <div
                              style={{
                                display: "flex",
                                alignItems: "baseline",
                                justifyContent: "space-between",
                              }}
                            >
                              <div className="ak-kicker-xs">Example request</div>
                              <button
                                type="button"
                                className="btn btn-ghost"
                                style={{ fontSize: 11, padding: "2px 8px" }}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  copyExample(card.name, ref?.exampleRequest ?? "");
                                }}
                              >
                                {copiedName === card.name ? "Copied" : "Copy"}
                              </button>
                            </div>
                            <pre className="ak-snippet">{ref?.exampleRequest ?? "Loading…"}</pre>
                          </div>
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>

        {cards !== null && cards.length === 0 && !cardsError && (
          <div style={{ fontSize: 12.5, opacity: 0.55 }}>
            No character cards yet — add a class to an agent in the Builder to give it one.
          </div>
        )}
      </div>
    </div>
  );
}
