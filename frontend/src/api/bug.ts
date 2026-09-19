import { postJson } from './client'

export interface Bug {
  id: number
  title: string
  description: string
  severity: 'critical' | 'major' | 'minor' | 'trivial'
  status: 'open' | 'fixing' | 'fixed' | 'closed'
  reporter_id: number
  assignee_id: number
  created_at: string
  updated_at: string
  fixed_at?: string
  closed_at?: string
}

export interface BugWithNames extends Bug {
  reporter_name: string
  assignee_name: string
}

export interface ListBugsResponse {
  bugs: BugWithNames[]
  total: number
}

export function createBug(data: { title: string; description?: string; severity?: string; assignee_id: number }) {
  return postJson<Bug>('/bug/create', data, { authRequired: true })
}

export function updateBugStatus(bugId: number, status: string) {
  return postJson<Bug>('/bug/updateStatus', { bug_id: bugId, status }, { authRequired: true })
}

export function listBugs(data: { status?: string; role?: string; limit?: number }) {
  return postJson<ListBugsResponse>('/bug/list', data, { authRequired: true })
}