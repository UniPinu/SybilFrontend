import katex from 'katex'
import 'katex/dist/katex.min.css'
import { useMemo } from 'react'

/** KaTeX, rendered once per expression. `block` centres it on its own line. */
export function Tex({ tex, block = false, className }: { tex: string; block?: boolean; className?: string }) {
  const html = useMemo(
    () => katex.renderToString(tex, { displayMode: block, throwOnError: false, strict: 'ignore' }),
    [tex, block],
  )
  return block ? (
    <div className={`overflow-x-auto py-1 ${className ?? ''}`} dangerouslySetInnerHTML={{ __html: html }} />
  ) : (
    <span className={className} dangerouslySetInnerHTML={{ __html: html }} />
  )
}
