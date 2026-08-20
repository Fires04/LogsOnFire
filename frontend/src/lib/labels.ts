import type { Agent, LogSource } from '../types/models'

/** Log source labels are only guaranteed unique within one agent — anywhere
 * a log source is shown alongside others from *different* agents (dashboard
 * builder, panel titles, standalone popout titles), qualify it with the
 * agent's name so it's unambiguous which host it's actually on. */
export function qualifiedLabel(agent: Pick<Agent, 'name'> | undefined | null, logSource: Pick<LogSource, 'label'>): string {
  return agent ? `${agent.name} · ${logSource.label}` : logSource.label
}
