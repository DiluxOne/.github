<?php
/**
 * What wordpress.org's plugin review flags and Plugin Check does not.
 *
 * Every DiluxOne plugin passed PHPCS, PHPStan, Psalm and Plugin Check and was
 * still sent back: the review reads the code, and its tools treat some shapes
 * as findings whatever the comment beside them says. This checks the shipped
 * tree for those shapes, with PHP's own tokenizer rather than a regular
 * expression, so a string or a comment is never mistaken for code.
 *
 *   php wp-review-patterns.php <dir>
 *
 * Errors (exit 1), each one a finding in a real review:
 *
 *   escape-suppressed  A `phpcs:ignore` / `phpcs:disable` of
 *                      WordPress.Security.EscapeOutput. The review reads it as
 *                      unescaped output, whatever the justification says
 *                      ("escaped inside", "our own markup"). Escape at the
 *                      line that prints: `wp_kses()` with an allow-list for
 *                      markup built as a string, a template that prints
 *                      itself instead of a string that is echoed.
 *   menu-position      `add_menu_page()` with a position before the end of
 *                      WordPress's own menu (below 100). "High position for
 *                      your admin dashboard menu item": leave it out, or put
 *                      the screen under Settings / Tools.
 *
 * Warnings (annotated, exit 0), each one worth a look before submitting:
 *
 *   nonce-elsewhere    A NonceVerification suppression whose reason says the
 *                      check is somewhere else ("the caller verifies it",
 *                      "checked below"). A reviewer reads the line in
 *                      isolation; verify in the handler, before the read.
 *   notice-unscoped    A function hooked to an admin notice that never asks
 *                      which screen it is on: guideline 11 wants notices on
 *                      the plugin's own screens, the dashboard or the plugins
 *                      list, and dismissible when they are not urgent.
 *
 *   php wp-review-patterns.php --test
 *
 * Runs its own tests.
 *
 * @package DiluxOne
 */

declare(strict_types=1);

const WRP_NOTICE_HOOKS = array( 'admin_notices', 'network_admin_notices', 'all_admin_notices', 'user_admin_notices' );

/**
 * Every finding in one PHP file.
 *
 * @return list<array{level: string, rule: string, line: int, message: string}>
 */
function wrp_check_source( string $code ): array {
	$tokens   = token_get_all( $code );
	$findings = array();
	$count    = count( $tokens );

	foreach ( $tokens as $i => $token ) {
		if ( ! is_array( $token ) ) {
			continue;
		}

		list( $type, $text, $line ) = $token;

		if ( T_COMMENT === $type || T_DOC_COMMENT === $type ) {
			if ( preg_match( '/phpcs:(ignore|disable)\b[^\n]*WordPress\.Security\.EscapeOutput/', $text ) ) {
				$findings[] = wrp_finding( 'error', 'escape-suppressed', $line, 'Output escaping is suppressed here. wordpress.org reads this as unescaped output: escape at this line (wp_kses() with an allow-list for markup built as a string, or a template that prints itself).' );
			}

			if ( preg_match( '/phpcs:(ignore|disable)\b[^\n]*WordPress\.Security\.NonceVerification[^\n]*--([^\n]*)/', $text, $why )
				&& preg_match( '/\b(caller|callers|verif\w*\s+(it|this|them|above|below|elsewhere|by|in|first)|checked\s+(above|below|by|in|elsewhere)|the\s+(panel|dispatcher|handler|router)\b)/i', $why[2] )
			) {
				$findings[] = wrp_finding( 'warning', 'nonce-elsewhere', $line, 'The nonce is said to be checked somewhere else. A reviewer reads this line on its own: verify the nonce and the capability in this function, before the first read.' );
			}

			continue;
		}

		if ( T_STRING !== $type || 'add_menu_page' !== strtolower( $text ) || wrp_is_definition( $tokens, $i ) ) {
			continue;
		}

		$args = wrp_call_args( $tokens, $i, $count );

		if ( count( $args ) < 7 ) {
			continue;
		}

		$position = trim( $args[6] );

		if ( '' === $position || 'null' === strtolower( $position ) ) {
			continue;
		}

		if ( is_numeric( $position ) && (float) $position >= 100 ) {
			continue;
		}

		$findings[] = wrp_finding( 'error', 'menu-position', $line, sprintf( 'add_menu_page() asks for position %s, among WordPress\'s own menus. wordpress.org flags it ("high position for your admin dashboard menu item"): leave the position out, or move the screen under Settings or Tools.', $position ) );
	}

	foreach ( wrp_notice_callbacks( $tokens, $count ) as $callback => $line ) {
		$body = wrp_function_body( $tokens, $count, $callback );

		if ( null === $body ) {
			continue;
		}

		if ( ! preg_match( '/get_current_screen|\$pagenow|\[\s*[\'"]pagenow[\'"]\s*\]|\$hook_suffix|current_screen|is-dismissible|_here\s*\(|screen\w*\s*\(/i', $body ) ) {
			$findings[] = wrp_finding( 'warning', 'notice-unscoped', $line, sprintf( '%s() is an admin notice that never asks which screen it is on. Show it on the plugin\'s own screens, the dashboard or the plugins list (guideline 11), or hook it from a load-<screen> action.', $callback ) );
		}
	}

	usort( $findings, static fn( array $a, array $b ): int => $a['line'] <=> $b['line'] );

	return $findings;
}

