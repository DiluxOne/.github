# Components and patterns

Each one as Offload and Users+ draw it today, written with the tokens. The
examples use the prefix `diluxone-example`: a plugin writes its own
(`diluxone-offload`, `diluxone-users`), since a plugin's classes carry its
prefix. Every rule sits under the screen's wrapper class
(`.diluxone-example-admin`), so WordPress's classes change on the plugin's
screen and nowhere else.

## The screen

WordPress's `.wrap` with the plugin's wrapper class, its own `h1`, the tabs,
then the content: one column at the measure, or the content beside a rail
(status, links, help) that goes under it below 960px.

```html
<div class="wrap diluxone-example-admin">
  <h1>DiluxOne Example</h1>
  <nav class="nav-tab-wrapper">…</nav>
  <div class="diluxone-example-studio">
    <div class="diluxone-example-studio__main">…</div>
    <aside class="diluxone-example-studio__aside">…</aside>
  </div>
</div>
```

```css
.diluxone-example-studio {
	display: grid;
	grid-template-columns: minmax(0, var(--dx-layout-measure)) minmax(var(--dx-layout-rail), 1fr);
	gap: var(--dx-space-6);
	align-items: start;
}
.diluxone-example-studio__main { min-width: 0; }
.diluxone-example-studio__aside {
	position: sticky;
	top: calc(var(--dx-layout-toolbar) + var(--dx-space-3));
	display: grid;
	gap: var(--dx-space-4);
}
/* Every block of the main column leaves the same room under it. */
.diluxone-example-admin .diluxone-example-studio__main > * { margin: 0 0 var(--dx-space-block); }

@media screen and (max-width: 960px) {
	.diluxone-example-studio { grid-template-columns: minmax(0, 1fr); }
	.diluxone-example-studio__aside { position: static; }
}
```

## Tabs

WordPress's `.nav-tab-wrapper`, no icons. The open tab is marked by a band of
the accent along its top, not by being a shade lighter; on a phone the
strip stays one row and scrolls sideways.

```html
<nav class="nav-tab-wrapper" aria-label="Sections">
  <a href="?page=diluxone-example&amp;tab=overview" class="nav-tab nav-tab-active" aria-current="page">Overview</a>
  <a href="?page=diluxone-example&amp;tab=settings" class="nav-tab">Settings</a>
</nav>
```

```css
.diluxone-example-admin .nav-tab-wrapper {
	margin-bottom: var(--dx-space-5);
	border-bottom: var(--dx-border-width) solid var(--dx-color-border-strong);
}
.diluxone-example-admin .nav-tab {
	border-top: var(--dx-border-width-bar) solid transparent;
	font-size: var(--dx-font-size-help);
	transition: color var(--dx-motion-duration-fast) ease, border-color var(--dx-motion-duration-fast) ease;
}
.diluxone-example-admin .nav-tab-active,
.diluxone-example-admin .nav-tab-active:hover,
.diluxone-example-admin .nav-tab-active:focus {
	border-top-color: var(--dx-color-accent);
	color: var(--dx-color-text);
	font-weight: var(--dx-font-weight-semibold);
}

@media screen and (max-width: 782px) {
	.diluxone-example-admin .nav-tab-wrapper { display: flex; flex-wrap: nowrap; overflow-x: auto; }
	.diluxone-example-admin .nav-tab { flex: none; float: none; white-space: nowrap; }
}
```

## Cards

**A section of a tab** is WordPress's `.card`, at the measure, its title
ruled off.

```html
<section class="card">
  <h2>Storage</h2>
  <p>…</p>
</section>
```

```css
.diluxone-example-admin .card {
	max-width: var(--dx-layout-measure);
	margin: 0 0 var(--dx-space-block);
	padding: var(--dx-space-5);
	border: var(--dx-border-width) solid var(--dx-color-border);
	border-radius: var(--dx-radius-md);
	box-sizing: border-box;
}
.diluxone-example-admin .card > h2 {
	margin: 0 0 var(--dx-space-4);
	padding-bottom: var(--dx-space-3);
	border-bottom: var(--dx-border-width) solid var(--dx-color-border);
	font-size: var(--dx-font-size-heading);
}
```

