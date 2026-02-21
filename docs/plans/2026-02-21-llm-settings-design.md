# LLM Settings + LiteLLM Integration Design

## Overview

Add LLM model selection and API key configuration to the authoring-ui, backed by
LiteLLM integration in the Python authoring service. OpenAI models are prioritized
with Gemini as fallback.

## Approach: DSPy + LiteLLM Adapter

Keep existing DSPy signatures and ChainOfThought programs. Configure `dspy.LM()`
with LiteLLM-compatible model strings (`openai/gpt-4o`, `gemini/gemini-2.5-flash`).

## Model List

**OpenAI:**
- `gpt-4o` — flagship multimodal
- `gpt-4o-mini` — fast/cheap
- `o3-mini` — reasoning

**Gemini:**
- `gemini-2.5-flash` — fast/cheap
- `gemini-2.0-flash` — stable
- `gemini-2.5-pro` — best quality

## Backend Changes

### 1. New: `app/llm_config.py`
- In-memory LLM config store (singleton dataclass)
- `configure_llm(model, openai_key, gemini_key)` → calls `dspy.configure(lm=...)`
- Priority: OpenAI key present → use OpenAI model; else Gemini key → use Gemini model
- `get_current_config()` → returns model name, provider, key masked status

### 2. New: `app/api/llm_settings.py`
- `GET /llm-settings` — current config (keys masked as `sk-...xxxx`)
- `POST /llm-settings` — set model + API keys, triggers `configure_llm()`
- `GET /llm-settings/models` — available model list grouped by provider

### 3. Modified: `app/main.py`
- Include `llm_settings.router`

### 4. Dependencies
- Add `litellm` to pyproject.toml

## Frontend Changes

### 1. New: Settings Modal (`components/LlmSettingsModal.tsx`)
- OpenAI API Key input (password type)
- Gemini API Key input (password type)
- Model dropdown (grouped by provider)
- Save button → POST /llm-settings
- Status indicator (configured/not configured)

### 2. Modified: `components/Toolbar.tsx`
- Add Settings gear button that opens LlmSettingsModal

### 3. Modified: `components/AiChatPanel.tsx`
- Show current model name in header
- Show "Configure LLM in Settings" hint when not configured

### 4. Modified: `utils/authoringClient.ts`
- Add `getLlmSettings()`, `setLlmSettings()`, `getAvailableModels()` functions

## Data Flow

```
Settings Modal → POST /llm-settings {model, openaiKey, geminiKey}
  → llm_config.configure_llm()
    → dspy.LM('openai/gpt-4o', api_key='sk-...')
    → dspy.configure(lm=lm)

Chat Input → POST /compile-intent {goal, procedure, domain}
  → _is_dspy_configured() returns True
  → _compile_with_dspy() → ChainOfThought(IntentToWorkflowSignature)
    → LiteLLM → OpenAI API → JSON response
  → parse → validate → return recipe
```

## Fallback Logic

1. Both keys provided → OpenAI primary, Gemini secondary (manual switch via model dropdown)
2. Only OpenAI key → OpenAI models only
3. Only Gemini key → Gemini models only
4. No keys → rule-based fallback (current behavior)
