import { useState, useEffect } from 'react';
import Dashboard from './components/Dashboard';
import AIChat from './components/AIChat';
import Portfolio from './components/Portfolio';
import { LayoutDashboard, MessageSquare, Briefcase, Settings, LogIn, LogOut } from 'lucide-react';

export interface User {
  id: number;
  email: string;
  name: string;
  picture: string;
  balance: number;
}

function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // Check if logged in
  useEffect(() => {
    fetch('http://localhost:8001/auth/me', { credentials: 'include' })
      .then(res => {
        if (res.ok) return res.json();
        throw new Error('Not authenticated');
      })
      .then(data => setUser(data))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const [isLoggingIn, setIsLoggingIn] = useState(false);

  const handleMockLogin = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsLoggingIn(true);
    try {
      const formData = new FormData(e.currentTarget);
      const email = formData.get('email');
      const name = formData.get('name');
      
      const res = await fetch('http://localhost:8001/auth/mock-login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, name }),
        credentials: 'include'
      });
      
      if (res.ok) {
        // Fetch full profile to get balance
        const meRes = await fetch('http://localhost:8001/auth/me', { credentials: 'include' });
        if (meRes.ok) setUser(await meRes.json());
      } else {
        const errorText = await res.text();
        alert(`Login failed: ${res.status} - ${errorText}`);
      }
    } catch (err) {
      alert(`Network error connecting to backend: ${err}`);
    } finally {
      setIsLoggingIn(false);
    }
  };

  const handleLogout = async () => {
    await fetch('http://localhost:8001/auth/logout', { method: 'POST', credentials: 'include' });
    setUser(null);
  };

  if (loading) {
    return <div className="flex h-screen items-center justify-center bg-background text-primary">Loading...</div>;
  }

  if (!user) {
    return (
      <div className="flex h-screen items-center justify-center bg-background text-foreground">
        <div className="w-full max-w-md p-8 bg-card border rounded-2xl shadow-xl">
          <h2 className="text-2xl font-bold mb-6 text-center">Developer Login</h2>
          <form onSubmit={handleMockLogin} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">Name</label>
              <input name="name" required defaultValue="Harsh Masalge" className="w-full bg-background border rounded-lg p-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Email</label>
              <input name="email" type="email" required defaultValue="harsh@finsight.ai" className="w-full bg-background border rounded-lg p-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary" />
            </div>
            <button type="submit" disabled={isLoggingIn} className="w-full py-3 bg-primary text-primary-foreground font-semibold rounded-lg hover:bg-primary/90 flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed">
              <LogIn className="w-5 h-5 mr-2" />
              {isLoggingIn ? "Signing In..." : "Sign In (Mock OAuth)"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-background text-foreground overflow-hidden">
      {/* Sidebar Navigation */}
      <nav className="w-64 border-r border-gray-800 bg-card flex flex-col">
        <div className="p-6">
          <h2 className="text-2xl font-bold bg-gradient-to-r from-primary to-blue-400 bg-clip-text text-transparent">
            FinSight AI
          </h2>
        </div>
        <div className="flex-1 px-4 space-y-2">
          <NavItem 
            icon={<LayoutDashboard />} 
            label="Dashboard" 
            isActive={activeTab === 'dashboard'} 
            onClick={() => setActiveTab('dashboard')} 
          />
          <NavItem 
            icon={<Briefcase />} 
            label="Portfolio" 
            isActive={activeTab === 'portfolio'} 
            onClick={() => setActiveTab('portfolio')} 
          />
          <NavItem 
            icon={<MessageSquare />} 
            label="AI Advisor" 
            isActive={activeTab === 'ai'} 
            onClick={() => setActiveTab('ai')} 
          />
        </div>
        <div className="p-4 border-t border-gray-800 space-y-4">
          <div className="flex items-center space-x-3 px-4 py-2">
            <img src={user.picture} alt="Profile" className="w-8 h-8 rounded-full bg-gray-800" />
            <div className="flex flex-col">
              <span className="text-sm font-medium truncate">{user.name}</span>
              <span className="text-xs text-muted-foreground truncate">{user.email}</span>
            </div>
          </div>
          <button 
            onClick={handleLogout}
            className="w-full flex items-center space-x-3 px-4 py-3 rounded-lg text-red-400 hover:bg-red-500/10 transition-colors"
          >
            <LogOut size={20} />
            <span>Logout</span>
          </button>
        </div>
      </nav>

      {/* Main Content Area */}
      <main className="flex-1 overflow-y-auto">
        {activeTab === 'dashboard' && <Dashboard user={user} />}
        {activeTab === 'portfolio' && <Portfolio />}
        {activeTab === 'ai' && <AIChat />}
      </main>
    </div>
  );
}

function NavItem({ icon, label, isActive, onClick }: { icon: React.ReactNode, label: string, isActive: boolean, onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg transition-all ${
        isActive 
          ? 'bg-primary/10 text-primary font-medium' 
          : 'text-muted-foreground hover:bg-gray-800/50 hover:text-foreground'
      }`}
    >
      <div className={`${isActive ? 'text-primary' : 'text-gray-400'}`}>
        {icon}
      </div>
      <span>{label}</span>
    </button>
  );
}

export default App;
