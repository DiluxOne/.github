// The stylelint rule `diluxone/design-system`: a design system's pattern
// rules (design-systems/<name>/rules.yml), run on a stylesheet.
//
// It holds no rule of its own. Its options are what scripts/design-tokens.py
// writes into the system's dist/stylelint.json from rules.yml: each rule's
// id, severity, regular expression, message and the tokens to suggest for a
// raw value. The expression runs on the file's text with its comments
// blanked out, as design-tokens.py runs it on the fixtures, so the fixtures
// that hold there hold here (scripts/design-lint.py --test runs every one
// through this rule).
//
//   {"plugins": ["./scripts/stylelint/design-system.mjs"],
//    "rules": {"diluxone/design-system": [true, {"system": "…", "rules": [
//      {"id": "…", "severity": "error|warning|notice", "pattern": "…",
//       "message": "…", "suggest": {"#2271b1": ["--dx-color-accent", …]}}]}]}}

import stylelint from 'stylelint';

const {
	createPlugin,
	utils: { report, validateOptions },
} = stylelint;

export const ruleName = 'diluxone/design-system';

// A raw value as the generator wrote the keys of `suggest`: a hex in lower
// case and six or eight digits, a number without trailing zeros.
export function normalise(raw) {
	const value = raw.toLowerCase();
	const hex = /^#([0-9a-f]{3,4})$/.exec(value);
	if (hex) {
		return '#' + [...hex[1]].map((c) => c + c).join('');
	}
	const num = /^(-?(?:\d+(?:\.\d*)?|\.\d+))([a-z%]*)$/.exec(value);
	if (num) {
		return String(Number(num[1])) + num[2];
	}
	return value;
}

// What the found code says, followed by the tokens that hold those values.
function message(rule, found) {
	const hints = [];
	for (const raw of found.match(/#[0-9a-fA-F]{3,8}\b|-?(?:\d+(?:\.\d+)?|\.\d+)(?:px|rem|em|%)?/g) || []) {
		const names = (rule.suggest || {})[normalise(raw)];
		if (names && !hints.some((h) => h.startsWith('`' + raw + '`'))) {
			hints.push('`' + raw + '` is ' + names.map((n) => '`var(' + n + ')`').join(' or '));
		}
	}
	return rule.id + ': ' + (hints.length ? hints.join('; ') + '. ' : '') + rule.message;
}

// Comments become spaces (their line breaks kept), so an offset in the result
// is the same offset in the file.
export function blankComments(css) {
	return css.replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, ' '));
}

// Every match of every rule, as [rule, start, end, text]. A pattern starts at
// the delimiter before a declaration (`{` or `;`) and ends at the one after
// it, so the next search starts on that last delimiter: two declarations on
// one line are two findings.
export function findings(css, rules) {
	const code = blankComments(css);
	const out = [];
	for (const rule of rules) {
		const rx = new RegExp(rule.pattern, 'gm');
		let m;
		while ((m = rx.exec(code)) !== null) {
			const lead = /^[\s{};,]*/.exec(m[0])[0].length;
			const tail = /[\s{};,]*$/.exec(m[0].slice(lead))[0].length;
			const start = m.index + lead;
			const end = Math.max(start + 1, m.index + m[0].length - tail);
			out.push([rule, start, end, code.slice(start, end)]);
			rx.lastIndex = Math.max(m.index + 1, m.index + m[0].length - 1);
		}
	}
	return out.sort((a, b) => a[1] - b[1]);
}

const rule = (primary, secondary) => (root, result) => {
	const valid = validateOptions(
		result,
		ruleName,
		{ actual: primary, possible: [true] },
		{ actual: secondary, possible: (o) => Boolean(o) && Array.isArray(o.rules) },
	);
	if (!valid) {
		return;
	}
	const css = root.source && root.source.input ? root.source.input.css : root.toString();
	for (const [found, index, endIndex, text] of findings(css, secondary.rules)) {
		report({
			result,
			ruleName,
			node: root,
			index,
			endIndex,
			// stylelint knows two severities; a notice is a warning to it.
			severity: found.severity === 'error' ? 'error' : 'warning',
			message: message(found, text),
		});
	}
};

rule.ruleName = ruleName;
rule.meta = { url: 'https://github.com/DiluxOne/.github/tree/main/design-systems' };

export default createPlugin(ruleName, rule);
