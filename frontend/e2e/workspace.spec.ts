import { test, expect } from '@playwright/test';
import path from 'node:path';
import fs from 'node:fs';

test('local-video workspace: create, batch import, process, exclude, reinclude and refresh', async ({page}) => {
  await page.goto('/');
  await expect(page.getByText('本地视频 · 模拟模型')).toBeVisible();
  await expect(page.getByRole('heading', {name:'你想拍出一条什么样的视频？'})).toBeVisible();
  await page.getByLabel('成片目标').fill('展示一家咖啡馆的环境和招牌饮品');
  await page.getByLabel('拍摄条件').fill('室内桌面，保持连接处无遮挡');
  await page.getByRole('button', {name:'创建项目并生成分镜 →'}).click();
  await expect(page.getByRole('button',{name:'确认并锁定清单 →'})).toBeEnabled();
  await page.getByRole('button',{name:'确认并锁定清单 →'}).click();
  await page.getByLabel('我确认所选文件是普通视角视频').check();
  const fixtureRoot = path.join(process.env.BOLD_DATA_DIR ?? path.resolve('../data'), 'simulator');
  const catalog = JSON.parse(fs.readFileSync(path.join(fixtureRoot, 'catalog.json'), 'utf8'));
  const fixtures = catalog.groups.slice(0, 2).map((group:{members:string[]}) => path.join(fixtureRoot, group.members[0]));
  await page.getByLabel('导入本地视频').setInputFiles(fixtures);
  await expect(page.locator('.clip')).toHaveCount(2);
  await expect(page.locator('.clip').filter({hasText:'分析完成'})).toHaveCount(2, {timeout:30000});
  await expect(page.getByText('连接相机')).toHaveCount(0);
  await expect(page.getByText('同步会话')).toHaveCount(0);
  const first = page.locator('.clip').first();
  await first.getByRole('button',{name:'排除',exact:true}).click();
  await expect(first.getByRole('button',{name:'重新纳入',exact:true})).toBeVisible();
  await first.getByRole('button',{name:'重新纳入',exact:true}).click();
  await expect(first).toContainText('分析完成', {timeout:30000});
  await page.reload();
  await expect(page.locator('.clip')).toHaveCount(2);
});

test('real Qwen video E2E when BOLD_E2E_VIDEO_FILES is supplied', async ({page}) => {
  const configured = process.env.BOLD_E2E_VIDEO_FILES?.split(path.delimiter).filter(Boolean) ?? [];
  test.skip(!configured.length || process.env.BOLD_SIMULATION === '1',
    'Set BOLD_E2E_VIDEO_FILES to real local video paths and run without simulation.');
  await page.goto('/');
  await expect(page.getByText('本地视频 · 千问视觉模型')).toBeVisible();
  await page.getByLabel('成片目标').fill(process.env.BOLD_E2E_GOAL ?? '展示真实拍摄场景的核心内容和代表性细节');
  await page.getByLabel('允许将本项目纳入的素材分析副本发送至千问模型服务').check();
  await page.getByRole('button', {name:'创建项目并生成分镜 →'}).click();
  await page.getByRole('button',{name:'确认并锁定清单 →'}).click();
  await page.getByLabel('我确认所选文件是普通视角视频').check();
  await page.getByLabel('导入本地视频').setInputFiles(configured);
  await expect(page.locator('.clip')).toHaveCount(configured.length);
  await expect(page.locator('.clip').filter({hasText:'分析完成'})).toHaveCount(configured.length, {timeout:300000});
  await expect(page.locator('.cliperror')).toHaveCount(0);
  await expect(page.locator('.evidence').first()).toBeVisible();
});
