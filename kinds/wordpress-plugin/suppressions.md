# Suppressions in a WordPress plugin

Plugin Check honours a `phpcs:ignore`; the Plugin Review Team, and the scan
it runs, read the line without it. So the `suppression-unlisted` rule of
this pack ([`rules.yml`](rules.yml)) holds every suppression of these checks
to an entry, with its reason, in the plugin's
`.github/review-suppressions.yml`:

| Check suppressed | Listed with a reason |
| --- | --- |
| `WordPress.Security.NonceVerification.*` | yes |
| `WordPress.Security.ValidatedSanitizedInput.*` | yes |
| `WordPress.DB.PreparedSQL.*`, `WordPress.DB.PreparedSQLPlaceholders.*` | yes |
| `WordPress.WP.AlternativeFunctions.*` | yes |
| `WordPress.Security.EscapeOutput.*` | never: escape at the line (`escape-suppressed`) |
| any check, by a bare `phpcs:ignore` | never: name the check |

The file's format, the fingerprint and how a stale entry fails are in
[`../README.md`](../README.md#the-suppressions-file). Generate what is
missing with `--suggest-suppressions` and write each reason yourself.

## A reason the reviewer accepts

It says why the line is safe **in that line's terms**, without pointing
somewhere else:

- `NonceVerification.Recommended`: what the read decides and that nothing is
  saved or printed from it ("which tab to draw; the value is compared with
  the list of tabs").
- `PreparedSQL.InterpolatedNotPrepared`: what is interpolated and why it is
  not input ("the table name, `$wpdb->prefix` and a constant").
- `AlternativeFunctions.*`: why WordPress's function does not fit ("a stream
  to the storage provider; WP_Filesystem cannot write to it").

"The caller verifies it", "checked below" or "the panel verifies it" is not
a reason: the `nonce-elsewhere` rule flags it, and the fix is the check in
the function that reads.
