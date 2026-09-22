import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir:'./e2e', timeout:60000, workers:1,
  outputDir:'../test-results',
  reporter:[['list'],['html',{outputFolder:'../playwright-report',open:'never'}]],
  use:{baseURL:'http://127.0.0.1:8765', headless:true, viewport:{width:1440,height:1000},
    screenshot:'only-on-failure',trace:'retain-on-failure',launchOptions:process.env.BROWSER_EXECUTABLE ? {executablePath:process.env.BROWSER_EXECUTABLE} : {}},
  webServer:{command:'../.venv/bin/python -m uvicorn backend.app.api.main:app --host 127.0.0.1 --port 8765',
    url:'http://127.0.0.1:8765/api/v1/health',reuseExistingServer:false,
    env:{...process.env,PYTHONPATH:'..'},timeout:30000}
});
