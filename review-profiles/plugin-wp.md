# Review profile: WordPress plugin (`plugin-wp`)

For plugins published on wordpress.org. Every rule comes from the Plugin
Review Team's guidelines or from a real rejection; the automated tools
passed each time, so check them by reading the code.

## Input, output, permissions

- **Every `$_POST` / `$_GET` / `$_REQUEST` / `$_COOKIE` / `$_SERVER` value is
  unslashed, sanitised and validated before use:**
  `sanitize_text_field( wp_unslash( $_POST['x'] ?? '' ) )`. Sanitising
  later, inside a DTO, does not count, and never pass a whole superglobal
  to a helper: read only the named fields.
- **Output is escaped late,** with the escaper for its context
  (`esc_html`, `esc_attr`, `esc_url`, `wp_kses`); translated strings too
  (`esc_html__`).
- **Every AJAX / REST / admin-post handler checks a nonce and a
  capability** (`check_ajax_referer` + `current_user_can`).
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
