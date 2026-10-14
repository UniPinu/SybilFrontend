# CTscannr — frontend

Vite + React + TypeScript + Tailwind v4 + shadcn/ui (radix). The whole demo is one scrolling page;
see [../README.md](../README.md) for setup and [../MVP.md](../MVP.md) section 7 for the design brief.

```bash
pnpm install
pnpm dev     # :5173, proxies /api to the backend on :8000
pnpm build   # -> dist/, which the backend serves itself on :8000
pnpm lint

# end-to-end check of live mode against a running backend: picks a person nobody
# has run, follows the real SSE stream to the end, and screenshots each stage.
node live-check.mjs
BASE=http://localhost:5173 node live-check.mjs   # through the dev proxy
```

## Layout

```
src/
  App.tsx                  the page, and the one state machine that drives it
  lib/api.ts               typed wrappers for every endpoint
  lib/format.ts            percentages, the risk colour ramp, reduced-motion check
  hooks/useJobEvents.ts    EventSource -> a reduced view for the progress stepper
  components/
    Hero.tsx               how it works, first-run alerts
    PersonSection.tsx      pick a person, the card, the sealed outcome
    ScanViewer.tsx         slice scrubber, cine, coronal map, attention strip, overlay
    RunSection.tsx         the stepper and the five experts
    PredictionSection.tsx  headline number, risk curve, 100-person icon array
    RevealSection.tsx      the flip card
    Scoreboard.tsx         published results | this demo's people
    Glossary.tsx           hover-card definitions ("slice", "nodule", "AUC", ...)
    ui/                    shadcn components, unmodified
```

## Conventions worth knowing

- **Colour never carries meaning alone.** Every risk colour sits next to a number or a word. The ramp
  has two sets of tokens: `--risk-N` for fills and `--risk-N-text` for anything that is text or a
  hairline border, because the fill ramp is too light to read on white. All text tokens are at least
  4.5:1 against the background in both themes, and the graphics at least 3:1.
- **Motion only where it means something** — votes filling in, the headline counting up, the reveal
  flip. All of it is disabled under `prefers-reduced-motion`.
- **The outcome is never fetched early.** `/outcome` is only requested when the visitor clicks
  *Reveal what happened*, and the backend will not serve it before a result exists.
- A cached person replays the progress stepper over ~2.7 s, labelled as a replay. A live person is
  driven by the real SSE stream.
- The current person lives in the URL (`?p=218892_T1`), so a specific person can be shared.
