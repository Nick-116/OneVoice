import { useQuery } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { api } from '../api';
import { useAuth } from '../auth/AuthContext';
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  Empty,
  ErrorBox,
  Field,
  Input,
  Loading,
  Modal,
  PageHeader,
  Select,
  Table,
  Td,
  Th,
} from '../components/ui';
import { useAction } from '../lib/queries';
import { formatInZone, relativeTime } from '../lib/time';
import type { AdminUser, Role, UserPatch } from '../types';

const usersKey = ['users'] as const;

function CreateUserModal({ onClose }: { onClose: () => void }) {
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<Role>('operator');
  const create = useAction(
    (b: { username: string; display_name: string; password: string; role: Role }) => api.post<AdminUser>('/api/users', b),
    { success: (u) => `User ${u.username} created. They will enrol MFA at first sign-in.`, invalidate: [usersKey], onSuccess: onClose },
  );
  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate({ username: username.trim(), display_name: displayName.trim(), password, role });
  }
  return (
    <Modal
      open
      onClose={onClose}
      title="New user"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="user-form" variant="primary" loading={create.isPending}>
            Create user
          </Button>
        </>
      }
    >
      <form id="user-form" onSubmit={submit} className="space-y-4">
        <Field label="Username" hint="Letters, digits and . _ @ -">
          {(id) => <Input id={id} required minLength={3} maxLength={64} autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)} />}
        </Field>
        <Field label="Display name">{(id) => <Input id={id} maxLength={120} value={displayName} onChange={(e) => setDisplayName(e.target.value)} />}</Field>
        <Field label="Initial password" hint="At least 12 characters. Share it securely; the user can change it after signing in.">
          {(id) => <Input id={id} type="password" required minLength={12} maxLength={256} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
        </Field>
        <Field label="Role" hint="Operators can monitor and run live controls; admins can change configuration.">
          {(id) => (
            <Select id={id} value={role} onChange={(e) => setRole(e.target.value as Role)}>
              <option value="operator">Operator</option>
              <option value="admin">Admin</option>
            </Select>
          )}
        </Field>
      </form>
    </Modal>
  );
}

function ResetPasswordModal({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const [password, setPassword] = useState('');
  const reset = useAction((pw: string) => api.patch(`/api/users/${user.id}`, { password: pw }), {
    success: `Password reset for ${user.username}; their sessions were signed out.`,
    invalidate: [usersKey],
    onSuccess: onClose,
  });
  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title={`Reset password — ${user.username}`}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="reset-form" variant="primary" loading={reset.isPending}>
            Reset password
          </Button>
        </>
      }
    >
      <form
        id="reset-form"
        onSubmit={(e) => {
          e.preventDefault();
          reset.mutate(password);
        }}
      >
        <Field label="New password" hint="At least 12 characters.">
          {(id) => <Input id={id} type="password" required minLength={12} maxLength={256} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />}
        </Field>
      </form>
    </Modal>
  );
}

type Pending = { user: AdminUser; action: 'disable' | 'enable' | 'reset_mfa' | 'delete' | 'role'; role?: Role };

