export interface CountsData {
  index: string[]
  counts: number[]
}

export interface PathwayListValue {
  pathways: string[]
  breakdowns: Record<string, CountsData>
}

export function normalizePathwayListResponse(value: unknown): PathwayListValue {
  if (typeof value === 'object' && value !== null && 'pathways' in value) {
    const v = value as { pathways: string[]; breakdowns?: Record<string, CountsData> }
    return { pathways: v.pathways, breakdowns: v.breakdowns ?? {} }
  }
  if (Array.isArray(value)) {
    return { pathways: value as string[], breakdowns: {} }
  }
  return { pathways: [], breakdowns: {} }
}
