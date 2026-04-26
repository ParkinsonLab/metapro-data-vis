import _ from 'lodash'
import { DatabaseSync } from 'node:sqlite'

let db;

type TaxResultRow = {
  c_name: string
  p_name: string
  c_id: number
  p_id: number | null
}
type PathwayNodeRow = {
  id: string
  label: string
  x: number
  y: number
  type: string
}
type PathwayEdgeRow = {
  source: string
  source_name: string
  target: string
  target_name: string
}
type PathwayRow = {
  ec: string
  pathway_id: number
  pathway: string
  superpathway: string
}
type PathwaySummary = {
  id: number
  name: string
}

const check_db = (): boolean => {
  try {
    db = new DatabaseSync('resources/db/taxonomy.db')
    return true
  } catch (error) {
    return false
  }
}

check_db() // lets the following code work in tests

const get_parents_at_level = (names: string[], rank: string) => {
  // assumes that level is one of ['realm', 'kingdom', 'phylum', 'class', 'order', 'family', 'genus']

  const placeholders = names.map(() => '?').join(', ')
  const q = `
    WITH nsq AS (
      SELECT tax_id, name FROM names
      WHERE name IN (${placeholders})
    )
    SELECT
      nsq.name AS c_name,
      nsq.tax_id AS c_id,
      np.name AS p_name,
      parents.t_${rank} AS p_id
    FROM nsq
    LEFT JOIN parents ON nsq.tax_id == parents.tax_id
    LEFT JOIN names np ON np.tax_id == parents.t_${rank} 
  `
  const q_res: Array<TaxResultRow> = db.prepare(q).all(...names) as Array<TaxResultRow>
  const res_entries = q_res.map((e) => [e.c_name, e.p_name])
  const all_cats = q_res.map((e) => e.p_name)

  // the input can include terms at the same rank as the rank parameter
  // e.g. Bacteria for kingdom. we want these to match to themselves
  const backfill_entries = res_entries
    .filter((e) => !e[1])
    .map((e) => {
      if (all_cats.includes(e[0])) {
        return [e[0], e[0]]
      }
      return null
    })
  return Object.fromEntries(res_entries.filter((e) => e[1]).concat(_.compact(backfill_entries)))
}

const get_parents_multilevel = (names: string[], levels: string[]) => {
  const raw_res = levels.map((e) => get_parents_at_level(names, e))
  const res = names.map((e) => ({
    id: e,
    ...Object.fromEntries(levels.map((e2, i) => [e2, raw_res[i][e]]))
  }))
  return res
}

/**
 * Look up the nodes and edges that compose a single pathway, by readable name.
 *
 * Previously this took the integer `pathway_id`. Renderers only ever know the
 * pathway *name* (it's what we surface in the chord/network UI), and the old
 * code path silently passed the name into a query that compared against the
 * integer key (`WHERE pathway == ${pathway_id}`), so it always returned 0
 * rows. Now we resolve the name -> id with a parameterized query first.
 *
 * Returns empty `{ nodes: [], edges: [] }` if the name doesn't exist in the
 * `pathway_superpathways` table.
 */
const get_pathway_info = (pathway_name: string) => {
  const id_q = `SELECT id FROM pathway_superpathways WHERE name = ?`
  const id_res = db.prepare(id_q).all(pathway_name) as Array<{ id: number }>
  if (id_res.length === 0) {
    return { nodes: [] as PathwayNodeRow[], edges: [] as PathwayEdgeRow[] }
  }
  const pathway_id = id_res[0].id

  const node_q = `
    SELECT
      id, name AS label, x, y, type
    FROM pathway_nodes
    WHERE pathway = ?
  `
  const edge_q = `
    SELECT
      n_source.id AS source,
      n_source.name AS source_label,
      n_target.id AS target,
      n_target.name AS target_label
    FROM pathway_edges edge
    LEFT JOIN pathway_nodes n_source ON n_source.id = edge.source
    LEFT JOIN pathway_nodes n_target ON n_target.id = edge.target
    WHERE edge.pathway = ?
  `
  const node_res = db.prepare(node_q).all(pathway_id) as Array<PathwayNodeRow>
  const edge_res = db.prepare(edge_q).all(pathway_id) as Array<PathwayEdgeRow>

  return { nodes: node_res, edges: edge_res }
}

/**
 * Lists every pathway belonging to a given superpathway, in DB-row order.
 * Used by the Network pane to render the clickable pathway grid.
 */
const get_pathways_in_superpathway = (superpathway_name: string): PathwaySummary[] => {
  const q = `
    SELECT psp.id AS id, psp.name AS name
    FROM pathway_superpathways psp
    LEFT JOIN superpathways sp ON psp.superpathway = sp.id
    WHERE sp.name = ?
  `
  return db.prepare(q).all(superpathway_name) as PathwaySummary[]
}

const get_superpathway_info = () => {
  const q = `
    SELECT
      node.name AS ec,
      psp.id AS pathway_id,
      psp.name AS pathway,
      sp.name AS superpathway
    FROM pathway_nodes node
    LEFT JOIN pathway_superpathways psp ON psp.id = node.pathway
    LEFT JOIN superpathways sp ON psp.superpathway = sp.id
  `
  const res: Array<PathwayRow> = db.prepare(q).all() as Array<PathwayRow>
  return res
}

/**
 * Resolve a numeric NCBI tax_id to a name. If the id is missing from the
 * bundled DB, returns the id verbatim so callers can still render *something*.
 *
 * Pass a `missing` Set if you want to collect the misses for an aggregate
 * warning instead of logging one line per miss (very noisy on real fixtures
 * where a single TSV can have hundreds of unknown ids).
 */
const get_name_from_id = (id, missing?: Set<string | number>): string => {
  const q_res = db.prepare('SELECT name FROM names WHERE tax_id = ?').all(id) as Array<{
    name: string
  }>
  if (q_res.length === 0) {
    if (missing) {
      missing.add(id)
    } else {
      console.log(`${id} not found in name db`)
    }
    return id
  }
  return q_res[0].name
}

export {
  get_parents_at_level,
  get_superpathway_info,
  get_pathway_info,
  get_pathways_in_superpathway,
  get_parents_multilevel,
  check_db,
  get_name_from_id
}
