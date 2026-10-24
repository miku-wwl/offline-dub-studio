import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import App from './App'

vi.mock('./api', () => ({
  api: {
    health: async () => ({ status: 'ok' }),
    projectTranslation: async () => ({glossary:{}}),
    models: async () => ({ packs: [], operations: {} }), jobs: async () => ({ jobs: [] }),
    inbox: async () => ({ files: [] }), voices: async () => ({ voices: [] }),
    diagnostics: async () => ({ cpu_count: 4, data_free_bytes: 1, offline_inference: false }),
  },
}))

describe('Offline Dub Studio dashboard', () => {
  it('shows a local-first conversion workspace', async () => {
    render(<App />)
    expect(await screen.findByText('Start with a video')).toBeInTheDocument()
    expect(await screen.findByText(/4 CPU threads/)).toBeInTheDocument()
    expect(screen.getByText('Model readiness')).toBeInTheDocument()
    expect(screen.getByText('Recent conversions')).toBeInTheDocument()
  })
})
