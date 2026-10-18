import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router';
import { AdminLayout } from './components/layout';
import { authToken } from './lib/api';
import {
  AuditsPage,
  BillingPage,
  ConversationsPage,
  DashboardPage,
  EvalsPage,
  GuardrailsPage,
  PersonasPage,
  RagStudioPage,
  SkillsToolsPage,
  SystemLogsPage,
  TenantsPage,
  LoginPage,
} from './pages';

function RequireAuth({ children }: { children: React.ReactElement }) {
  // 平台闸前端半边(2026-10-18):无 token 一律回登录页
  if (!authToken()) return <Navigate to="/login" replace />;
  return children;
}

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <RequireAuth>
              <AdminLayout />
            </RequireAuth>
          }
        >
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
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
