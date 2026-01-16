import _ from 'lodash'
import { DatabaseSync } from 'node:sqlite'

const db = new DatabaseSync('resources/db/taxonomy.db')

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
  pathway_name: string
  superpathway: string
}

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
  const res = Object.fromEntries(names.map((e) => [e, Object.fromEntries(levels.map((e2, i) => ([e2, raw_res[i][e] ])))]))
  return res
}

const get_pathway_info = (pathway_id) => {
  const node_q = `
        SELECT
            id, name AS label, x, y, type
        FROM pathway_nodes
        WHERE pathway == ${pathway_id}
    `
  const edge_q = `
        SELECT
            n_source.id AS source,
            n_source.name AS source_label,
            n_target.id AS target,
            n_target.name AS target_label
        FROM pathway_edges edge
        LEFT JOIN pathway_nodes n_source ON n_source.id == edge.source
        LEFT JOIN pathway_nodes n_target ON n_target.id == edge.target
        WHERE edge.pathway == ${pathway_id}
    `
  const node_res: Array<PathwayNodeRow> = db.prepare(node_q).all() as Array<PathwayNodeRow>
  const edge_res: Array<PathwayEdgeRow> = db.prepare(edge_q).all() as Array<PathwayEdgeRow>

  return { nodes: node_res, edges: edge_res }
}

const get_superpathway_info = () => {
  const q = `
        SELECT
            node.name AS ec,
            psp.id AS pathway_id,
            psp.name AS pathway_name,
            sp.name AS superpathway
        FROM pathway_nodes node
        LEFT JOIN pathway_superpathways psp ON psp.id = node.pathway
        LEFT JOIN superpathways sp ON psp.superpathway = sp.id
    `
  const res: Array<PathwayRow> = db.prepare(q).all() as Array<PathwayRow>
  return res
}

export { get_parents_at_level, get_superpathway_info, get_pathway_info, get_parents_multilevel }
