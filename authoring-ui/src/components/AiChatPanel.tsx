import { useState, useRef, useEffect, useCallback } from 'react';
import { useRecipeStore } from '../store/recipeStore.ts';
import { compileIntent, healthCheck, getLlmSettings } from '../utils/authoringClient.ts';

interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
}

const STORAGE_KEY = 'ai-chat-history';
const SYSTEM_MSG: ChatMessage = {
  role: 'system',
  content: 'Describe the web automation you want to create.\nExample: "Go to amazon.com, search for laptop, click the first result, extract the price"',
  timestamp: 0,
};

function loadHistory(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as ChatMessage[];
      if (parsed.length > 0) return [SYSTEM_MSG, ...parsed];
    }
  } catch { /* ignore */ }
  return [SYSTEM_MSG];
}

function saveHistory(messages: ChatMessage[]) {
  // Save only user/assistant messages (skip system)
  const toSave = messages.filter((m) => m.role !== 'system');
  localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave));
}

export function AiChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>(loadHistory);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [serviceOnline, setServiceOnline] = useState<boolean | null>(null);
  const [llmModel, setLlmModel] = useState<string | null>(null);
  const [llmConfigured, setLlmConfigured] = useState<boolean>(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const importRecipe = useRecipeStore((s) => s.importRecipe);

  // Check service health and LLM config on mount + poll for config changes
  useEffect(() => {
    const checkStatus = () => {
      healthCheck().then(setServiceOnline);
      getLlmSettings().then(s => { setLlmModel(s.model); setLlmConfigured(s.isConfigured); }).catch(() => {});
    };
    checkStatus();
    const interval = setInterval(checkStatus, 3000);
    return () => clearInterval(interval);
  }, []);

  // Auto-scroll + persist to localStorage
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    saveHistory(messages);
  }, [messages]);

  const handleSubmit = useCallback(async () => {
    const text = input.trim();
    if (!text || isLoading) return;

    const userMsg: ChatMessage = { role: 'user', content: text, timestamp: Date.now() };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setInput('');
    setIsLoading(true);

    try {
      // Extract domain from text or previous messages
      const domainMatch = text.match(/(?:go\s+to|visit|open|navigate\s+to)\s+([\w.-]+\.\w{2,})/i);
      const urlMatch = text.match(/https?:\/\/([\w.-]+)/);
      const domain = domainMatch?.[1] || urlMatch?.[1] || undefined;

      // Build history from previous user/assistant messages (exclude system)
      const history = updatedMessages
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .map((m) => ({ role: m.role, content: m.content }));

      const response = await compileIntent({
        requestId: `chat-${Date.now()}`,
        goal: text,
        procedure: text,
        domain,
        history,
      });

      // Load the generated recipe into the store
      importRecipe({
        workflow: response.workflow,
        actions: response.actions,
        selectors: response.selectors,
        fingerprints: response.fingerprints,
        policies: response.policies,
      });

      const stepCount = response.workflow.steps.length;
      const actionCount = Object.keys(response.actions).length;

      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content: `Recipe generated! ${stepCount} steps, ${actionCount} actions created.\n\nWorkflow: ${response.workflow.id}\nSteps:\n${response.workflow.steps.map((s, i) => `  ${i + 1}. [${s.op}] ${s.targetKey || s.args?.url || s.args?.message || s.id}`).join('\n')}\n\nYou can now edit the flow in the canvas, or describe more changes.`,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      const errorMsg: ChatMessage = {
        role: 'assistant',
        content: `Error: ${err instanceof Error ? err.message : 'Failed to generate recipe'}.\n\nMake sure the Python authoring service is running:\n  cd python-authoring-service\n  uvicorn app.main:app --port 8321`,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  }, [input, isLoading, importRecipe, messages]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="ai-chat-panel">
      <div className="chat-header">
        <span className="chat-title">AI Recipe Generator</span>
        <span className={`chat-status ${serviceOnline === true ? 'online' : serviceOnline === false ? 'offline' : 'checking'}`}>
          {serviceOnline === true ? 'Online' : serviceOnline === false ? 'Offline' : '...'}
        </span>
        {llmModel && <span className="chat-status online" style={{ marginLeft: 4 }}>{llmModel.split('/')[1]}</span>}
      </div>

      <div className="chat-messages">
        {messages.map((msg, i) => (
          <div key={i} className={`chat-msg chat-msg-${msg.role}`}>
            <div className="chat-msg-label">
              {msg.role === 'user' ? 'You' : msg.role === 'assistant' ? 'AI' : ''}
            </div>
            <div className="chat-msg-content">{msg.content}</div>
          </div>
        ))}
        {isLoading && (
          <div className="chat-msg chat-msg-assistant">
            <div className="chat-msg-label">AI</div>
            <div className="chat-msg-content chat-loading">Generating recipe...</div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-area">
        <textarea
          ref={inputRef}
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={llmConfigured ? 'Describe your automation... (Enter to send)' : 'Configure LLM API key first (click LLM Settings)'}
          rows={3}
          disabled={isLoading || !llmConfigured}
        />
        <button
          className="chat-send-btn"
          onClick={handleSubmit}
          disabled={isLoading || !input.trim() || !llmConfigured}
        >
          {isLoading ? '...' : 'Send'}
        </button>
      </div>
    </div>
  );
}