**A row of figures** is a grid of cards, each with a band of the accent
along its top and an icon on a disc of the accent's wash: the row reads as
one object, in the dashboard's colour.

```html
<div class="diluxone-example-cards">
  <div class="diluxone-example-card">
    <span class="diluxone-example-card__icon dashicons dashicons-cloud" aria-hidden="true"></span>
    <div class="diluxone-example-card__body">
      <h3>Files offloaded</h3>
      <p class="diluxone-example-card__value">1,204</p>
    </div>
  </div>
</div>
```

```css
.diluxone-example-cards {
	display: grid;
	gap: var(--dx-space-4);
	grid-template-columns: repeat(auto-fit, minmax(var(--dx-layout-card-min), 1fr));
}
.diluxone-example-card {
	position: relative;
	display: flex;
	gap: var(--dx-space-3);
	align-items: flex-start;
	padding: var(--dx-space-5);
	border: var(--dx-border-width) solid var(--dx-color-border);
	border-radius: var(--dx-radius-md);
	background: var(--dx-color-surface);
	overflow: hidden;
	transition: box-shadow var(--dx-motion-duration-fast) ease, border-color var(--dx-motion-duration-fast) ease;
}
.diluxone-example-card::before {
	content: "";
	position: absolute;
	inset: 0 0 auto 0;
	height: var(--dx-border-width-bar);
	background: var(--dx-color-accent);
}
.diluxone-example-card:hover { border-color: var(--dx-color-accent-edge); box-shadow: var(--dx-shadow-raise); }
.diluxone-example-card__icon {
	display: flex;
	align-items: center;
	justify-content: center;
	width: var(--dx-space-6);
	height: var(--dx-space-6);
	border-radius: var(--dx-radius-round);
	background: var(--dx-color-accent-wash);
	color: var(--dx-color-accent);
}
.diluxone-example-card h3 {
	margin: 0;
	font-size: var(--dx-font-size-help);
	font-weight: var(--dx-font-weight-semibold);
	line-height: var(--dx-font-line-height-snug);
	text-transform: uppercase;
	color: var(--dx-color-text-muted);
}
```

**The state box** says where the screen stands right now, at the top of
the rail: a box with the accent band on top (it is the answer, not a
warning), an eyebrow, a pill and one sentence.

```html
<div class="diluxone-example-state">
  <div class="diluxone-example-state__head">
    <span class="diluxone-example-state__now">Right now</span>
    <span class="diluxone-example-pill diluxone-example-pill--on">Connected</span>
  </div>
  <p class="diluxone-example-state__line">New uploads go to the bucket.</p>
</div>
```

```css
.diluxone-example-state {
	padding: var(--dx-space-4);
	border: var(--dx-border-width) solid var(--dx-color-border);
	border-top: var(--dx-border-width-bar) solid var(--dx-color-accent);
	border-radius: var(--dx-radius-md);
	background: var(--dx-color-surface);
}
.diluxone-example-state__head { display: flex; flex-wrap: wrap; align-items: center; gap: var(--dx-space-2); margin-bottom: var(--dx-space-2); }
.diluxone-example-state__now {
	font-size: var(--dx-font-size-tiny);
	font-weight: var(--dx-font-weight-semibold);
	text-transform: uppercase;
	color: var(--dx-color-text-muted);
}
.diluxone-example-state__line { margin: 0; font-size: var(--dx-font-size-help); line-height: var(--dx-font-line-height-base); }
```

## Pills

The state vocabulary: one shape, three states, the same in every plugin.

```html
<span class="diluxone-example-pill diluxone-example-pill--on">Active</span>
<span class="diluxone-example-pill diluxone-example-pill--pending">Pending</span>
<span class="diluxone-example-pill diluxone-example-pill--off">Off</span>
```

