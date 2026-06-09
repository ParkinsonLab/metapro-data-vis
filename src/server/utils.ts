const key_cols = ['EC#', 'GeneID', 'Length', 'Reads', 'RPKM', 'Unclassified']

const sum = (arr: number[]): number => {
  return arr.reduce((acc, e) => (acc += e), 0)
}

const mean = (arr: number[]): number => {
  return arr.reduce((acc, e) => (acc += e), 0) / arr.length
}

const base_lum = 50
// produces a 'hash' from a string and maps it to luminsity from 20-100
// low lum is just black
const map_lum = (string) => {
  let hash = 0
  for (const char of string) {
    hash = (hash << 5) - hash + char.charCodeAt(0)
    hash |= 0 // Constrain to 32bit integer
  }
  return Math.abs(Math.trunc(hash % 80)) + 20
}

const get_color = (i, n) => `hsl(${Math.trunc((360 / (n + 1)) * i)} 75 ${base_lum})`

// const get_sub_color = (c, e) => c.replace(` ${base_lum})`, ` ${map_lum(e)})`)

/** Builds a map from key-value pairs: each key maps to an array of unique values it was paired with. */
const reduce_to_dict = (pairs): Record<string, string[]> => {
  const map = pairs.reduce((acc, [k, v]) => {
    if (!acc.has(k)) acc.set(k, new Set())
    acc.get(k)!.add(v)
    return acc
  }, new Map())
  return Object.fromEntries([...map.entries()].map(([k, set]) => [k, Array.from(set)]))
}

const empty_filter = { level: '', name: '' }

export { map_lum, get_color, sum, mean, key_cols, reduce_to_dict, empty_filter }
