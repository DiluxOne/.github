/**
 * The repository's Playwright configuration, narrowed to a reproduction
 * (DiluxOne/.github#352): its tests in tests/e2e/repro/, in chromium, with
 * no retries, and a JUnit report the verdict is read from. Copied to the
 * repository's root by issue-repro.yml (kinds/wordpress-plugin/pack.yml,
 * `repro.ways.browser.setup`) and plugin-tests-wp.yml, never committed: what
 * the repository's own configuration sets (its address, sign-in, setup
 * projects) stays as it is.
 */
import { defineConfig, devices } from '@playwright/test';
import base from './playwright.config';

const REPRO = './tests/e2e/repro';
// The repository's setup and teardown projects, where they were: a project
// without a testDir of its own keeps the repository's, not the one below.
const own = (base.projects ?? [])
	.filter((p) => p.name === 'setup' || p.name === 'teardown')
	.map((p) => ({ ...p, testDir: p.testDir ?? base.testDir ?? '.' }));
const chromium = (base.projects ?? []).find((p) => p.name === 'chromium');

export default defineConfig({
	...base,
	testDir: REPRO,
	retries: 0,
	// build/ is the one folder the reproduction's user can write.
	outputDir: 'build/dx-repro-results',
	reporter: [['junit', { outputFile: 'build/dx-repro-junit.xml' }], ['line']],
	projects: [
		...own,
		{
			...(chromium ?? {}),
			name: 'chromium',
			testDir: REPRO,
			testMatch: /issue-\d+\.spec\.ts$/,
			testIgnore: [],
			use: { ...devices['Desktop Chrome'], ...(chromium?.use ?? {}) },
		},
	],
});
