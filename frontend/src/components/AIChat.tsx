import { useState } from 'react';
import { Send, User, Bot, Sparkles } from 'lucide-react';

export default function AIChat() {
  const [messages, setMessages] = useState([
    { role: 'ai', content: 'Hello! I am FinSight AI. I am actively monitoring your portfolio. How can I help you today?' },
    { role: 'user', content: 'What is the current sentiment on Reliance?' },
    { role: 'ai', content: 'Based on my analysis of 14 recent articles, the sentiment on RELIANCE.NS is **bullish** (score: +0.65). RSI is at 58, indicating neutral momentum. I recommend holding your current position.' }
  ]);
  const [input, setInput] = useState('');

  const handleSend = () => {
    if (!input.trim()) return;
    setMessages([...messages, { role: 'user', content: input }]);
    setInput('');
    // Simulate AI thinking (Backend integration in Checkpoint 8)
    setTimeout(() => {
      setMessages(prev => [...prev, { role: 'ai', content: 'This is a placeholder response. In Checkpoint 8, this will be connected to the LangGraph AI orchestrator!' }]);
    }, 1000);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-2rem)] max-w-4xl mx-auto p-6">
      <div className="flex items-center space-x-2 mb-6">
        <Sparkles className="h-6 w-6 text-primary" />
        <h1 className="text-2xl font-bold">AI Advisor</h1>
      </div>

      <div className="flex-1 overflow-y-auto space-y-6 mb-6 pr-4">
        {messages.map((msg, idx) => (
          <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`flex items-start max-w-[80%] ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
              <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${msg.role === 'user' ? 'bg-primary/20 text-primary ml-3' : 'bg-blue-500/20 text-blue-400 mr-3'}`}>
                {msg.role === 'user' ? <User size={16} /> : <Bot size={16} />}
              </div>
              <div className={`p-4 rounded-2xl ${msg.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-card border shadow-sm'}`}>
                <p className="text-sm leading-relaxed">{msg.content}</p>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="relative">
        <input 
          type="text" 
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Ask me about a stock, your portfolio, or market trends..."
          className="w-full bg-card border rounded-xl py-4 pl-4 pr-12 focus:outline-none focus:ring-2 focus:ring-primary/50 text-sm"
        />
        <button 
          onClick={handleSend}
          className="absolute right-2 top-1/2 -translate-y-1/2 p-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
        >
          <Send size={16} />
        </button>
      </div>
    </div>
  );
}
