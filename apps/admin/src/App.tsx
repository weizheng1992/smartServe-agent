import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router';
import { AdminLayout } from './components/layout';
import {
  AuditsPage,
  BillingPage,
  ConversationsPage,
  EvalsPage,
  GuardrailsPage,
  PersonasPage,
  RagStudioPage,
  SkillsToolsPage,
  SystemLogsPage,
  TenantsPage,
} from './pages';

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AdminLayout />}>
          <Route path="/" element={<Navigate to="/tenants" replace />} />
          <Route path="/tenants" element={<TenantsPage />} />
          <Route path="/conversations" element={<ConversationsPage />} />
          <Route path="/audits" element={<AuditsPage />} />
          <Route path="/personas" element={<PersonasPage />} />
          <Route path="/rag-studio" element={<RagStudioPage />} />
          <Route path="/skills-tools" element={<SkillsToolsPage />} />
          <Route path="/evals" element={<EvalsPage />} />
          <Route path="/billing" element={<BillingPage />} />
          <Route path="/guardrails" element={<GuardrailsPage />} />
          <Route path="/system-logs" element={<SystemLogsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/tenants" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
