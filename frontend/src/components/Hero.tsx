import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { READ_ONLY, type Health } from '@/lib/api'
import { Archive, Download } from 'lucide-react'

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

/** Above the try-it-yourself part of the homepage: setup and read-only notices, and the FAQ. */
export function HomeNotices({ health }: { health: Health | undefined }) {
  // a snapshot's health describes the machine it was taken on, not this site
  const weightsMissing = !READ_ONLY && health && !health.weights_present
  const noCandidates = !READ_ONLY && health && !health.candidates.available

  return (
    <section id="try" className="section-anchor space-y-6 border-t pt-12">
      <div className="space-y-2">
        <p className="text-xs font-medium tracking-widest text-muted-foreground uppercase">6 · Try it yourself</p>
        <h2 className="text-2xl font-semibold sm:text-3xl">One scan, six years ahead</h2>
        <p className="max-w-2xl text-muted-foreground">
          Pick a real person from the screening trial, look at their scan, run Sybil on it, and then find
          out what actually happened to them.
        </p>
      </div>

      {READ_ONLY && (
        <Alert>
          <Archive className="size-4" />
          <AlertTitle>Showing results that were already computed</AlertTitle>
          <AlertDescription>
            Everyone you can pick here has already been through Sybil, so you see the real model's
            output, replayed. Running Sybil on new scans is switched off on this site for now.
          </AlertDescription>
        </Alert>
      )}

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