/** @return array{level: string, rule: string, line: int, message: string} */
function wrp_finding( string $level, string $rule, int $line, string $message ): array {
	return array(
		'level'   => $level,
		'rule'    => $rule,
		'line'    => $line,
		'message' => $message,
	);
}

/**
 * Whether the name at $i is being declared rather than called.
 *
 * @param array<int, mixed> $tokens
 */
function wrp_is_definition( array $tokens, int $i ): bool {
	for ( $j = $i - 1; $j >= 0; $j-- ) {
		if ( is_array( $tokens[ $j ] ) && T_WHITESPACE === $tokens[ $j ][0] ) {
			continue;
		}

		return is_array( $tokens[ $j ] ) && in_array( $tokens[ $j ][0], array( T_FUNCTION, T_OBJECT_OPERATOR, T_DOUBLE_COLON, T_NEW ), true );
	}

	return false;
}

/**
 * The arguments of the call whose name is at $i, as source text, split on the
 * commas at its own depth.
 *
 * @param array<int, mixed> $tokens
 * @return list<string>
 */
function wrp_call_args( array $tokens, int $i, int $count ): array {
	$j = $i + 1;

	while ( $j < $count && is_array( $tokens[ $j ] ) && T_WHITESPACE === $tokens[ $j ][0] ) {
		++$j;
	}

	if ( $j >= $count || '(' !== $tokens[ $j ] ) {
		return array();
	}

	$args  = array();
	$now   = '';
	$depth = 0;

	for ( $j = $j + 1; $j < $count; $j++ ) {
		$token = $tokens[ $j ];
		$text  = is_array( $token ) ? $token[1] : $token;

		if ( is_array( $token ) && in_array( $token[0], array( T_COMMENT, T_DOC_COMMENT ), true ) ) {
			continue;
		}

		if ( in_array( $text, array( '(', '[', '{' ), true ) || ( is_array( $token ) && in_array( $token[0], array( T_CURLY_OPEN, T_DOLLAR_OPEN_CURLY_BRACES ), true ) ) ) {
			++$depth;
		} elseif ( in_array( $text, array( ')', ']', '}' ), true ) ) {
			if ( 0 === $depth ) {
				break;
			}
			--$depth;
		} elseif ( ',' === $text && 0 === $depth ) {
			$args[] = $now;
			$now    = '';
			continue;
		}

		$now .= $text;
	}

	if ( '' !== trim( $now ) ) {
		$args[] = $now;
	}

	return $args;
}

