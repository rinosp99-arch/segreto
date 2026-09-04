import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { adminLogin } from '@/lib/adminApi';
import { Btn, TextInput, Field } from '@/pages/admin/ui';
import { ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';

export default function AdminLogin() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await adminLogin(email, password);
      localStorage.setItem('ls_admin_token', res.token);
      toast.success('Accesso effettuato');
      navigate('/admin/dashboard');
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Credenziali non valide');
    } finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-5 bg-background text-foreground grain">
      <form onSubmit={submit} className="glass rounded-2xl card-elev-2 w-full max-w-sm p-8">
        <div className="flex justify-center mb-5">
          <div className="h-12 w-12 rounded-full flex items-center justify-center" style={{ background: 'hsl(var(--primary)/0.14)', border: '1px solid hsl(var(--primary)/0.4)' }}>
            <ShieldCheck className="h-6 w-6" style={{ color: 'hsl(var(--primary))' }} />
          </div>
        </div>
        <div className="caps-label gold-text text-center mb-1">Area riservata</div>
        <h1 className="font-serif text-2xl text-center mb-6">Pannello LATO SEGRETO</h1>
        <Field label="Email"><TextInput type="email" value={email} onChange={(e) => setEmail(e.target.value)} data-testid="admin-email" required /></Field>
        <Field label="Password"><TextInput type="password" value={password} onChange={(e) => setPassword(e.target.value)} data-testid="admin-password" required /></Field>
        <Btn type="submit" disabled={busy} className="w-full mt-2" data-testid="admin-login-button">{busy ? 'Accesso…' : 'Entra'}</Btn>
      </form>
    </div>
  );
}
