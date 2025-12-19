import _ from "lodash"
import { DatabaseSync } from 'node:sqlite'

const db = new DatabaseSync('resources/db/taxonomy.db')

type ResultRow = {
    c_name: string
    p_name: string
    c_id: number
    p_id: number | null
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
    const q_res: Array<ResultRow> = db.prepare(q).all(...names) as Array<ResultRow>
    const res_entries = q_res.map(e => [e.c_name, e.p_name])
    const all_cats = q_res.map(e => e.p_name)

    // the input can include terms at the same rank as the rank parameter
    // e.g. Bacteria for kingdom. we want these to match to themselves
    const backfill_entries = res_entries.filter(e => !e[1]).map(e => {
        if (all_cats.includes(e[0])) {
            return [e[0], e[0]]
        }
        return null
    })
    return Object.fromEntries(res_entries.filter(e => e[1]).concat(_.compact(backfill_entries)))
}

export default get_parents_at_level;