/**
 * The functions hooked to an admin notice by name, with the line of the hook.
 *
 * @param array<int, mixed> $tokens
 * @return array<string, int>
 */
function wrp_notice_callbacks( array $tokens, int $count ): array {
	$callbacks = array();
	$depth     = 0;

	foreach ( $tokens as $i => $token ) {
		$text = is_array( $token ) ? $token[1] : $token;

		if ( '{' === $text || ( is_array( $token ) && in_array( $token[0], array( T_CURLY_OPEN, T_DOLLAR_OPEN_CURLY_BRACES ), true ) ) ) {
			++$depth;
		} elseif ( '}' === $text ) {
			--$depth;
		}

		// A notice hooked from inside a function is hooked when that function
		// decides — from a load-<screen> action, on one screen. Only the ones
		// hooked as the file loads speak on every screen unless they ask.
		if ( $depth > 0 || ! is_array( $token ) || T_STRING !== $token[0] || 'add_action' !== strtolower( $token[1] ) || wrp_is_definition( $tokens, $i ) ) {
			continue;
		}

		$args = wrp_call_args( $tokens, $i, $count );

		if ( count( $args ) < 2 ) {
			continue;
		}

		$hook     = trim( $args[0], " \t\n\r'\"" );
		$callback = trim( $args[1], " \t\n\r'\"" );

		if ( in_array( $hook, WRP_NOTICE_HOOKS, true ) && preg_match( '/^[A-Za-z_][A-Za-z0-9_]*$/', $callback ) ) {
			$callbacks[ $callback ] = $token[2];
		}
	}

	return $callbacks;
}

/**
 * The source of a function declared in the same file, or null.
 *
 * @param array<int, mixed> $tokens
 */
function wrp_function_body( array $tokens, int $count, string $name ): ?string {
	foreach ( $tokens as $i => $token ) {
		if ( ! is_array( $token ) || T_FUNCTION !== $token[0] ) {
			continue;
		}

		$j = $i + 1;

		while ( $j < $count && is_array( $tokens[ $j ] ) && T_WHITESPACE === $tokens[ $j ][0] ) {
			++$j;
		}

		if ( ! is_array( $tokens[ $j ] ?? null ) || strtolower( $tokens[ $j ][1] ) !== strtolower( $name ) ) {
			continue;
		}

		while ( $j < $count && '{' !== $tokens[ $j ] ) {
			++$j;
		}

		$body  = '';
		$depth = 0;

		for ( ; $j < $count; $j++ ) {
			$text = is_array( $tokens[ $j ] ) ? $tokens[ $j ][1] : $tokens[ $j ];

			if ( '{' === $text || ( is_array( $tokens[ $j ] ) && in_array( $tokens[ $j ][0], array( T_CURLY_OPEN, T_DOLLAR_OPEN_CURLY_BRACES ), true ) ) ) {
				++$depth;
			} elseif ( '}' === $text ) {
				--$depth;
			}

			$body .= $text;

			if ( 0 === $depth ) {
				return $body;
			}
		}
	}

	return null;
}

/**
 * Every finding under a directory, by file.
 *
 * @return array<string, list<array{level: string, rule: string, line: int, message: string}>>
 */
function wrp_check_dir( string $dir ): array {
	$found = array();
	$files = new RecursiveIteratorIterator( new RecursiveDirectoryIterator( $dir, FilesystemIterator::SKIP_DOTS ) );

	foreach ( $files as $file ) {
		$path     = (string) $file;
		$relative = ltrim( substr( $path, strlen( rtrim( $dir, '/' ) ) ), '/' );

		// What does not ship: run on the built tree there is none of it, run
		// on a checkout it is skipped here.
		if ( '.php' !== substr( $path, -4 ) || preg_match( '#(^|/)(vendor|node_modules|tests?|build|\.[^/]+)/#', $relative ) ) {
			continue;
		}

		$findings = wrp_check_source( (string) file_get_contents( $path ) );

		if ( array() !== $findings ) {
			$found[ $relative ] = $findings;
		}
	}

	ksort( $found );

	return $found;
}

