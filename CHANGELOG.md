# Changelog

Every version of the engine (the workflows, scripts, policy and kinds other repositories call), newest first, built from git by `scripts/changelog.py`: what merged in it, by type. What a major, a minor and a patch mean for whoever calls these workflows is in [docs/versioning.md](docs/versioning.md).

## [6.8.4](https://github.com/DiluxOne/.github/releases/tag/v6.8.4) · 2026-10-25

### Fixes

- **repro:** a confirmed bug stops waiting for an acceptance ([#429](https://github.com/DiluxOne/.github/pull/429))

### Build and dependencies

- **deps:** Bump fast-uri from 3.1.8 to 3.1.9 in /scripts/stylelint ([#363](https://github.com/DiluxOne/.github/pull/363))

## [6.8.3](https://github.com/DiluxOne/.github/releases/tag/v6.8.3) · 2026-10-24

### Fixes

- **repro:** run-ref's cleanup never fails a verdict ([#422](https://github.com/DiluxOne/.github/pull/422))

### Maintenance

- **release:** v6.8.3, run-ref's cleanup never fails a verdict ([#426](https://github.com/DiluxOne/.github/pull/426))

## [6.8.2](https://github.com/DiluxOne/.github/releases/tag/v6.8.2) · 2026-10-24

### Fixes

- **autopilot:** an accepted decision's sub-issues start the autopilot ([#417](https://github.com/DiluxOne/.github/pull/417))

### Maintenance

- **release:** v6.8.2, a decision's sub-issues start the autopilot ([#419](https://github.com/DiluxOne/.github/pull/419))

## [6.8.1](https://github.com/DiluxOne/.github/releases/tag/v6.8.1) · 2026-10-24

### Fixes

- **repro:** run-ref brings .dx-central and frees the network ([#410](https://github.com/DiluxOne/.github/pull/410))

### Maintenance

- **release:** v6.8.1, the lane verifies a browser fix ([#414](https://github.com/DiluxOne/.github/pull/414))

## [6.8.0](https://github.com/DiluxOne/.github/releases/tag/v6.8.0) · 2026-10-24

### Features

- **repro:** every reproduced bug goes to the lane, whatever its way ([#399](https://github.com/DiluxOne/.github/pull/399))

### Maintenance

- **release:** v6.8.0, every reproduced bug to the lane ([#401](https://github.com/DiluxOne/.github/pull/401))

## [6.7.0](https://github.com/DiluxOne/.github/releases/tag/v6.7.0) · 2026-10-24

### Features

- **repro:** every repository declares how its bugs are reproduced ([#388](https://github.com/DiluxOne/.github/pull/388))

### Fixes

- **repro:** the reproduction reads the issue in a private repository ([#395](https://github.com/DiluxOne/.github/pull/395))

### Maintenance

- **release:** v6.7.0, bugs reproduced in every repository ([#398](https://github.com/DiluxOne/.github/pull/398))
- **repos:** the new plugin diluxone-events-wordpress joins ([#391](https://github.com/DiluxOne/.github/pull/391))

## [6.6.0](https://github.com/DiluxOne/.github/releases/tag/v6.6.0) · 2026-10-23

### Features

- **repro:** reproduce the engine's own bugs with a test ([#382](https://github.com/DiluxOne/.github/pull/382))

### Performance

- **runner-vm:** three slots per two cores, the disk on Premium P15 ([#381](https://github.com/DiluxOne/.github/pull/381))

### CI

- **tests-wp:** plugin tests run on Node 24, so wp-env 12 can start ([#389](https://github.com/DiluxOne/.github/pull/389))

### Maintenance

- **release:** v6.6.0, the engine's own bugs reproduced with a test ([#386](https://github.com/DiluxOne/.github/pull/386))

## [6.5.0](https://github.com/DiluxOne/.github/releases/tag/v6.5.0) · 2026-10-23

### Features

- **install:** one pull request sets an organisation up ([#346](https://github.com/DiluxOne/.github/pull/346))

### Fixes

- **issues:** an incomplete issue never shows as Accepted on its Project ([#378](https://github.com/DiluxOne/.github/pull/378))
- **weekly:** open the weekly failure issue with the Type Bug ([#380](https://github.com/DiluxOne/.github/pull/380))

### CI

- **deps:** Bump the github-actions group across 1 directory with 3 updates ([#325](https://github.com/DiluxOne/.github/pull/325))

### Maintenance

- **release:** v6.5.0, another organisation set up in one PR ([#373](https://github.com/DiluxOne/.github/pull/373))

## [6.4.3](https://github.com/DiluxOne/.github/releases/tag/v6.4.3) · 2026-10-23

### Fixes

- **repro:** a failed assertion's call log is no missing element ([#367](https://github.com/DiluxOne/.github/pull/367))

### Maintenance

- **release:** v6.4.3, a failed assertion is a reproduction ([#369](https://github.com/DiluxOne/.github/pull/369))

## [6.4.2](https://github.com/DiluxOne/.github/releases/tag/v6.4.2) · 2026-10-23

### Fixes

- **conventions:** no size cap on the organisation's own bot ([#364](https://github.com/DiluxOne/.github/pull/364))

### Maintenance

- **release:** v6.4.2, no size cap on the organisation's own bot ([#365](https://github.com/DiluxOne/.github/pull/365))

## [6.4.1](https://github.com/DiluxOne/.github/releases/tag/v6.4.1) · 2026-10-23

### Fixes

- **repro:** the site's address, and setup failures as the environment ([#358](https://github.com/DiluxOne/.github/pull/358))

### Maintenance

- **release:** v6.4.1, the browser reproduction finds its site ([#362](https://github.com/DiluxOne/.github/pull/362))

## [6.4.0](https://github.com/DiluxOne/.github/releases/tag/v6.4.0) · 2026-10-23

### Features

- **repro:** reproduce each bug the way its repository declares ([#356](https://github.com/DiluxOne/.github/pull/356))

### Maintenance

- **release:** v6.4.0, each bug reproduced the way its repo says ([#357](https://github.com/DiluxOne/.github/pull/357))

## [6.3.0](https://github.com/DiluxOne/.github/releases/tag/v6.3.0) · 2026-10-22

### Features

- **g1:** check the issue schema when an issue opens and on each edit ([#354](https://github.com/DiluxOne/.github/pull/354))
- **engine:** read the calling organisation's configuration ([#342](https://github.com/DiluxOne/.github/pull/342))
- **engine:** the calling organisation's App, not dilux-bot ([#344](https://github.com/DiluxOne/.github/pull/344))

### Build and dependencies

- **deps:** Bump ubuntu from `534baea` to `68ee220` in /runner ([#340](https://github.com/DiluxOne/.github/pull/340))

### Maintenance

- **release:** v6.3.0, the issue schema checked before acceptance ([#355](https://github.com/DiluxOne/.github/pull/355))

## [6.2.0](https://github.com/DiluxOne/.github/releases/tag/v6.2.0) · 2026-10-20

### Features

- close four small gaps of the agentic model ([#347](https://github.com/DiluxOne/.github/pull/347))

### Maintenance

- **release:** v6.2.0, four small gaps of the agentic model ([#348](https://github.com/DiluxOne/.github/pull/348))

## [6.1.0](https://github.com/DiluxOne/.github/releases/tag/v6.1.0) · 2026-10-20

### Features

- **security:** fix forward a weakness no release holds ([#343](https://github.com/DiluxOne/.github/pull/343))

### Documentation

- **review:** weekly review lessons 2026-10-19 ([#338](https://github.com/DiluxOne/.github/pull/338))

### Maintenance

- **release:** v6.1.0, unreleased weaknesses fixed forward ([#345](https://github.com/DiluxOne/.github/pull/345))

## [6.0.1](https://github.com/DiluxOne/.github/releases/tag/v6.0.1) · 2026-10-18

### Fixes

- **sync:** a caller's top-level permissions are held to its template's ([#331](https://github.com/DiluxOne/.github/pull/331))
- **sync:** a person's run writes signed git commits ([#328](https://github.com/DiluxOne/.github/pull/328))
- **sync:** a caller's triggers are held to its template's ([#326](https://github.com/DiluxOne/.github/pull/326))

### Maintenance

- **release:** v6.0.1, the sync fixes merged after v6.0.0 ([#336](https://github.com/DiluxOne/.github/pull/336))
- **policy:** planned releases go out on their own again ([#333](https://github.com/DiluxOne/.github/pull/333))

## [6.0.0](https://github.com/DiluxOne/.github/releases/tag/v6.0.0) · 2026-10-18

### Breaking changes

- v6, every repository's release ends at the GitHub release ([#323](https://github.com/DiluxOne/.github/pull/323))
- **release:** the release ends at the GitHub release; wordpress.org follows it ([#300](https://github.com/DiluxOne/.github/pull/300))

### Features

- **sync:** a callers-only major moves every repository on its own ([#321](https://github.com/DiluxOne/.github/pull/321))
- **security:** a maintainer's answer sends a failed fix back ([#314](https://github.com/DiluxOne/.github/pull/314))
- **ci:** the engine's scripts run at the commit its uses: names ([#299](https://github.com/DiluxOne/.github/pull/299))
- **autopilot:** others' opinions summarised for the maintainer ([#298](https://github.com/DiluxOne/.github/pull/298))
- **release:** a planned release ships only its plan ([#297](https://github.com/DiluxOne/.github/pull/297))
- **security:** carry a released patch into main on its own ([#296](https://github.com/DiluxOne/.github/pull/296))
- **security:** every report of a vulnerability takes the private path ([#295](https://github.com/DiluxOne/.github/pull/295))
- **release:** the engine's changelog, its versions and releases ([#293](https://github.com/DiluxOne/.github/pull/293))
- **autonomy:** a person merges an agent's change to sensitive code ([#294](https://github.com/DiluxOne/.github/pull/294))
- **security:** publish a patch only on a maintainer's patch:go ([#290](https://github.com/DiluxOne/.github/pull/290))
- **autonomy:** brakes and budgets on every agent and release ([#292](https://github.com/DiluxOne/.github/pull/292))
- **issues:** take back an acceptance when the issue is not ready ([#291](https://github.com/DiluxOne/.github/pull/291))
- **autopilot:** the agent works with no key, through an outbox ([#289](https://github.com/DiluxOne/.github/pull/289))

### Fixes

- **security:** a released patch publishes its advisory ([#318](https://github.com/DiluxOne/.github/pull/318))
- **security:** a plugin not on wordpress.org can be patched ([#316](https://github.com/DiluxOne/.github/pull/316))
- **triage:** a public security report is moved, or locked ([#312](https://github.com/DiluxOne/.github/pull/312))
- **surface:** an escape moved to another line is not taken out ([#309](https://github.com/DiluxOne/.github/pull/309))
- **receipts:** the jobs that seal and receipt read the whole engine ([#307](https://github.com/DiluxOne/.github/pull/307))
- **autopilot:** apply waits until the pull request shows the push ([#305](https://github.com/DiluxOne/.github/pull/305))

### CI

- **review:** reviewers read the diff from files, with no shell ([#288](https://github.com/DiluxOne/.github/pull/288))

### Maintenance

- **repos:** the sandbox plugin, where the workflows are proved ([#301](https://github.com/DiluxOne/.github/pull/301))

## [5.24.0](https://github.com/DiluxOne/.github/releases/tag/v5.24.0) · 2026-10-17

### Features

- **release:** merge a proved release pull request on its own ([#284](https://github.com/DiluxOne/.github/pull/284))

### Documentation

- **adopting:** a release environment admits security/* branches ([#286](https://github.com/DiluxOne/.github/pull/286))

## [5.23.0](https://github.com/DiluxOne/.github/releases/tag/v5.23.0) · 2026-10-17

### Features

- **release:** approve a planned release when its milestone is done ([#282](https://github.com/DiluxOne/.github/pull/282))

## [5.22.0](https://github.com/DiluxOne/.github/releases/tag/v5.22.0) · 2026-10-17

### Features

- **security:** publish a security patch after a veto window ([#280](https://github.com/DiluxOne/.github/pull/280))

## [5.21.0](https://github.com/DiluxOne/.github/releases/tag/v5.21.0) · 2026-10-17

### Features

- **release:** release a security patch pushed on security/X.Y.Z ([#278](https://github.com/DiluxOne/.github/pull/278))

## [5.20.0](https://github.com/DiluxOne/.github/releases/tag/v5.20.0) · 2026-10-17

### Features

- **security:** triage advisories and move them to draft on their own ([#274](https://github.com/DiluxOne/.github/pull/274))
- **release:** find the version in production a patch starts from ([#276](https://github.com/DiluxOne/.github/pull/276))

## [5.19.8](https://github.com/DiluxOne/.github/releases/tag/v5.19.8) · 2026-10-17

### Fixes

- **lanes:** close a reproduced bug's report when its fix merges ([#272](https://github.com/DiluxOne/.github/pull/272))

## [5.19.7](https://github.com/DiluxOne/.github/releases/tag/v5.19.7) · 2026-10-17

### Fixes

- **autopilot:** push once after marking ready, so the review runs ([#270](https://github.com/DiluxOne/.github/pull/270))

## [5.19.6](https://github.com/DiluxOne/.github/releases/tag/v5.19.6) · 2026-10-17

### Fixes

- **repro:** remove one label per call, so a missing one stops nothing ([#268](https://github.com/DiluxOne/.github/pull/268))

## [5.19.5](https://github.com/DiluxOne/.github/releases/tag/v5.19.5) · 2026-10-17

### Fixes

- **repro:** a writer that stops early is no verdict on the report ([#266](https://github.com/DiluxOne/.github/pull/266))

## [5.19.4](https://github.com/DiluxOne/.github/releases/tag/v5.19.4) · 2026-10-17

### Fixes

- **autonomy:** read a lane's issue again until its label shows ([#264](https://github.com/DiluxOne/.github/pull/264))

## [5.19.3](https://github.com/DiluxOne/.github/releases/tag/v5.19.3) · 2026-10-17

### Fixes

- **repro:** try a test written wrong once more, with its error ([#262](https://github.com/DiluxOne/.github/pull/262))

## [5.19.2](https://github.com/DiluxOne/.github/releases/tag/v5.19.2) · 2026-10-17

### Fixes

- **repro:** a test that breaks the rest of the unit suite proves nothing ([#260](https://github.com/DiluxOne/.github/pull/260))

## [5.19.1](https://github.com/DiluxOne/.github/releases/tag/v5.19.1) · 2026-10-17

### Fixes

- **repro:** start the autopilot after the optional diagnose job ([#258](https://github.com/DiluxOne/.github/pull/258))

## [5.19.0](https://github.com/DiluxOne/.github/releases/tag/v5.19.0) · 2026-10-17

### Features

- **repro:** a test setup that blocks a reproduction is fixed first ([#255](https://github.com/DiluxOne/.github/pull/255))

## [5.18.0](https://github.com/DiluxOne/.github/releases/tag/v5.18.0) · 2026-10-17

### Features

- **autopilot:** guided mode asks a maintainer; full mode decides ([#249](https://github.com/DiluxOne/.github/pull/249))

### Fixes

- **repro:** never mock a function the stubs already define ([#254](https://github.com/DiluxOne/.github/pull/254))
- **repro:** a repository with a paid add-on reproduces its bugs too ([#251](https://github.com/DiluxOne/.github/pull/251))

### Documentation

- **plan:** phase 12 reads product context by convention ([#252](https://github.com/DiluxOne/.github/pull/252))

## [5.17.0](https://github.com/DiluxOne/.github/releases/tag/v5.17.0) · 2026-10-17

### Features

- **review:** the nightly review's bugs go down the usual bug path ([#248](https://github.com/DiluxOne/.github/pull/248))

## [5.16.0](https://github.com/DiluxOne/.github/releases/tag/v5.16.0) · 2026-10-17

### Features

- **review:** an evaluation set every change to the review is held to ([#246](https://github.com/DiluxOne/.github/pull/246))

## [5.15.0](https://github.com/DiluxOne/.github/releases/tag/v5.15.0) · 2026-10-16

### Features

- **review:** a nightly review of existing code, one list per repository ([#245](https://github.com/DiluxOne/.github/pull/245))
- **review:** a second agent confirms each blocker before it is posted ([#243](https://github.com/DiluxOne/.github/pull/243))

## [5.14.0](https://github.com/DiluxOne/.github/releases/tag/v5.14.0) · 2026-10-16

### Features

- **security:** an advisory's fix is written in the private repository ([#244](https://github.com/DiluxOne/.github/pull/244))
- **digest:** what became of the review's findings, and its noise ([#239](https://github.com/DiluxOne/.github/pull/239))
- **review:** the count first, and pre-existing findings never block ([#238](https://github.com/DiluxOne/.github/pull/238))

## [5.13.0](https://github.com/DiluxOne/.github/releases/tag/v5.13.0) · 2026-10-16

### Features

- **security:** a maintainer starting the fork accepts an advisory ([#242](https://github.com/DiluxOne/.github/pull/242))

## [5.12.1](https://github.com/DiluxOne/.github/releases/tag/v5.12.1) · 2026-10-16

### Fixes

- **security:** the plan's token can read the advisories ([#241](https://github.com/DiluxOne/.github/pull/241))

### Documentation

- **plan:** phase 13, review quality, and the merge queue in phase 12 ([#236](https://github.com/DiluxOne/.github/pull/236))

## [5.12.0](https://github.com/DiluxOne/.github/releases/tag/v5.12.0) · 2026-10-16

### Features

- **security:** an accepted advisory gets its fix in its private fork ([#233](https://github.com/DiluxOne/.github/pull/233))
- **security:** a security issue is always merged by a person ([#232](https://github.com/DiluxOne/.github/pull/232))

### Fixes

- **g7:** auto-merge only the head commit that was decided ([#235](https://github.com/DiluxOne/.github/pull/235))

### Documentation

- **plan:** phase 12 is our engine with each organisation's config ([#231](https://github.com/DiluxOne/.github/pull/231))

## [5.11.0](https://github.com/DiluxOne/.github/releases/tag/v5.11.0) · 2026-10-16

### Features

- **g1:** the Spec step judges the PRD first and can stop ([#228](https://github.com/DiluxOne/.github/pull/228))
- **autopilot:** a decision log on the pull request ([#225](https://github.com/DiluxOne/.github/pull/225))
- **learnings:** three repeats make a rule; a rejected one never returns ([#227](https://github.com/DiluxOne/.github/pull/227))
- **spike:** a spike label starts a read-only investigation ([#224](https://github.com/DiluxOne/.github/pull/224))
- **g3:** a Feature's Spec carries its impact, threats and architecture ([#226](https://github.com/DiluxOne/.github/pull/226))
- **g6:** the review checks each criterion; G7 needs them all met ([#223](https://github.com/DiluxOne/.github/pull/223))
- **g7:** new public surface merges on its own only for a Feature ([#222](https://github.com/DiluxOne/.github/pull/222))
- **g1:** a PRD with an open doubt is not ready ([#221](https://github.com/DiluxOne/.github/pull/221))
- **release:** a closed version milestone opens its release issue ([#220](https://github.com/DiluxOne/.github/pull/220))
- **detect:** new repositories proposed for repos.yml every day ([#218](https://github.com/DiluxOne/.github/pull/218))
- **repos:** repos.yml says what each repository is, held to a schema ([#217](https://github.com/DiluxOne/.github/pull/217))

### Refactoring

- **org:** org.yml names the organisation; the scripts read it ([#219](https://github.com/DiluxOne/.github/pull/219))

## [5.10.0](https://github.com/DiluxOne/.github/releases/tag/v5.10.0) · 2026-10-16

### Features

- **runners:** DX_RUNNER_HEAVY names where the shared jobs run ([#215](https://github.com/DiluxOne/.github/pull/215))
- **bots:** every bot commit through the API, signed by GitHub ([#214](https://github.com/DiluxOne/.github/pull/214))

### CI

- **runner-image:** the image builds every day ([#213](https://github.com/DiluxOne/.github/pull/213))

## [5.9.0](https://github.com/DiluxOne/.github/releases/tag/v5.9.0) · 2026-10-16

### Features

- **decisions:** accepting a decision opens its sub-issues ([#212](https://github.com/DiluxOne/.github/pull/212))
- **sync:** every day, labels and shared files in step on their own ([#210](https://github.com/DiluxOne/.github/pull/210))
- **board:** each automatic decision links its rule ([#209](https://github.com/DiluxOne/.github/pull/209))
- **autonomy:** the delegated lane, a sub-issue of an accepted issue ([#207](https://github.com/DiluxOne/.github/pull/207))
- **runs:** one issue per run of the image build and the digest ([#205](https://github.com/DiluxOne/.github/pull/205))
- **sync:** Dependabot apart, so the AGENTS.md block takes the lane ([#203](https://github.com/DiluxOne/.github/pull/203))
- **autonomy:** a lane's ceiling, and the policy held to its schema ([#204](https://github.com/DiluxOne/.github/pull/204))
- **model:** the model in docs/model.md, rules/ and the AGENTS.md block ([#202](https://github.com/DiluxOne/.github/pull/202))

### Fixes

- **autonomy:** human-issue merges on its own only up to medium risk ([#201](https://github.com/DiluxOne/.github/pull/201))

### Documentation

- **plans:** the agentic model and its work plan ([#198](https://github.com/DiluxOne/.github/pull/198))

### CI

- **runner-vm:** a clock in Azure that runs runner-vm.yml on time ([#199](https://github.com/DiluxOne/.github/pull/199))

## [5.8.0](https://github.com/DiluxOne/.github/releases/tag/v5.8.0) · 2026-10-15

### Features

- **plugin-checks:** hold changed CSS to the design system's rules ([#169](https://github.com/DiluxOne/.github/pull/169))
- **autonomy:** an org-sync lane for the sync's issues and pull requests ([#171](https://github.com/DiluxOne/.github/pull/171))
- **autonomy:** revert a merge that turns the default branch red ([#165](https://github.com/DiluxOne/.github/pull/165))
- **sync:** every repository's Dependabot config from its template ([#180](https://github.com/DiluxOne/.github/pull/180))
- **autonomy:** reproduced bugs go to the autopilot on their own ([#166](https://github.com/DiluxOne/.github/pull/166))
- **plugin-checks:** tools on the latest PHP, code held to PHP 7.4 ([#156](https://github.com/DiluxOne/.github/pull/156))
- **runner-vm:** a pull request starts the VM, not only the schedule ([#162](https://github.com/DiluxOne/.github/pull/162))
- **review:** the review reads the repository's design system ([#168](https://github.com/DiluxOne/.github/pull/168))
- **conventions:** no new public surface behind a non-feat outside PR ([#164](https://github.com/DiluxOne/.github/pull/164))
- **sync:** compare workflow callers with their templates ([#160](https://github.com/DiluxOne/.github/pull/160))
- **design-systems:** wordpress-admin from Offload and Users+ ([#151](https://github.com/DiluxOne/.github/pull/151))
- **digest:** the weekly digest says what still needed a person ([#161](https://github.com/DiluxOne/.github/pull/161))
- **release:** a release is an issue a person accepts ([#159](https://github.com/DiluxOne/.github/pull/159))
- **plugin-tests:** mount the plugins a plugin requires in wp-env ([#158](https://github.com/DiluxOne/.github/pull/158))
- **issues:** assign accepted issues to whoever works them ([#149](https://github.com/DiluxOne/.github/pull/149))

### Fixes

- **runner:** keep reproduction pull requests off the VM ([#175](https://github.com/DiluxOne/.github/pull/175))
- **workflows:** give every setup-php job 15 minutes ([#176](https://github.com/DiluxOne/.github/pull/176))
- **plugin-checks:** stage the plugin outside its checkout ([#174](https://github.com/DiluxOne/.github/pull/174))
- **runner:** the image carries the libraries setup-php's PHP links to ([#163](https://github.com/DiluxOne/.github/pull/163))

### CI

- **deps:** Bump actions/create-github-app-token from 3.2.0 to 3.3.0 ([#181](https://github.com/DiluxOne/.github/pull/181))
- **templates:** comments that stay true once a repository copies them ([#177](https://github.com/DiluxOne/.github/pull/177))
- **deps:** Bump actions/create-github-app-token from 3.2.0 to 3.3.0 in the github-actions group ([#157](https://github.com/DiluxOne/.github/pull/157))
- **dependabot:** leave Ubuntu release bumps of the runner image to us ([#147](https://github.com/DiluxOne/.github/pull/147))
- **deps:** Bump the github-actions group across 1 directory with 5 updates ([#99](https://github.com/DiluxOne/.github/pull/99))

## [5.7.9](https://github.com/DiluxOne/.github/releases/tag/v5.7.9) · 2026-10-14

### Fixes

- **plugin-tests:** the E2E job sets PHP and Composer up when needed ([#141](https://github.com/DiluxOne/.github/pull/141))

## [5.7.8](https://github.com/DiluxOne/.github/releases/tag/v5.7.8) · 2026-10-13

### CI

- **runner-vm:** one runner slot per core, not a fixed four ([#139](https://github.com/DiluxOne/.github/pull/139))

## [5.7.7](https://github.com/DiluxOne/.github/releases/tag/v5.7.7) · 2026-10-13

### CI

- **templates:** every call at v5, the release too; no pinned commits ([#137](https://github.com/DiluxOne/.github/pull/137))

## [5.7.6](https://github.com/DiluxOne/.github/releases/tag/v5.7.6) · 2026-10-13

### Fixes

- **release:** nothing deploys to wordpress.org without an approval ([#135](https://github.com/DiluxOne/.github/pull/135))

## [5.7.5](https://github.com/DiluxOne/.github/releases/tag/v5.7.5) · 2026-10-13

### Fixes

- **conventions:** a taken-over autopilot pull request has no size cap ([#133](https://github.com/DiluxOne/.github/pull/133))

## [5.7.4](https://github.com/DiluxOne/.github/releases/tag/v5.7.4) · 2026-10-13

### Fixes

- **autopilot:** a run killed by its timeout still ends with a verdict ([#131](https://github.com/DiluxOne/.github/pull/131))

## [5.7.3](https://github.com/DiluxOne/.github/releases/tag/v5.7.3) · 2026-10-13

### Fixes

- **autopilot:** the draft reads every criterion the schema accepts ([#129](https://github.com/DiluxOne/.github/pull/129))

## [5.7.2](https://github.com/DiluxOne/.github/releases/tag/v5.7.2) · 2026-10-13

### Fixes

- **plugin-tests:** the integration job's timeout comes from the plan ([#128](https://github.com/DiluxOne/.github/pull/128))

## [5.7.1](https://github.com/DiluxOne/.github/releases/tag/v5.7.1) · 2026-10-12

### Fixes

- **plugin-checks:** Review rules sets PHP up before it runs the engine ([#124](https://github.com/DiluxOne/.github/pull/124))

## [5.7.0](https://github.com/DiluxOne/.github/releases/tag/v5.7.0) · 2026-10-12

### Features

- **issues:** reproduce a classified bug report on its own (#119) ([#120](https://github.com/DiluxOne/.github/pull/120))

### Fixes

- **runner-vm:** a slot removes the job's wp-env volumes and networks ([#122](https://github.com/DiluxOne/.github/pull/122))
- **issues:** accepting an issue here re-runs its pull request's gate ([#117](https://github.com/DiluxOne/.github/pull/117))

### Documentation

- **readme:** a release ends in production, published ([#115](https://github.com/DiluxOne/.github/pull/115))

## [5.6.1](https://github.com/DiluxOne/.github/releases/tag/v5.6.1) · 2026-10-11

### Fixes

- **autopilot:** commands in the foreground; finish a ticked draft ([#113](https://github.com/DiluxOne/.github/pull/113))

## [5.6.0](https://github.com/DiluxOne/.github/releases/tag/v5.6.0) · 2026-10-11

### Features

- **autopilot:** work in the open, in a draft pull request ([#111](https://github.com/DiluxOne/.github/pull/111))

### Fixes

- **issues:** the Spec appended after the AI line keeps the PRD's hash ([#110](https://github.com/DiluxOne/.github/pull/110))
- **review:** a person's type label also wins over the title ([#107](https://github.com/DiluxOne/.github/pull/107))

### CI

- **issues:** no daily cap on triage; accepting clears needs-triage ([#108](https://github.com/DiluxOne/.github/pull/108))
- **scripts:** the review's type decision, as a script with its test ([#104](https://github.com/DiluxOne/.github/pull/104))
- **issues:** this repository's issues reach its Project and the autopilot ([#102](https://github.com/DiluxOne/.github/pull/102))

## [5.5.0](https://github.com/DiluxOne/.github/releases/tag/v5.5.0) · 2026-10-10

### Features

- **autopilot:** an accepted issue worked to a merged pull request ([#101](https://github.com/DiluxOne/.github/pull/101))
- **receipts:** seal the PRD on acceptance, receipt on merge ([#100](https://github.com/DiluxOne/.github/pull/100))
- **issues:** one schema for PRD and Spec, checked at acceptance ([#98](https://github.com/DiluxOne/.github/pull/98))
- **autonomy:** lanes the gate trusts, narrower per repository ([#97](https://github.com/DiluxOne/.github/pull/97))
- **runner:** one-job containers on the VM, rebuilt weekly ([#88](https://github.com/DiluxOne/.github/pull/88))

### Documentation

- describe the runners, the VM and joining the organisation ([#96](https://github.com/DiluxOne/.github/pull/96))

### Maintenance

- **repos:** send diluxone-website's issues to its Project ([#90](https://github.com/DiluxOne/.github/pull/90))

## [5.4.2](https://github.com/DiluxOne/.github/releases/tag/v5.4.2) · 2026-10-10

### Documentation

- **agents:** say what waits on whom, with its link ([#74](https://github.com/DiluxOne/.github/pull/74))

### CI

- **claude:** run on the maintainer's subscription, API key as fallback ([#76](https://github.com/DiluxOne/.github/pull/76))

## [5.4.1](https://github.com/DiluxOne/.github/releases/tag/v5.4.1) · 2026-10-10

### Fixes

- **plugin-tests:** no apt on the VM, URLs from the runner's ports ([#72](https://github.com/DiluxOne/.github/pull/72))

### Maintenance

- **labels:** add Dependabot's npm and composer labels ([#68](https://github.com/DiluxOne/.github/pull/68))

## [5.4.0](https://github.com/DiluxOne/.github/releases/tag/v5.4.0) · 2026-10-10

### Features

- **runners:** private repositories run on the organisation's VM ([#66](https://github.com/DiluxOne/.github/pull/66))

### Maintenance

- keep the organisation's shared files in step ([#64](https://github.com/DiluxOne/.github/pull/64))

## [5.3.3](https://github.com/DiluxOne/.github/releases/tag/v5.3.3) · 2026-10-10

### Features

- **sync:** create the "own checks" ruleset and report it missing ([#62](https://github.com/DiluxOne/.github/pull/62))

### Documentation

- **review:** weekly review lessons 2026-10-05 ([#24](https://github.com/DiluxOne/.github/pull/24))
- **plans:** Mail is in the organisation, with its row ([#48](https://github.com/DiluxOne/.github/pull/48))

### CI

- **deps:** Bump the github-actions group across 1 directory with 4 updates ([#60](https://github.com/DiluxOne/.github/pull/60))

## [5.3.2](https://github.com/DiluxOne/.github/releases/tag/v5.3.2) · 2026-10-10

### Fixes

- **conventions:** let grouped Dependabot titles through ([#61](https://github.com/DiluxOne/.github/pull/61))

## [5.3.1](https://github.com/DiluxOne/.github/releases/tag/v5.3.1) · 2026-10-10

### Features

- **policy:** this repository's pages can merge on their own ([#53](https://github.com/DiluxOne/.github/pull/53))

### Fixes

- **plugin-checks:** keep the required plugins for a later re-run ([#58](https://github.com/DiluxOne/.github/pull/58))

### Documentation

- name every doc that stays high risk ([#55](https://github.com/DiluxOne/.github/pull/55))
- a short graphical README, the details under docs/ ([#51](https://github.com/DiluxOne/.github/pull/51))

## [5.3.0](https://github.com/DiluxOne/.github/releases/tag/v5.3.0) · 2026-10-08

### Features

- **plugin-checks:** mount required plugins wordpress.org lacks ([#49](https://github.com/DiluxOne/.github/pull/49))

## [5.2.2](https://github.com/DiluxOne/.github/releases/tag/v5.2.2) · 2026-10-08

### Features

- **drift:** report repositories on an old version, and Mail's Project ([#44](https://github.com/DiluxOne/.github/pull/44))

## [5.2.1](https://github.com/DiluxOne/.github/releases/tag/v5.2.1) · 2026-10-08

### Fixes

- **plugin-checks:** skip CodeQL in private repositories ([#42](https://github.com/DiluxOne/.github/pull/42))
- **issues:** issue-accepted asks only for what its callers grant ([#40](https://github.com/DiluxOne/.github/pull/40))

## [5.2.0](https://github.com/DiluxOne/.github/releases/tag/v5.2.0) · 2026-10-08

### Features

- **projects:** accepted issues land on their product's Project ([#38](https://github.com/DiluxOne/.github/pull/38))

## [5.1.0](https://github.com/DiluxOne/.github/releases/tag/v5.1.0) · 2026-10-08

### Features

- **org:** a weekly drift check, and the gate re-run when an issue is accepted ([#35](https://github.com/DiluxOne/.github/pull/35))

## [5.0.0](https://github.com/DiluxOne/.github/releases/tag/v5.0.0) · 2026-10-07

### Breaking changes

- **org:** one required pull request pipeline for every repository, as v5 ([#33](https://github.com/DiluxOne/.github/pull/33))
- **issue-gate:** native issue Type, an agent's flow, and what repos share kept in step ([#31](https://github.com/DiluxOne/.github/pull/31))

### Documentation

- **plans:** configure the organisation once, not every repository ([#29](https://github.com/DiluxOne/.github/pull/29))

## [4.0.0](https://github.com/DiluxOne/.github/releases/tag/v4.0.0) · 2026-10-07

### Breaking changes

- **conventions:** accepted issues first, a private paid roadmap, safer reproductions ([#26](https://github.com/DiluxOne/.github/pull/26))

## [3.0.2](https://github.com/DiluxOne/.github/releases/tag/v3.0.2) · 2026-10-08

### Fixes

- **plugin-checks:** skip CodeQL in private repositories ([#42](https://github.com/DiluxOne/.github/pull/42))

## [3.0.1](https://github.com/DiluxOne/.github/releases/tag/v3.0.1) · 2026-10-02

### Fixes

- **plugin-checks:** install WP-CLI from its release by name, checked against its SHA-512 ([#23](https://github.com/DiluxOne/.github/pull/23))

## [3.0.0](https://github.com/DiluxOne/.github/releases/tag/v3.0.0) · 2026-10-02

### Breaking changes

- **kinds:** project kinds as packs, a generic review-rules engine and strict Plugin Check, as v3 ([#22](https://github.com/DiluxOne/.github/pull/22))

## [2.7.3](https://github.com/DiluxOne/.github/releases/tag/v2.7.3) · 2026-10-02

### Fixes

- **plugin-checks:** install WP-CLI from its release by name, checked against its SHA-512 ([#23](https://github.com/DiluxOne/.github/pull/23))

## [2.7.2](https://github.com/DiluxOne/.github/releases/tag/v2.7.2) · 2026-10-01

### Maintenance

- **policy:** review every risk level with Sonnet 5.5, at low, medium and high effort ([#21](https://github.com/DiluxOne/.github/pull/21))

## [2.7.1](https://github.com/DiluxOne/.github/releases/tag/v2.7.1) · 2026-10-01

### Fixes

- **local-review:** a profile it cannot read says so, and the self-test catches a broken setup ([#20](https://github.com/DiluxOne/.github/pull/20))

## [2.7.0](https://github.com/DiluxOne/.github/releases/tag/v2.7.0) · 2026-09-30

### Features

- **policy:** Sonnet 5.5 reviews low and medium risk, Opus 5.5 keeps high ([#19](https://github.com/DiluxOne/.github/pull/19))

### Documentation

- **review:** weekly review lessons 2026-09-28 ([#14](https://github.com/DiluxOne/.github/pull/14))

## [2.6.1](https://github.com/DiluxOne/.github/releases/tag/v2.6.1) · 2026-09-30

### Fixes

- **review:** bot pull requests are reviewed, edits cancel no review, conventions read live labels ([#18](https://github.com/DiluxOne/.github/pull/18))

## [2.6.0](https://github.com/DiluxOne/.github/releases/tag/v2.6.0) · 2026-09-29

### Features

- **review:** the local review leaves its findings for an agent and reviews again what changed ([#17](https://github.com/DiluxOne/.github/pull/17))

## [2.5.0](https://github.com/DiluxOne/.github/releases/tag/v2.5.0) · 2026-09-28

### Features

- **review:** check a branch locally, before its pull request, as CI will check it ([#15](https://github.com/DiluxOne/.github/pull/15))

### Fixes

- **review:** the workflows run the shared scripts, and the scripts carry their tests ([#16](https://github.com/DiluxOne/.github/pull/16))

## [2.4.0](https://github.com/DiluxOne/.github/releases/tag/v2.4.0) · 2026-09-27

### Features

- **release:** one versioning policy for every repository, and main names the version it released ([#12](https://github.com/DiluxOne/.github/pull/12))

## [2.3.0](https://github.com/DiluxOne/.github/releases/tag/v2.3.0) · 2026-09-26

### Features

- **issues:** a report on an older version is reproduced on the current code, not told to update ([#11](https://github.com/DiluxOne/.github/pull/11))

## [2.2.0](https://github.com/DiluxOne/.github/releases/tag/v2.2.0) · 2026-09-26

### Features

- **release:** the dev build is one pre-release on a moving tag; triage knows current versions ([#10](https://github.com/DiluxOne/.github/pull/10))

## [2.1.0](https://github.com/DiluxOne/.github/releases/tag/v2.1.0) · 2026-09-26

### Features

- **release:** the readme holds the release until ready, and every push to main builds a dev zip ([#9](https://github.com/DiluxOne/.github/pull/9))

## [2.0.2](https://github.com/DiluxOne/.github/releases/tag/v2.0.2) · 2026-09-26

### Fixes

- **conventions:** every caller's retired-names line is exempt, not one file ([#8](https://github.com/DiluxOne/.github/pull/8))

## [2.0.1](https://github.com/DiluxOne/.github/releases/tag/v2.0.1) · 2026-09-26

### Breaking changes

- **tests:** a push to main runs the suites only on a tree they did not test ([#5](https://github.com/DiluxOne/.github/pull/5))

## [2.0.0](https://github.com/DiluxOne/.github/releases/tag/v2.0.0) · 2026-09-26

### Breaking changes

- **release:** the release is a deployment computed from the labels and approved in the environment ([#7](https://github.com/DiluxOne/.github/pull/7))
- **review:** the review decides the type of a change and whether the description matches ([#4](https://github.com/DiluxOne/.github/pull/4))

### Features

- **release:** the next version is arithmetic over the type labels of what merged ([#6](https://github.com/DiluxOne/.github/pull/6))

## [1.2.0](https://github.com/DiluxOne/.github/releases/tag/v1.2.0) · 2026-09-26

### Fixes

- **security:** least-privilege bot tokens, a write check for commands, the release in an environment ([#3](https://github.com/DiluxOne/.github/pull/3))

## [1.1.0](https://github.com/DiluxOne/.github/releases/tag/v1.1.0) · 2026-09-25

### Features

- **tests:** the slow suites and Plugin Check run only when a pull request changes code ([#2](https://github.com/DiluxOne/.github/pull/2))

## [1.0.1](https://github.com/DiluxOne/.github/releases/tag/v1.0.1) · 2026-09-25

### Fixes

- **review:** read the changed files from the files API, which has no diff-size limit ([#1](https://github.com/DiluxOne/.github/pull/1))

## [1.0.0](https://github.com/DiluxOne/.github/releases/tag/v1.0.0) · 2026-09-25

### Features

- DiluxOne shared engineering setup
