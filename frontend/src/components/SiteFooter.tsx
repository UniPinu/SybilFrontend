import { Separator } from '@/components/ui/separator'
import { READ_ONLY, type Health } from '@/lib/api'

export function SiteFooter({ health }: { health: Health | undefined }) {
  return (
    <footer id="about" className="section-anchor space-y-4 pt-8 pb-16 text-sm text-muted-foreground">
      <Separator />
      <div className="grid gap-6 md:grid-cols-3">
        <div className="space-y-2">
          <p className="font-medium text-foreground">About this demo</p>
          <p>
            It runs the published Sybil model (MIT licence) on single de-identified chest CT scans
            from the National Lung Screening Trial, fetched one at a time from the NCI Imaging Data
            Commons and deleted again after processing.
          </p>
        </div>
        <div className="space-y-2">
          <p className="font-medium text-foreground">Credit where it is due</p>
          <p>
            Mikhael, Wohlwend, Yala et al., <em>Sybil: a validated deep learning model to predict
            future lung cancer risk from a single low-dose chest computed tomography</em>, J Clin
            Oncol 2023.
          </p>
          <p>
            National Lung Screening Trial Research Team (2013). Data from the National Lung Screening
            Trial (NLST). The Cancer Imaging Archive. CC BY 4.0.{' '}
            <a
              className="underline underline-offset-4"
              href="https://doi.org/10.7937/TCIA.HMQ8-J677"
              target="_blank"
              rel="noreferrer"
            >
              doi:10.7937/TCIA.HMQ8-J677
            </a>
          </p>
        </div>
        <div className="space-y-2">
          <p className="font-medium text-foreground">
            {READ_ONLY ? 'Where these results come from' : 'This machine'}
          </p>
          {READ_ONLY ? (
            <ul className="space-y-1">
              <li>model: {health?.model_name ?? 'sybil_ensemble'}, run ahead of time</li>
              <li>people with results: {health?.cache.patients_ready ?? '-'}</li>
              <li>running new scans: switched off for now</li>
            </ul>
          ) : health ? (
            <ul className="space-y-1">
              <li>
                model: {health.model_name} on {health.device} ({health.threads} threads)
              </li>
              <li>
                prepared people: {health.cache.patients_ready} ({health.cache.pool} pool,{' '}
                {health.cache.reference} reference)
              </li>
              <li>
                candidate exams: {health.candidates.exams?.toLocaleString() ?? '-'} from{' '}
                {health.candidates.participants?.toLocaleString() ?? '-'} participants
              </li>
              <li>cache on disk: {health.cache.cache_mb} MB</li>
            </ul>
          ) : (
            <p>Backend not reachable.</p>
          )}
        </div>
      </div>
      <Separator />
      <p className="font-medium">
        Research demonstration using public, de-identified trial data. Not for medical decisions.
      </p>
    </footer>
  )
}
