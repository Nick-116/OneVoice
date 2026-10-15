import type { ReactNode } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useAuth } from './auth/AuthContext';
import { Layout } from './components/Layout';
import { Loading } from './components/ui';
import { AudioPage } from './pages/Audio';
import { BrandingPage } from './pages/Branding';
import { CampusesPage } from './pages/Campuses';
import { LanguagesPage } from './pages/Languages';
import { AuditPage, ErrorsPage } from './pages/Logs';
import { LoginPage } from './pages/Login';
import { MfaPage } from './pages/Mfa';
import { OverviewPage } from './pages/Overview';
import { ProvidersPage } from './pages/Providers';
import { PrintQrPage, QrCodesPage } from './pages/QrCodes';
import { SchedulePage } from './pages/Schedule';
import { UsagePage } from './pages/Usage';
import { UpdatesPage } from './pages/Updates';
import { UsersPage } from './pages/Users';

interface FromState {
  from?: string;
}

/** Signed-in, MFA-verified users only; otherwise redirect to /login or /mfa remembering the target. */
function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const loc = useLocation();
  const from = loc.pathname + loc.search;
  if (status === 'loading') return <Loading label="Checking session…" />;
  if (status === 'anonymous') return <Navigate to="/login" replace state={{ from } satisfies FromState} />;
  if (status === 'mfa') return <Navigate to="/mfa" replace state={{ from } satisfies FromState} />;
  return <>{children}</>;
}

function AdminOnly({ children }: { children: ReactNode }) {
  const { isAdmin } = useAuth();
  return isAdmin ? <>{children}</> : <Navigate to="/" replace />;
}

function useReturnTo(): string {
  const loc = useLocation();
  const from = (loc.state as FromState | null)?.from;
  return from && from.startsWith('/') && !from.startsWith('/login') && !from.startsWith('/mfa') ? from : '/';
}

function LoginRoute() {
  const { status } = useAuth();
  const to = useReturnTo();
  const loc = useLocation();
  if (status === 'loading') return <Loading label="Checking session…" />;
  if (status === 'ready') return <Navigate to={to} replace />;
  if (status === 'mfa') return <Navigate to="/mfa" replace state={loc.state} />;
  return <LoginPage />;
}

function MfaRoute() {
  const { status } = useAuth();
  const to = useReturnTo();
  const loc = useLocation();
  if (status === 'loading') return <Loading label="Checking session…" />;
  if (status === 'ready') return <Navigate to={to} replace />;
  if (status === 'anonymous') return <Navigate to="/login" replace state={loc.state} />;
  return <MfaPage />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginRoute />} />
      <Route path="/mfa" element={<MfaRoute />} />
      <Route
        path="/print/qr/:campusId"
        element={
          <RequireAuth>
            <PrintQrPage />
          </RequireAuth>
        }
      />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<OverviewPage />} />
        <Route path="schedule" element={<SchedulePage />} />
        <Route path="campuses" element={<AdminOnly><CampusesPage /></AdminOnly>} />
        <Route path="languages" element={<LanguagesPage />} />
        <Route path="audio" element={<AudioPage />} />
        <Route path="qr" element={<QrCodesPage />} />
        <Route path="providers" element={<AdminOnly><ProvidersPage /></AdminOnly>} />
        <Route path="branding" element={<AdminOnly><BrandingPage /></AdminOnly>} />
        <Route path="updates" element={<AdminOnly><UpdatesPage /></AdminOnly>} />
        <Route path="usage" element={<UsagePage />} />
        <Route path="users" element={<AdminOnly><UsersPage /></AdminOnly>} />
        <Route path="audit" element={<AdminOnly><AuditPage /></AdminOnly>} />
        <Route path="errors" element={<ErrorsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