```css
.diluxone-example-pill {
	display: inline-block;
	padding: var(--dx-space-pill-block) var(--dx-space-pill-inline);
	border-radius: var(--dx-radius-pill);
	font-size: var(--dx-font-size-small);
	font-weight: var(--dx-font-weight-semibold);
	line-height: var(--dx-font-line-height-pill);
	white-space: nowrap;
}
.diluxone-example-pill--on { background: var(--dx-color-pill-on-background); color: var(--dx-color-pill-on-text); }
.diluxone-example-pill--pending { background: var(--dx-color-pill-pending-background); color: var(--dx-color-pill-pending-text); }
.diluxone-example-pill--off { background: var(--dx-color-pill-off-background); color: var(--dx-color-pill-off-text); }
```

A Pro feature's badge is `--dx-color-pro` on `--dx-color-pro-wash`: a colour
of its own, never one of the three states.

## Notices

**What just happened** (saved, failed, connected) is WordPress's own notice,
at the top of the page, untouched: `notice notice-success|warning|error|info`,
`is-dismissible` when it can be dismissed. Inside a card or a modal it is
`notice inline`.

```html
<div class="notice notice-success is-dismissible"><p>Settings saved.</p></div>
```

**A caveat about a place** (a setting below that cannot take effect on this
site) sits next to what it is about, as an aside: a bar down the left and a
wash, no icon. Warning in WordPress's amber, everything else in the accent.

```html
<div class="diluxone-example-aside diluxone-example-aside--warning">
  <p>The site's <code>wp-config.php</code> sets this, so the choice below has no effect.</p>
</div>
```

```css
.diluxone-example-aside {
	max-width: var(--dx-layout-measure);
	padding: var(--dx-space-4);
	border: var(--dx-border-width) solid var(--dx-color-border);
	border-left-width: var(--dx-border-width-notice);
	border-radius: var(--dx-radius-sm);
}
.diluxone-example-aside p { margin: 0; line-height: var(--dx-font-line-height-base); }
.diluxone-example-aside p + p { margin-top: var(--dx-space-2); }
.diluxone-example-aside--warning { border-left-color: var(--dx-color-warning); background: var(--dx-color-warning-wash); }
.diluxone-example-aside--info { border-left-color: var(--dx-color-info); background: var(--dx-color-info-wash); }
```

