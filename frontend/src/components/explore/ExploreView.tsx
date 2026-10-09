import { ExploreSearch } from '@/components/explore/ExploreSearch'
import { ParticipantView } from '@/components/explore/ParticipantView'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { goTo, setParams, useSearchParams } from '@/lib/url'
import { EyeOff } from 'lucide-react'
import { useId } from 'react'

/** Search -> participant -> compare. Outcomes are shown unless `blind=1`. */
export function ExploreView() {
  const params = useSearchParams()
  const pid = params.get('participant')
  const blind = params.get('blind') === '1'
  const blindId = useId()

  return (
    <div>
      <div className="flex flex-wrap items-center justify-end gap-2 pt-4">
        <Switch id={blindId} checked={blind}
          onCheckedChange={(value) =>
            setParams(
              {
                blind: value,
                // outcome filters and sorting do not exist in blind mode
                ...(value && { diagnosed: null, sort: params.get('sort')?.endsWith('dx') ? null : undefined }),
              },
              { replace: true, state: window.history.state ?? {} },
            )
          } />
        <Label htmlFor={blindId} className="text-sm">
          <EyeOff className="size-4" aria-hidden />
          Blind mode
          <span className="text-xs font-normal text-muted-foreground">hide every outcome</span>
        </Label>
      </div>

      {pid ? (
        <ParticipantView
          key={pid}
          pid={pid}
          blind={blind}
          onBack={() => {
            // back to the same search, filters and scroll position, when we came from it
            if (window.history.state?.fromSearch) window.history.back()
            else setParams({ participant: null })
          }}
          onOpenStory={(examId) => goTo({ p: examId })}
        />
      ) : (
        <ExploreSearch
          blind={blind}
          onOpen={(id) => {
            setParams({ participant: id }, { state: { fromSearch: true } })
            window.scrollTo({ top: 0 })
          }}
        />
      )}
    </div>
  )
}
