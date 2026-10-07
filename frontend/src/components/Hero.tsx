import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { Health } from '@/lib/api'
import { Brain, Download, LineChart, ScanLine } from 'lucide-react'

const STEPS = [
  {
    icon: ScanLine,
    title: 'One ordinary CT scan',
    body: 'A low-dose chest CT, the kind used for lung screening. No contrast, no extra tests, no questionnaire.',
  },
  {
    icon: Brain,
    title: 'Sybil studies every slice',
    body: 'The scan is a stack of about 150 cross-sections. Sybil reads the whole stack at once, the way a radiologist flips through it.',
  },
  {
    icon: LineChart,
    title: 'A risk for each of the next 6 years',
    body: 'Not a yes or no. Six numbers: the chance of a lung-cancer diagnosis by year 1, 2, 3, 4, 5 and 6.',
  },
]

const FAQ = [
  {
    q: 'What is Sybil, in one paragraph?',
    a: `Sybil is a deep-learning model from MIT and Massachusetts General Hospital. It was trained on
        thousands of low-dose chest CT scans from the National Lung Screening Trial, together with what
        happened to those people afterwards. Given a single new scan it outputs the chance that the
        person will be diagnosed with lung cancer in each of the next six years.`,
  },
  {
    q: 'Does it find a tumour?',
    a: `No. It is not a detector that circles a nodule and says "cancer". It scores the whole scan for
        future risk. Sometimes it reacts to something a radiologist would also flag; sometimes it reacts
        to patterns in the lung tissue that nobody has a name for.`,
  },
  {
    q: 'Where do these people come from?',
    a: `From the National Lung Screening Trial, a US study that scanned more than 26,000 people between
        2002 and 2004 and followed them for years. The scans and the outcomes are public and
        de-identified, hosted by the NCI Imaging Data Commons. Nothing here is a patient of yours or mine.`,
  },
  {
    q: 'Is the model really running?',
    a: `Yes. Each person's six numbers come from running the published five-model Sybil ensemble on that
        person's actual scan, on this machine. The install is checked against the score vector the Sybil
        authors publish for their demo scan, to the fourth decimal place.`,
  },
]

export function Hero({ health }: { health: Health | undefined }) {
  const weightsMissing = health && !health.weights_present
  const noCandidates = health && !health.candidates.available

  return (
    <section id="how-it-works" className="section-anchor space-y-8 pt-10">
      <div className="space-y-4">
        <p className="text-sm font-medium tracking-wide text-muted-foreground uppercase">
          One scan. Six years ahead.
        </p>
        <h1 className="text-4xl leading-tight font-semibold text-balance sm:text-5xl">
          Can a computer spot lung cancer years before it appears?
        </h1>
        <p className="max-w-2xl text-lg text-muted-foreground">
          Sybil reads a single low-dose chest CT and estimates the chance of a lung-cancer diagnosis in
          each of the next six years. Pick a real person from a public screening trial, look at their
          scan, run the model, and then find out what actually happened to them.
        </p>
      </div>

      {weightsMissing && (
        <Alert>
          <Download className="size-4" />
          <AlertTitle>Sybil's weights are not downloaded yet</AlertTitle>
          <AlertDescription>
            The five model checkpoints are about 700 MB and download once. Run{' '}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              uv run python scripts/smoke_test.py
            </code>{' '}
            in the backend folder, which also checks the install against the published scores.
          </AlertDescription>
        </Alert>
      )}

      {noCandidates && (
        <Alert>
          <Download className="size-4" />
          <AlertTitle>No candidate list yet</AlertTitle>
          <AlertDescription>
            Run{' '}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              uv run python scripts/build_candidates.py
            </code>{' '}
            to index the trial's scans, then{' '}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              uv run python scripts/prepare_pool.py
            </code>{' '}
            to prepare the demo people.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        {STEPS.map((step, index) => (
          <Card key={step.title} className="h-full">
            <CardHeader>
              <div className="flex items-center gap-3">
                <span className="flex size-10 items-center justify-center rounded-full bg-muted">
                  <step.icon className="size-5" aria-hidden />
                </span>
                <span className="text-xs font-medium text-muted-foreground">Step {index + 1}</span>
              </div>
              <CardTitle className="pt-2 text-lg">{step.title}</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">{step.body}</CardContent>
          </Card>
        ))}
      </div>

      <Accordion type="single" collapsible className="max-w-3xl">
        <AccordionItem value="more">
          <AccordionTrigger className="text-base">Want to know more?</AccordionTrigger>
          <AccordionContent className="space-y-4 text-sm text-muted-foreground">
            {FAQ.map((item) => (
              <div key={item.q} className="space-y-1">
                <p className="font-medium text-foreground">{item.q}</p>
                <p>{item.a}</p>
              </div>
            ))}
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </section>
  )
}
