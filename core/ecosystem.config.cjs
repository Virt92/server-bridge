// Load .agent.env directly so keys are available regardless of how PM2 daemon was started
const fs = require('fs');
const path = require('path');
const agentEnvPath = path.join(__dirname, '.agent.env');
if (fs.existsSync(agentEnvPath)) {
  const lines = fs.readFileSync(agentEnvPath, 'utf8').split('\n');
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eqIdx = trimmed.indexOf('=');
    if (eqIdx < 1) continue;
    const key = trimmed.slice(0, eqIdx).trim();
    let val = trimmed.slice(eqIdx + 1).trim();
    // Strip surrounding quotes
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }
    if (key && val) process.env[key] = val;
  }
}

const sharedEnv = {
  PYTHONUNBUFFERED: '1',
};

const optionalEnvKeys = [
  'OPENAI_API_KEY',
  'ANTHROPIC_API_KEY',
  'OPENAI_BASE_URL',
  'AI_PROVIDER',
  'AI_MODEL',
  'PM_MODEL',
  'PM_PROVIDER',
  'AI_MAX_STEPS',
  'AI_MAX_COMMANDS_PER_STEP',
  'AI_CMD_OUTPUT_CHARS',
  'AI_COMMAND_TIMEOUT_SEC',
  'AI_ROLE_PROFILE_CHARS',
  'PM_MODEL',
  'PM_MAX_SUBTASKS',
  'AI_PROVIDER_FRONTEND',
  'AI_PROVIDER_BACKEND',
  'AI_PROVIDER_DEVOPS',
  'AI_PROVIDER_QA',
  'AI_PROVIDER_PM',
  'AI_MODEL_FRONTEND',
  'AI_MODEL_BACKEND',
  'AI_MODEL_DEVOPS',
  'AI_MODEL_QA',
  'AI_MODEL_PM',
  'AI_STRATEGY_FRONTEND',
  'AI_STRATEGY_BACKEND',
  'AI_STRATEGY_DEVOPS',
  'AI_STRATEGY_QA',
  'AI_STRATEGY_PM',
  'OPENAI_API_KEY_FRONTEND',
  'OPENAI_API_KEY_BACKEND',
  'OPENAI_API_KEY_DEVOPS',
  'OPENAI_API_KEY_QA',
  'OPENAI_API_KEY_PM',
  'OPENAI_BASE_URL_FRONTEND',
  'OPENAI_BASE_URL_BACKEND',
  'OPENAI_BASE_URL_DEVOPS',
  'OPENAI_BASE_URL_QA',
  'OPENAI_BASE_URL_PM',
];

for (const key of optionalEnvKeys) {
  if (process.env[key]) {
    sharedEnv[key] = process.env[key];
  }
}

module.exports = {
  apps: [
    {
      name: 'core-api',
      script: 'python3',
      args: 'orchestrator/api_server.py --host 0.0.0.0 --port 8080',
      cwd: '/root/core',
      autorestart: true,
      watch: false,
      max_restarts: 20,
      restart_delay: 2000,
      env: { ...sharedEnv, PYTHONUNBUFFERED: '1' },
    },
    {
      name: 'orch-main',
      script: 'python3',
      args: 'orchestrator/orchestrator.py',
      cwd: '/root/core',
      autorestart: true,
      watch: false,
      max_restarts: 20,
      restart_delay: 2000,
      env: sharedEnv,
    },
    {
      name: 'agent-frontend',
      script: 'python3',
      args: 'orchestrator/agent_worker.py frontend',
      cwd: '/root/core',
      autorestart: true,
      watch: false,
      env: sharedEnv,
    },
    {
      name: 'agent-backend',
      script: 'python3',
      args: 'orchestrator/agent_worker.py backend',
      cwd: '/root/core',
      autorestart: true,
      watch: false,
      env: sharedEnv,
    },
    {
      name: 'agent-devops',
      script: 'python3',
      args: 'orchestrator/agent_worker.py devops',
      cwd: '/root/core',
      autorestart: true,
      watch: false,
      env: sharedEnv,
    },
    {
      name: 'agent-qa',
      script: 'python3',
      args: 'orchestrator/agent_worker.py qa',
      cwd: '/root/core',
      autorestart: true,
      watch: false,
      env: sharedEnv,
    },
    {
      name: 'git-sync',
      script: '/root/core/scripts/git-sync.sh',
      interpreter: 'bash',
      cwd: '/root/core',
      autorestart: true,
      watch: false,
      max_restarts: 10,
      restart_delay: 5000,
      env: {
        GIT_SYNC_INTERVAL_SEC: '1800',
        HOME: '/root',
      },
    },
    {
      name: 'office-sim',
      script: 'node',
      args: 'server.js',
      cwd: '/root/projects/office-sim',
      autorestart: true,
      watch: false,
      max_restarts: 20,
      restart_delay: 2000,
      env: { PORT: '4000' },
    },
    {
      name: 'server-bridge',
      script: 'node',
      args: 'src/server.js',
      cwd: '/root/codex-workspaces/default/server-bridge',
      autorestart: true,
      watch: false,
      max_restarts: 20,
      restart_delay: 2000,
      env: {
        HOST: '0.0.0.0',
        PORT: '3001',
        MAX_BODY_BYTES: '1048576',
        CORE_API_BASE_URL: 'http://127.0.0.1:8080',
        CORE_API_TIMEOUT_MS: '10000',
      },
    },
  ],
};
