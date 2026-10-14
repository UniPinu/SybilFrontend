import {
  CalendarDiagram,
  Figure,
  HazardStackDiagram,
  NudgeDiagram,
  OffsetDiagram,
  PipelineDiagram,
} from '@/components/research/diagrams'
import { Tex } from '@/components/Tex'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import { useVisualiserCase } from '@/lib/visualiser'
import { goTo } from '@/lib/url'
import { COHORT, EXAMPLE, bestLambda, logitMse, nudged, offsets } from '@/lib/trajectory'
import { ArrowDown, Boxes, FlaskConical, Layers3, Sigma } from 'lucide-react'
import { useId, useMemo, useState, type ReactNode } from 'react'

function Section({ id, eyebrow, title, children }: { id: string; eyebrow: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="section-anchor space-y-6" aria-labelledby={`${id}-title`}>
      <header className="space-y-2">
        <p className="text-xs font-medium tracking-widest text-muted-foreground uppercase">{eyebrow}</p>
        <h2 id={`${id}-title`} className="text-2xl font-semibold sm:text-3xl">{title}</h2>
      </header>
      {children}
    </section>
  )
}

function Equation({ label, tex, children }: { label?: string; tex: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border bg-muted/30 px-4 py-3">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1"><Tex tex={tex} block /></div>
        {label && <span className="shrink-0 font-mono text-xs text-muted-foreground">({label})</span>}
      </div>
      {children && <div className="pt-1 text-sm text-muted-foreground">{children}</div>}
    </div>
  )
}

const [T0, T1, T2] = EXAMPLE.scans

export function ResearchHero() {
  return (
    <section id="research" className="section-anchor grid items-center gap-10 pt-10 lg:grid-cols-[1fr_1.15fr]">
      <div className="space-y-5">
        <Badge variant="outline" className="gap-1.5"><FlaskConical className="size-3.5" aria-hidden /> CTscannr research project</Badge>
        <h1 className="text-4xl leading-tight font-semibold text-balance sm:text-5xl">
          Does a second scan make the prediction sharper?
        </h1>
        <p className="max-w-xl text-lg text-muted-foreground">
          Sybil reads <em>one</em> low-dose chest CT and predicts lung-cancer risk for the next six
          years. Screening programmes take a scan every year, yet each one is read as if the
          last never happened. We ask whether the <strong className="text-foreground">change</strong> between
          two of Sybil&rsquo;s predictions says something a single prediction cannot, and whether it
          can nudge this year&rsquo;s estimate towards next year&rsquo;s.
        </p>
        <div className="flex flex-wrap gap-3">
          <Button asChild size="lg"><a href="#question"><Sigma aria-hidden /> The research question</a></Button>
          <Button variant="outline" size="lg" onClick={() => goTo({ view: 'visualiser' })}>
            <Layers3 aria-hidden /> How Sybil works, step by step
          </Button>
        </div>
        <dl className="grid max-w-md grid-cols-3 gap-4 pt-2 text-sm">
          <div><dt className="text-muted-foreground">participants</dt><dd className="text-xl font-semibold tabular-nums">{COHORT.threeRounds.toLocaleString()}</dd><dd className="text-xs text-muted-foreground">with 3 readable scans</dd></div>
          <div><dt className="text-muted-foreground">diagnosed</dt><dd className="text-xl font-semibold tabular-nums">{COHORT.threeRoundsDiagnosed}</dd><dd className="text-xs text-muted-foreground">of them, later</dd></div>
          <div><dt className="text-muted-foreground">curves</dt><dd className="text-xl font-semibold tabular-nums">3 × 6</dd><dd className="text-xs text-muted-foreground">risks per person</dd></div>
        </dl>
      </div>
      <Figure
        title={`One real person, three scans: NLST participant ${EXAMPLE.pid}`}
        caption={<>Each scan gets its own six-year curve, drawn from the date it was taken. The shaded band is
          where the T0 and T1 curves both make a prediction. Sybil read each scan with no knowledge of the
          others, yet the curves climb from round to round, and the diagnosis came 0.2 years after T2.</>}
      >
        <CalendarDiagram />
      </Figure>
    </section>
  )
}