**A field's error** is said next to the group that has to change, written by
the server (so it is in the person's language) and only shown by the script.

```css
.diluxone-example-field-error {
	margin: var(--dx-space-2) 0 0;
	padding: var(--dx-space-2) var(--dx-space-3);
	border-left: var(--dx-border-width-notice) solid var(--dx-color-error-strong);
	border-radius: var(--dx-radius-sm);
	background: var(--dx-color-error-wash);
	font-size: var(--dx-font-size-help);
	color: var(--dx-color-error-text);
}
```

## Tables

**A list of rows** (files, accounts, logs) is WordPress's `.wp-list-table`
(`widefat fixed striped`), through `WP_List_Table` when it pages or sorts.
It takes the width it is given and scrolls sideways when there is no room;
a column that holds a state holds a pill.

```html
<div class="diluxone-example-wide">
  <table class="wp-list-table widefat fixed striped">
    <thead><tr><th scope="col">File</th><th scope="col">State</th></tr></thead>
    <tbody><tr><td><code>2026/10/photo.jpg</code></td><td><span class="diluxone-example-pill diluxone-example-pill--on">Offloaded</span></td></tr></tbody>
  </table>
</div>
```

```css
.diluxone-example-wide { max-width: none; overflow-x: auto; }
```

**Facts about one thing** (a provider, a connection) are a key/value table:
the key muted, the value in full text, aligned right, a soft rule between
rows.

```html
<table class="diluxone-example-facts">
  <tr><td>Region</td><td><code>us-east-1</code></td></tr>
  <tr><td>Bucket</td><td><code>media</code></td></tr>
</table>
```

```css
.diluxone-example-facts { width: 100%; border-collapse: collapse; }
.diluxone-example-facts tr { border-bottom: var(--dx-border-width) solid var(--dx-color-border-soft); }
.diluxone-example-facts tr:last-child { border-bottom: 0; }
.diluxone-example-facts td { padding: var(--dx-space-2) 0; font-size: var(--dx-font-size-help); line-height: var(--dx-font-line-height-base); }
.diluxone-example-facts td:first-child { width: 45%; color: var(--dx-color-text-muted); }
.diluxone-example-facts td:last-child { text-align: right; color: var(--dx-color-text); overflow-wrap: anywhere; }
```

## Forms

No `.form-table`: the two-column table is what every screen fell back to
when it had no piece for what it wanted. An option is a block: its title,
the sentence that explains it, the control.

**A choice among a few** is a card per option, the whole card the label. The
chosen one is seen from across the room: the accent's edge and wash, not
only a filled circle.

```html
<div class="diluxone-example-choices" role="radiogroup" aria-labelledby="mode-title">
  <label class="diluxone-example-choice">
    <input type="radio" name="mode" value="copy" checked>
    <span class="diluxone-example-choice__text">
      <strong class="diluxone-example-choice__title">Copy</strong>
      <span class="diluxone-example-choice__help">Keep the files on the server too.</span>
    </span>
  </label>
  <label class="diluxone-example-choice">…</label>
</div>
```

```css
.diluxone-example-choices { display: flex; flex-direction: column; gap: var(--dx-space-3); max-width: var(--dx-layout-measure); }
.diluxone-example-choice {
	display: flex;
	align-items: flex-start;
	gap: var(--dx-space-3);
	padding: var(--dx-space-4);
	border: var(--dx-border-width) solid var(--dx-color-border);
	border-radius: var(--dx-radius-md);
	background: var(--dx-color-surface);
	cursor: pointer;
	transition: border-color var(--dx-motion-duration-fast) ease, background var(--dx-motion-duration-fast) ease;
}
.diluxone-example-choice:hover { border-color: var(--dx-color-accent-edge); }
.diluxone-example-choice:has(input:checked) { border-color: var(--dx-color-accent); background: var(--dx-color-accent-wash); }
.diluxone-example-choice:has(input:disabled) { opacity: .65; cursor: default; background: var(--dx-color-surface-alt); }
.diluxone-example-choice__title { display: block; font-size: var(--dx-font-size-body); font-weight: var(--dx-font-weight-semibold); color: var(--dx-color-text); }
.diluxone-example-choice__help { display: block; font-size: var(--dx-font-size-help); line-height: var(--dx-font-line-height-base); color: var(--dx-color-text-muted); }
```

**A field** is WordPress's input (`regular-text`, `large-text`), its label
above it and its help under it, at the measure. Focus is WordPress's ring in
the accent; the primary button is the accent too.

```css
.diluxone-example-admin input[type="text"]:focus,
.diluxone-example-admin input[type="email"]:focus,
.diluxone-example-admin input[type="number"]:focus,
.diluxone-example-admin select:focus,
.diluxone-example-admin textarea:focus {
	border-color: var(--dx-color-accent);
	box-shadow: var(--dx-shadow-focus);
}
.diluxone-example-admin .button-primary { background: var(--dx-color-accent); border-color: var(--dx-color-accent); }
```

**The main action of a state** (start the sync, connect) is one wide
`.button-hero` in a box set apart, with what it does under it.

```css
.diluxone-example-action {
	padding: var(--dx-space-4);
	border: var(--dx-border-width) solid var(--dx-color-border-strong);
	border-radius: var(--dx-radius-sm);
	background: var(--dx-color-surface-alt);
}
.diluxone-example-action .button-hero { display: flex; width: 100%; justify-content: center; align-items: center; gap: var(--dx-space-2); }
```

## Motion

Every hover and state change takes `--dx-motion-duration-fast`, and none
when the person asks for less:

```css
@media (prefers-reduced-motion: reduce) {
	.diluxone-example-admin * { transition: none; }
}
```
