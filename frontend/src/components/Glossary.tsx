import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'
import type { ReactNode } from 'react'

const TERMS: Record<string, { title: string; body: string }> = {
  slice: {
    title: 'Slice',
    body: 'A CT scanner does not take one photograph. It takes a stack of cross-sections through the chest, each a few millimetres thick. One of those cross-sections is a slice.',
  },
  'low-dose CT': {
    title: 'Low-dose CT',
    body: 'A chest CT taken with much less radiation than a diagnostic one - roughly the amount you get from the environment in six months. It is the scan used for lung-cancer screening.',
  },
  nodule: {
    title: 'Nodule',
    body: 'A small round spot in the lung, usually under 3 cm. Most nodules are harmless scars or healed infections; a few turn out to be early cancer, which is why they get followed over time.',
  },
  'pack-years': {
    title: 'Pack-years',
    body: 'Packs smoked per day multiplied by years smoked. Everyone in this trial had at least 30 pack-years and was between 55 and 74.',
  },
  'screening round': {
    title: 'Screening round',
    body: 'Trial participants were scanned three times, a year apart: T0 at the start, then T1 and T2. The round tells you which of those scans you are looking at.',
  },
  attention: {
    title: 'Attention',
    body: 'Inside Sybil, each part of the scan gets a weight saying how much it contributed to the final number. Drawing those weights over the image shows where the model was looking - not a diagnosis, and not a tumour outline.',
  },
  calibration: {
    title: 'Calibration',
    body: 'The raw output of a neural network is just a number between 0 and 1. Calibration maps it onto real-world frequencies, so that "7%" means about 7 in 100 people like this were diagnosed.',
  },
  'C-index': {
    title: 'C-index',
    body: 'Take two people, one diagnosed earlier than the other. The C-index is how often the model gave the earlier case the higher risk. 0.5 is a coin flip; 1.0 is perfect ordering.',
  },
  AUC: {
    title: 'AUC',
    body: 'Take one person who was diagnosed and one who was not. The AUC is how often the model gives the diagnosed person the higher risk. 0.5 is a coin flip; 1.0 is perfect.',
  },
}

export function Term({ term, children }: { term: keyof typeof TERMS | string; children?: ReactNode }) {
  const entry = TERMS[term]
  if (!entry) return <>{children ?? term}</>
  return (
    <HoverCard openDelay={120}>
      <HoverCardTrigger asChild>
        <button
          type="button"
          className="cursor-help underline decoration-dotted decoration-muted-foreground underline-offset-4"
        >
          {children ?? term}
        </button>
      </HoverCardTrigger>
      <HoverCardContent className="w-80 text-sm">
        <p className="font-medium">{entry.title}</p>
        <p className="pt-1 text-muted-foreground">{entry.body}</p>
      </HoverCardContent>
    </HoverCard>
  )
}