export function ResearchBody() {
  const sliderId = useId()
  const best = useMemo(() => bestLambda(T0, T1, T2), [])
  const [lambda, setLambda] = useState(0)
  const pts = nudged(T0, T1, T2, lambda)
  const err = logitMse(pts.map((p) => ({ predicted: p.nudged, actual: p.actual })))
  const err0 = logitMse(pts.map((p) => ({ predicted: p.carried, actual: p.actual })))
  const d01 = offsets(T0, T1)
  const vcase = useVisualiserCase()
  const m0 = vcase.data?.models[0]

  return (
    <div className="space-y-20">
      {/* 1 ---------------------------------------------------------------- */}
      <Section id="sybil" eyebrow="1 · What one scan gives us" title="Sybil turns a CT scan into a six-year curve">
        <div className="grid gap-8 lg:grid-cols-2">
          <div className="space-y-4 leading-relaxed">
            <p>
              Write <Tex tex="x_k" /> for the scan taken at screening round <Tex tex="k" />, at time{' '}
              <Tex tex="t_k" /> (years since the person enrolled), and <Tex tex="T" /> for the time of a
              lung-cancer diagnosis. Sybil returns six numbers:
            </p>
            <Equation label="1" tex={String.raw`F_k(h) \;=\; \Pr\!\left(T \le t_k + h \;\middle|\; x_k,\; T > t_k\right), \qquad h = 1,\dots,6`} />
            <p>
              Inside, a 3D ResNet squeezes the scan into a 512-number summary <Tex tex="z_k" />. The last layer
              adds a base hazard to a running sum of non-negative yearly hazards, so the curve can only
              go up with <Tex tex="h" />:
            </p>
            <Equation label="2" tex={String.raw`F_k(h) = g_h\!\left(\tfrac15 \sum_{m=1}^{5} \sigma\!\Big( b_m(z_k) + \sum_{j=1}^{h} \operatorname{ReLU}\big(w_{m,j}^{\top} z_k + c_{m,j}\big) \Big)\right)`}>
              Five models vote (<Tex tex="m" />), their sigmoid outputs are averaged, and an isotonic map{' '}
              <Tex tex="g_h" /> per year calibrates the mean.
            </Equation>
            <Button variant="outline" onClick={() => goTo({ view: 'visualiser' })}>
              <Boxes aria-hidden /> Watch every step on a real scan
            </Button>
          </div>
          <Figure
            title={m0 ? `The six output neurons of model 1, for participant ${EXAMPLE.pid}'s T2 scan` : 'The six output neurons'}
            caption={<>Grey: base hazard <Tex tex="b(z)" />; yearly hazards would stack on top of it. Each bar&rsquo;s height is a
              logit, and the sigmoid above it gives that year&rsquo;s risk before averaging and calibration. Real values from the
              recorded run: for this scan every yearly hazard is negative, so ReLU zeroes them and all six bars equal the base.
              The rise from year 1 to year 6 in the final curve comes from the calibration maps <Tex tex="g_h" />.</>}
          >
            {m0 ? (
              <HazardStackDiagram base={m0.base_hazard} hazards={m0.raw_hazard.map((v) => Math.max(0, v))} />
            ) : (
              <p className="py-10 text-center text-sm text-muted-foreground">Loading the recorded run…</p>
            )}
          </Figure>
        </div>
      </Section>

      {/* 2 ---------------------------------------------------------------- */}
      <Section id="align" eyebrow="2 · Two scans, one clock" title="Before comparing curves, put them on the same clock">
        <div className="grid gap-8 lg:grid-cols-2">
          <div className="space-y-4 leading-relaxed">
            <p>
              The T1 scan only exists because the person was still cancer-free at <Tex tex="t_1" />. T0&rsquo;s
              curve does not know that. Conditioning it on surviving to <Tex tex="t_1" /> gives the risk T0
              <em> would</em> assign to the same years T1 is asked about:
            </p>
            <Equation label="3" tex={String.raw`\tilde F_{0\to1}(h) \;=\; \frac{F_0(h+\Delta) - F_0(\Delta)}{1 - F_0(\Delta)}, \qquad \Delta = t_1 - t_0`}>
              <Tex tex="F_0" /> is read between its yearly points by straight lines, with <Tex tex="F_0(0)=0" />.
              It follows from <Tex tex={String.raw`\Pr(A\mid B)=\Pr(A\cap B)/\Pr(B)`} />, and holds for{' '}
              <Tex tex={String.raw`h+\Delta\le 6`} />, which is five years for a yearly screen.
            </Equation>
            <p>
              The gap between the two, measured in logits so that a step from 1% to 2% counts as much as
              one from 33% to 50%, is the <strong>offset</strong>:
            </p>
            <Equation label="4" tex={String.raw`\delta_{01}(h) \;=\; \operatorname{logit} F_1(h) \;-\; \operatorname{logit} \tilde F_{0\to1}(h), \qquad h \in \mathcal H_{01} = \{h : h + \Delta \le 6\}`} />
            <p className="text-sm text-muted-foreground">
              If the second scan carried no new information, <Tex tex={String.raw`\delta_{01}`} /> would hover around a fixed
              pattern <Tex tex={String.raw`\mu(h)`} /> set by how Sybil spreads risk over the years. What is
              left over, <Tex tex={String.raw`\delta_{01}(h)-\mu(h)`} />, is what this person&rsquo;s scan changed.
            </p>
          </div>
          <Figure
            title={`Participant ${EXAMPLE.pid}: T0 rebased to T1 (Δ = ${(T1.t - T0.t).toFixed(2)} y)`}
            caption={<>At every year both scans cover, the new scan says more risk than the old one implied:{' '}
              <Tex tex={String.raw`\delta_{01}`} /> runs from {Math.min(...d01.map((p) => p.delta)).toFixed(2)} to{' '}
              {Math.max(...d01.map((p) => p.delta)).toFixed(2)} logits.</>}
          >
            <OffsetDiagram />
          </Figure>
        </div>
      </Section>

      {/* 3 ---------------------------------------------------------------- */}
      <Section id="nudge" eyebrow="3 · The idea" title="Use the T0 → T1 offset to nudge T1 towards T2">
        <div className="grid gap-8 lg:grid-cols-2">
          <div className="space-y-4 leading-relaxed">
            <p>
              If risk drifts smoothly, the offset between the first two scans should say something about
              the third. Carry T1 to T2&rsquo;s clock with (3), then push it along the drift it showed:
            </p>
            <Equation label="5" tex={String.raw`\operatorname{logit} \hat F_{2}(h) \;=\; \operatorname{logit} \tilde F_{1\to2}(h) \;+\; \alpha_h \;+\; \lambda_h\, \delta_{01}(h)`}>
              <Tex tex={String.raw`\alpha_h`} /> absorbs the structural part <Tex tex={String.raw`\mu`} />;{' '}
              <Tex tex={String.raw`\lambda_h`} /> says how much of a person&rsquo;s drift carries on.
            </Equation>
            <p>Both are fitted by least squares over the training participants <Tex tex="i" />, which has a closed form per year:</p>
            <Equation label="6" tex={String.raw`(\hat\alpha_h,\hat\lambda_h) = \arg\min_{\alpha,\lambda} \sum_{i} \Big( \operatorname{logit} F^{(i)}_{2}(h) - \operatorname{logit} \tilde F^{(i)}_{1\to2}(h) - \alpha - \lambda\, \delta^{(i)}_{01}(h) \Big)^2`} />
            <p>
              The same adjustment applied at T1, before any third scan exists, is the estimate we actually care about:
            </p>
            <Equation label="7" tex={String.raw`F^{\star}_{1}(h) \;=\; \sigma\!\big(\operatorname{logit} F_1(h) + \alpha'_h + \lambda'_h\, \delta_{01}(h)\big)`} />
          </div>
          <Figure
            title={`Try it on participant ${EXAMPLE.pid}`}
            caption={<>With one person there is no way to separate <Tex tex={String.raw`\alpha`} /> from <Tex tex={String.raw`\lambda`} />, so
              this sets <Tex tex={String.raw`\alpha = 0`} /> and fits <Tex tex={String.raw`\lambda`} /> alone. Here the
              drift explains the jump to T2 almost completely; whether that holds across thousands of people,
              once the structural part is removed, is the research question.</>}
          >
            <NudgeDiagram lambda={lambda} />
            <div className="space-y-3 rounded-lg border bg-muted/30 p-3">
              <div className="flex items-center justify-between gap-3">
                <Label htmlFor={sliderId} className="text-sm">λ = <span className="font-mono tabular-nums">{lambda.toFixed(2)}</span></Label>
                <div className="flex gap-2">
                  <Button size="xs" variant="outline" onClick={() => setLambda(0)}>λ = 0</Button>
                  <Button size="xs" variant="outline" onClick={() => setLambda(Number(best.toFixed(2)))}>
                    best fit (λ = {best.toFixed(2)})
                  </Button>
                </div>
              </div>
              <Slider id={sliderId} min={0} max={1.5} step={0.01} value={[lambda]}
                onValueChange={([v]) => setLambda(v)} aria-label="lambda" />
              <p className="text-sm">
                Error against T2 (mean squared logit gap):{' '}
                <span className="font-mono tabular-nums">{err.toFixed(3)}</span>
                <span className="text-muted-foreground"> vs {err0.toFixed(3)} carrying T1 forward unchanged</span>
              </p>
            </div>
          </Figure>
        </div>
      </Section>

      {/* 4 ---------------------------------------------------------------- */}
      <Section id="question" eyebrow="4 · Formally" title="The research question">
        <div className="rounded-2xl border bg-gradient-to-br from-muted/60 to-background p-6 sm:p-8">
          <p className="text-xs font-medium tracking-widest text-muted-foreground uppercase">RQ</p>
          <p className="mt-2 text-xl leading-relaxed font-medium text-balance sm:text-2xl">
            For people screened at <Tex tex="t_0 < t_1" />, does the offset <Tex tex={String.raw`\delta_{01}`} /> between
            Sybil&rsquo;s two predictions carry information about future lung cancer beyond the newest
            prediction <Tex tex="F_1" />, and does using it bring this year&rsquo;s estimate closer to next year&rsquo;s?
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2 rounded-xl border p-4">
            <p className="font-medium">Hypotheses</p>
            <Tex block tex={String.raw`H_0:\ \lambda_h = 0 \ \ \forall h \qquad H_1:\ \exists\, h:\ \lambda_h \neq 0`} />
            <p className="text-sm text-muted-foreground">
              Under <Tex tex="H_0" />, (5) collapses to a fixed recalibration of T1, and (7) to <Tex tex="F_1" /> itself:
              the history adds nothing.
            </p>
          </div>
          <div className="space-y-2 rounded-xl border p-4">
            <p className="font-medium">Two targets</p>
            <ol className="list-decimal space-y-1.5 pl-5 text-sm text-muted-foreground">
              <li><span className="text-foreground">Agreement:</span> does <Tex tex={String.raw`\hat F_2`} /> sit closer to T2&rsquo;s own curve than carrying T1 forward (<Tex tex={String.raw`\lambda=0`} />)? Mean squared logit error, per year.</li>
              <li><span className="text-foreground">Outcome:</span> does <Tex tex={String.raw`F^\star_1`} /> rank and calibrate real diagnoses better than <Tex tex="F_1" />? Time-dependent AUC at <Tex tex="h=1..5" />, Uno&rsquo;s C-index, Brier score.</li>
            </ol>
          </div>
          <div className="space-y-2 rounded-xl border p-4">
            <p className="font-medium">Protocol</p>
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted-foreground">
              <li>Run the ensemble on T0, T1 and T2 for all {COHORT.threeRounds.toLocaleString()} participants with three readable rounds.</li>
              <li>Fit <Tex tex={String.raw`\alpha_h,\lambda_h`} /> in 5-fold cross-validation, grouped by participant.</li>
              <li>Paired bootstrap (participants resampled) for 95% intervals on every difference; DeLong for AUCs.</li>
              <li>Report per year <Tex tex="h" />, and for cancers diagnosed before vs after T2 separately.</li>
            </ul>
          </div>
          <div className="space-y-2 rounded-xl border p-4">
            <p className="font-medium">What could fool us</p>
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted-foreground">
              <li><span className="text-foreground">Sybil was trained on NLST.</span> Only its held-out test participants give an honest estimate.</li>
              <li><span className="text-foreground">Structural offset.</span> Sybil front-loads risk into year 1, so (3) always sits below a fresh curve. <Tex tex={String.raw`\alpha_h`} /> must absorb that, or <Tex tex={String.raw`\lambda`} /> will look good for the wrong reason.</li>
              <li><span className="text-foreground">Survivorship.</span> People diagnosed between scans never get a T1 or T2, so the cohort is conditioned on <Tex tex={String.raw`T>t_2`} /> for target 1.</li>
              <li><span className="text-foreground">Uneven spacing.</span> Real gaps between rounds run from 0.86 to 1.25 years (5th to 95th percentile), so (3) uses each person&rsquo;s actual <Tex tex={String.raw`\Delta`} />, never &ldquo;one year&rdquo;.</li>
            </ul>
          </div>
        </div>
      </Section>

      {/* 5 ---------------------------------------------------------------- */}
      <Section id="method" eyebrow="5 · The study" title="From 19,758 people to an answer">
        <PipelineDiagram />
      </Section>

      <div className="flex flex-col items-center gap-2 pt-4 text-center">
        <p className="text-sm text-muted-foreground">Below: pick a real participant and run Sybil on one of their scans yourself.</p>
        <ArrowDown className="size-5 animate-bounce text-muted-foreground" aria-hidden />
      </div>
    </div>
  )
}