export function UsersPage() {
  const { user: me } = useAuth();
  const q = useQuery({ queryKey: usersKey, queryFn: () => api.get<AdminUser[]>('/api/users') });
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState<AdminUser | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const patch = useAction(({ id, body }: { id: number; body: UserPatch }) => api.patch(`/api/users/${id}`, body), {
    success: 'User updated',
    invalidate: [usersKey],
    onSuccess: () => setPending(null),
  });
  const del = useAction((u: AdminUser) => api.del(`/api/users/${u.id}`), {
    success: 'User deleted',
    invalidate: [usersKey],
    onSuccess: () => setPending(null),
  });

  function confirmPending() {
    if (!pending) return;
    const { user, action } = pending;
    if (action === 'delete') del.mutate(user);
    else if (action === 'disable') patch.mutate({ id: user.id, body: { disabled: true } });
    else if (action === 'enable') patch.mutate({ id: user.id, body: { disabled: false } });
    else if (action === 'reset_mfa') patch.mutate({ id: user.id, body: { reset_mfa: true } });
    else if (action === 'role' && pending.role) patch.mutate({ id: user.id, body: { role: pending.role } });
  }

  const confirmText: Record<Pending['action'], [string, string, string]> = {
    disable: ['Disable user?', 'They are signed out immediately and cannot sign in until re-enabled.', 'Disable'],
    enable: ['Enable user?', 'They will be able to sign in again.', 'Enable'],
    reset_mfa: ['Reset two-factor authentication?', 'Their authenticator is removed and they are signed out. They must enrol again at next sign-in.', 'Reset MFA'],
    delete: ['Delete user?', 'The account is permanently removed. Audit log entries keep the username.', 'Delete'],
    role: ['Change role?', 'The new permissions apply to their next request.', 'Change role'],
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Users"
        actions={
          <Button variant="primary" onClick={() => setCreating(true)}>
            + New user
          </Button>
        }
      />
      <Card>
        {q.isPending ? (
          <Loading />
        ) : q.isError ? (
          <ErrorBox error={q.error} />
        ) : q.data.length === 0 ? (
          <Empty>No users.</Empty>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>User</Th>
                <Th>Role</Th>
                <Th>MFA</Th>
                <Th>Status</Th>
                <Th>Last sign-in</Th>
                <Th />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {q.data.map((u) => {
                const self = u.id === me?.id;
                return (
                  <tr key={u.id} className={u.disabled ? 'opacity-60' : undefined}>
                    <Td>
                      <div className="font-medium">
                        {u.display_name || u.username} {self && <Badge tone="indigo">you</Badge>}
                      </div>
                      <div className="text-xs text-gray-500">{u.username}</div>
                    </Td>
                    <Td>
                      <Select
                        aria-label={`Role for ${u.username}`}
                        className="w-32 py-1"
                        value={u.role}
                        disabled={self}
                        onChange={(e) => setPending({ user: u, action: 'role', role: e.target.value as Role })}
                      >
                        <option value="operator">Operator</option>
                        <option value="admin">Admin</option>
                      </Select>
                    </Td>
                    <Td>{u.mfa_enabled ? <Badge tone="green">enrolled</Badge> : <Badge tone="amber">not enrolled</Badge>}</Td>
                    <Td>{u.disabled ? <Badge tone="red">disabled</Badge> : <Badge tone="green">active</Badge>}</Td>
                    <Td className="text-xs" >
                      <span title={formatInZone(u.last_login_at)}>{u.last_login_at ? relativeTime(u.last_login_at) : 'never'}</span>
                    </Td>
                    <Td className="whitespace-nowrap text-right">
                      <Button size="sm" variant="ghost" onClick={() => setResetting(u)}>
                        Reset password
                      </Button>
                      {u.mfa_enabled && (
                        <Button size="sm" variant="ghost" onClick={() => setPending({ user: u, action: 'reset_mfa' })}>
                          Reset MFA
                        </Button>
                      )}
                      {!self && (
                        <>
                          <Button size="sm" variant="ghost" onClick={() => setPending({ user: u, action: u.disabled ? 'enable' : 'disable' })}>
                            {u.disabled ? 'Enable' : 'Disable'}
                          </Button>
                          <Button size="sm" variant="ghost" className="text-red-700" onClick={() => setPending({ user: u, action: 'delete' })}>
                            Delete
                          </Button>
                        </>
                      )}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Card>
      {creating && <CreateUserModal onClose={() => setCreating(false)} />}
      {resetting && <ResetPasswordModal user={resetting} onClose={() => setResetting(null)} />}
      <ConfirmDialog
        open={!!pending}
        title={pending ? confirmText[pending.action][0] : ''}
        message={
          pending && (
            <>
              <strong>{pending.user.username}</strong>
              {pending.action === 'role' ? ` → ${pending.role}. ` : ': '}
              {confirmText[pending.action][1]}
            </>
          )
        }
        tone={pending?.action === 'enable' || pending?.action === 'role' ? 'primary' : 'danger'}
        confirmLabel={pending ? confirmText[pending.action][2] : 'Confirm'}
        busy={patch.isPending || del.isPending}
        onConfirm={confirmPending}
        onCancel={() => setPending(null)}
      />
    </div>
  );
}
