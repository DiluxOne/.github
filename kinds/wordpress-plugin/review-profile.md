# Review profile: WordPress plugin (kind `wordpress-plugin`, alias `plugin-wp`)

For plugins published on wordpress.org. Every rule comes from the Plugin
Review Team's guidelines or from a real rejection; the automated tools
passed each time, so check them by reading the code. What a script can
check is also a rule in `rules.yml` beside this file, run on every pull
request (`Review rules (wordpress-plugin)`); this profile is for what only
reading can find.

## Input, output, permissions

- **Every `$_POST` / `$_GET` / `$_REQUEST` / `$_COOKIE` / `$_SERVER` value is
  unslashed, sanitised and validated before use:**
  `sanitize_text_field( wp_unslash( $_POST['x'] ?? '' ) )`. Sanitising
  later, inside a DTO, does not count, and never pass a whole superglobal
  to a helper: read only the named fields.
- **Output is escaped late,** with the escaper for its context
  (`esc_html`, `esc_attr`, `esc_url`, `wp_kses`); translated strings too
  (`esc_html__`).
- **No `phpcs:ignore` of `EscapeOutput`, whatever the reason given.** The
  review reads "escaped inside" or "our own markup" as unescaped output.
  Markup built as a string is printed through `wp_kses()` with an allow-list
  at the line that echoes it; a template prints itself rather than being
  returned and echoed; a function that prints by itself
  (`wp_dropdown_pages()`, `get_avatar()` echoed) is no exception. An
  allow-list needs a test proving it strips nothing the plugin prints.
- **Every AJAX / REST / admin-post handler checks a nonce and a
  capability** (`check_ajax_referer` + `current_user_can`), **in the
  handler, before the first read** of the request. "The caller verifies
  it" or "checked below" next to a `NonceVerification` suppression is a
  finding: the reviewer reads the line on its own. The nonce action is
  static; one built from an input read before the check reads unverified
  input. The check is written with WordPress's own functions in that
  function: a helper registered in `phpcs.xml` as a custom nonce verifier or
  escaper satisfies the repository's PHPCS but not Plugin Check, which is
  what wordpress.org runs and which ignores the repository's config.
- **SQL goes through `$wpdb->prepare()`,** including `LIKE` with
  `$wpdb->esc_like()`.

## Files, memory, network

- **Never write outside the plugin's own place or what WordPress manages**
  (no writing into `uploads/` by hand): let core write, or fail with an error.
- **Never load a whole file into memory** (`file_get_contents` of an
  upload, a download into a string). Stream to disk (`wp_remote_get` with
  `stream` + `filename`), upload in blocks, use temp files (`wp_tempnam`).
- **No hard-coded `WP_CONTENT_DIR . '/uploads'`:** use `wp_upload_dir()`;
  sites move it with `UPLOADS`, `upload_path` and multisite.
- **HTTP through the WordPress HTTP API** (`wp_remote_*`) with an explicit
  timeout; no raw cURL unless documented and justified.
- **Every external service is disclosed** in `readme.txt` under
  `== External services ==`: what it is, what data is sent, when, and
  links to its terms and privacy policy. When the change touches that code
  or that section, dead code naming a host the plugin no longer calls goes
  too; reviewers grep for hostnames.

## Database and lifecycle

- **Check the result of anything that can fail** before recording success
  (`dbDelta()` returns the same on success and failure: verify the table).
- **Primary keys never use prefix indexes** on long columns (`file(191)`
  lets two paths collide). Use `VARCHAR(191)` like `wp_options`.
- **Multisite:** activation per site and for sites added later; uninstall
  cleans every site (`get_sites( [ 'number' => 0 ] )`).
- **Uninstall removes what the plugin created,** nothing else.

## The admin is a workspace (guideline 11)

- **No top-level menu among WordPress's own:** `add_menu_page()` without a
  position, or a submenu under Settings / Tools. A position like 22 or 71 is
  flagged as "a visibility tactic".
- **Notices speak on the plugin's own screens, the dashboard or the plugins
  list,** and are dismissible unless they are urgent. One on every screen of
  the admin reads as nagging, even when it is true.

## Code and packaging

- **Everything is prefixed** (functions, classes, options, hooks, AJAX
  actions, globals) with the plugin's unique prefix.
- **No `load_plugin_textdomain()`** for directory-hosted plugins; one text
  domain equal to the slug; `/* translators: */` comments on the line right
  before a translation call with placeholders.
- **No inline `<script>` / `<style>`:** enqueue with `wp_enqueue_*` and pass
  data with `wp_localize_script` / `wp_add_inline_script`.
- **Minimum PHP and WordPress versions** in the header are real: no syntax
  or functions newer than the stated PHP; `function_exists()` guards for
  newer WordPress APIs.
- **`Tested up to` lives only in `readme.txt`.** Version header, version
  constant and `Stable tag` stay aligned (the checks enforce it).
- **No trialware:** a plugin hosted on wordpress.org cannot lock features
  behind a payment or a licence (guideline 5). Paid value lives in a
  separate add-on or a real external service.
- **No logging by default:** nothing reaches the PHP error log unless the
  site turns it on; never log credentials or full request bodies.
- **Dead features are removed, not hidden:** a setting nobody reads, a
  form field without a handler or an unused AJAX action reads as a bug to
  a reviewer.

## Rating hints

- Changes to capability checks, nonces, sanitisation, escaping, file
  writes, SQL, activation/uninstall or anything that talks to an external
  service are **high** risk.
- Translation files, readme wording and screenshots are **low** risk when
  nothing else changes.

## Lessons learned

<!-- Rules proposed by the weekly learnings job and merged by a human. -->

- When a change adds a retry, a scheduled fallback event, a failure callback or a row that holds billed remote state (an unfinished multipart upload), check every path that ends the work, fails it or deletes the row: each must clear the event, run the callback or abort the remote state, including a 200 with an error body and a transport error.
- When a header, limit or option must apply to every request or upload path, check that a test covers each variant (single, multipart, copy, resumed, pooled; `wp_remote` and curl), not only the simplest one.
