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
            nu.name AS p_name,
            parents.t_${rank} AS p_id
        FROM nsq
        LEFT JOIN parents ON nsq.tax_id == parents.tax_id
        LEFT JOIN names_unique nu ON nu.tax_id == parents.t_${rank} 
    `
    const q_res: Array<ResultRow> = db.prepare(q).all(...names) as Array<ResultRow>
    const res_entries = q_res.map(e => [e.c_name, e.p_name])
    const id_map = Object.fromEntries(q_res.map(e => [e.c_name, e.c_id]))
    const cat_name_map = Object.fromEntries(q_res.map(e => [e.p_id, e.p_name]).filter((e) => e[0]))
    const all_cats = q_res.map(e => e.p_id)

    // the input can include terms at the same rank as the rank parameter
    // e.g. Bacteria for kingdom. we want these to match to themselves
    // but it might not be spelled the same way as in names_unique
    // so we need to match by ID instead 
    const backfill_entries = res_entries.filter(e => !e[1]).map(e => {
        const cid = id_map[e[0]] // gets the tax_id of the provided term
        if (all_cats.includes(cid)) {
            return [e, cat_name_map[cid]]
        }
        return null
    })
    return Object.fromEntries(res_entries.filter(e => e[1]).concat(_.compact(backfill_entries)))
}

export default get_parents_at_level;