function wrp_main( string $dir ): int {
	if ( ! is_dir( $dir ) ) {
		fwrite( STDERR, "Not a directory: $dir\n" );

		return 2;
	}

	$errors   = 0;
	$warnings = 0;
	$github   = 'true' === getenv( 'GITHUB_ACTIONS' );
	$prefix   = (string) getenv( 'WRP_PATH_PREFIX' );

	foreach ( wrp_check_dir( $dir ) as $file => $findings ) {
		foreach ( $findings as $finding ) {
			'error' === $finding['level'] ? ++$errors : ++$warnings;

			if ( $github ) {
				printf( "::%s file=%s,line=%d,title=%s::%s\n", $finding['level'], $prefix . $file, $finding['line'], $finding['rule'], $finding['message'] );
			} else {
				printf( "%s:%d  %s  %s: %s\n", $file, $finding['line'], $finding['level'], $finding['rule'], $finding['message'] );
			}
		}
	}

	printf( "%d error(s), %d warning(s).\n", $errors, $warnings );

	return $errors > 0 ? 1 : 0;
}

/** The self-test: each rule, on code that must and must not trip it. */
function wrp_test(): int {
	$cases = array(
		'escape ignore'                  => array( "<?php\necho \$x; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- escaped inside.\n", array( 'escape-suppressed' ) ),
		'escape disable'                 => array( "<?php\n// phpcs:disable WordPress.Security.EscapeOutput\necho \$x;\n", array( 'escape-suppressed' ) ),
		'escaped at the line'            => array( "<?php\necho wp_kses( \$x, \$allowed );\n", array() ),
		'other sniff ignored'            => array( "<?php\n\$a = \$_GET['tab']; // phpcs:ignore WordPress.Security.NonceVerification.Recommended -- which tab to draw.\n", array() ),
		'nonce elsewhere'                => array( "<?php\n// phpcs:disable WordPress.Security.NonceVerification.Missing -- the panel verifies it.\n", array( 'nonce-elsewhere' ) ),
		'nonce by the caller'            => array( "<?php\n\$a = \$_POST['a']; // phpcs:ignore WordPress.Security.NonceVerification.Missing -- the caller checks the nonce.\n", array( 'nonce-elsewhere' ) ),
		'menu at 22'                     => array( "<?php\nadd_menu_page( 'A', 'A', 'manage_options', 'a', 'cb', 'dashicons-groups', 22 );\n", array( 'menu-position' ) ),
		'menu at a constant'             => array( "<?php\nadd_menu_page(\n\t__( 'A', 'a' ),\n\t'A',\n\t'manage_options',\n\t'a',\n\tarray( \$this, 'cb' ),\n\t'dashicons-groups',\n\tMY_POSITION\n);\n", array( 'menu-position' ) ),
		'menu without a position'        => array( "<?php\nadd_menu_page( 'A', 'A', 'manage_options', 'a', 'cb', 'dashicons-groups' );\n", array() ),
		'menu with null'                 => array( "<?php\nadd_menu_page( 'A', 'A', 'manage_options', 'a', 'cb', '', null );\n", array() ),
		'menu after settings'            => array( "<?php\nadd_menu_page( 'A', 'A', 'manage_options', 'a', 'cb', '', 100 );\n", array() ),
		'menu in a string'               => array( "<?php\n\$doc = \"add_menu_page( 'A', 'A', 'm', 'a', 'cb', '', 2 )\";\n", array() ),
		'menu declared'                  => array( "<?php\nfunction add_menu_page( \$a, \$b, \$c, \$d, \$e, \$f, \$g ) {}\n", array() ),
		'notice everywhere'              => array( "<?php\nfunction my_notice() { echo '<div class=\"notice\"><p>Hi</p></div>'; }\nadd_action( 'admin_notices', 'my_notice' );\n", array( 'notice-unscoped' ) ),
		'notice on its screen'           => array( "<?php\nfunction my_notice() { if ( 'my' !== get_current_screen()->id ) { return; } echo 'x'; }\nadd_action( 'admin_notices', 'my_notice' );\n", array() ),
		'notice by pagenow'              => array( "<?php\nfunction my_notice() { if ( 'index.php' !== \$GLOBALS['pagenow'] ) { return; } echo 'x'; }\nadd_action( 'network_admin_notices', 'my_notice' );\n", array() ),
		'notice dismissible'             => array( "<?php\nfunction my_notice() { echo '<div class=\"notice is-dismissible\"></div>'; }\nadd_action( 'admin_notices', 'my_notice' );\n", array() ),
		'notice through a scope helper'  => array( "<?php\nfunction my_notice() { if ( ! my_notice_here() ) { return; } echo 'x'; }\nadd_action( 'admin_notices', 'my_notice' );\n", array() ),
		'notice defined in another file' => array( "<?php\nadd_action( 'admin_notices', 'elsewhere_notice' );\n", array() ),
		'notice hooked on one screen'    => array( "<?php\nfunction my_notice() { echo 'x'; }\nfunction my_hook() { add_action( 'admin_notices', 'my_notice' ); }\nadd_action( 'load-index.php', 'my_hook' );\n", array() ),
	);

	$failed = 0;

	foreach ( $cases as $name => list( $code, $expected ) ) {
		$got = array_values( array_unique( array_column( wrp_check_source( $code ), 'rule' ) ) );

		if ( $got !== $expected ) {
			++$failed;
			printf( "FAIL %s: expected [%s], got [%s]\n", $name, implode( ', ', $expected ), implode( ', ', $got ) );
		}
	}

	$dir = sys_get_temp_dir() . '/wrp-' . getmypid();
	mkdir( $dir . '/includes', 0777, true );
	mkdir( $dir . '/vendor/x', 0777, true );
	mkdir( $dir . '/build/x', 0777, true );
	file_put_contents( $dir . '/build/x/c.php', "<?php\necho \$x; // phpcs:ignore WordPress.Security.EscapeOutput\n" );
	file_put_contents( $dir . '/includes/a.php', "<?php\nadd_menu_page( 'A', 'A', 'm', 'a', 'cb', '', 3 );\n" );
	file_put_contents( $dir . '/vendor/x/b.php', "<?php\necho \$x; // phpcs:ignore WordPress.Security.EscapeOutput\n" );

	ob_start();
	$exit = wrp_main( $dir );
	$out  = (string) ob_get_clean();

	if ( 1 !== $exit || false === strpos( $out, 'includes/a.php:2' ) || false !== strpos( $out, 'vendor' ) || false !== strpos( $out, 'build' ) ) {
		++$failed;
		printf( "FAIL directory: exit %d, output:\n%s", $exit, $out );
	}

	array_map( 'unlink', array( $dir . '/includes/a.php', $dir . '/vendor/x/b.php', $dir . '/build/x/c.php' ) );
	array_map( 'rmdir', array( $dir . '/includes', $dir . '/vendor/x', $dir . '/vendor', $dir . '/build/x', $dir . '/build', $dir ) );

	printf( "%s: %d case(s), %d failed.\n", 0 === $failed ? 'ok' : 'FAILED', count( $cases ) + 1, $failed );

	return 0 === $failed ? 0 : 1;
}

if ( PHP_SAPI === 'cli' && realpath( (string) ( $argv[0] ?? '' ) ) === __FILE__ ) {
	$arg = (string) ( $argv[1] ?? '' );

	if ( '--test' === $arg ) {
		exit( wrp_test() );
	}

	if ( '' === $arg || '-h' === $arg || '--help' === $arg ) {
		fwrite( STDERR, "Usage: php wp-review-patterns.php <dir> | --test\n" );
		exit( '' === $arg ? 2 : 0 );
	}

	exit( wrp_main( $arg ) );
}
